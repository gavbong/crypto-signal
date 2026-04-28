"""
signal_engine.py — Phase 1a shadow mode signal generator.
Runs every 1 minute via APScheduler.
"""
import sys
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, get as cfg
from utils.ccxt_wrapper import _make_exchange, fetch_ohlcv_safe
from db.schema import init_db, get_conn, log_signal, is_duplicate
from regime.classifier import classify, _to_df
from signals.selector import active_strategies
from signals.generator import run_strategy
from llm.commentary import generate_commentary
from eval.outcomes import run_evaluation
from alerts.telegram import send_signal_alert


logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
logger.add("logs/signal_engine.log", rotation="1 day", retention="7 days", level="DEBUG")


def _build_regime_context(exchange, pairs: list, timeframe: str, limit: int) -> dict:
    """Fetch current regime for all pairs — used as LLM context."""
    context = {}
    for pair in pairs:
        ohlcv = fetch_ohlcv_safe(exchange, pair, timeframe, limit)
        if ohlcv is None or len(ohlcv) < 55:
            continue
        try:
            result = classify(ohlcv)
            context[pair] = {
                "regime": result.label,
                "confidence": result.confidence,
                "age_candles": result.age_candles,
                "stable": result.stable,
            }
        except ValueError:
            pass
    return context


def run_once(exchange, conn, pairs: list, timeframe: str, limit: int,
             dedup_window: int, regime_context: dict, shadow_mode: bool = True) -> list[dict]:
    """One signal engine cycle. Returns list of signals fired this run."""
    fired = []

    for pair in pairs:
        ohlcv = fetch_ohlcv_safe(exchange, pair, timeframe, limit)
        if ohlcv is None:
            logger.warning(f"Skipping {pair}: no candle data")
            continue

        if len(ohlcv) < 55:
            logger.warning(f"Skipping {pair}: only {len(ohlcv)} candles (need 55)")
            continue

        try:
            regime = classify(ohlcv)
        except ValueError as e:
            logger.warning(f"Regime error on {pair}: {e}")
            continue

        if not regime.stable:
            logger.debug(f"{pair}: regime {regime.label} not stable yet ({regime.age_candles} candles)")
            continue

        strategies = active_strategies(regime.label)
        if not strategies:
            logger.debug(f"{pair}: no active strategies for regime {regime.label}")
            continue

        df = _to_df(ohlcv)

        for strategy in strategies:
            signal = run_strategy(strategy, pair, df, regime, timeframe)
            if signal is None:
                continue

            # Deduplication check
            if is_duplicate(conn, pair, signal["direction"], strategy,
                            regime.label, dedup_window):
                logger.debug(f"Duplicate suppressed: {pair} {signal['direction']} {strategy} {regime.label}")
                continue

            # Generate LLM commentary (non-blocking: failure logs null)
            commentary = generate_commentary(signal, regime_context)
            signal["llm_commentary"] = commentary
            signal["commentary_status"] = "done" if commentary else "pending"

            signal["shadow_mode"] = shadow_mode
            signal_id = log_signal(conn, signal)
            signal["id"] = signal_id

            mode_str = "SHADOW" if shadow_mode else "LIVE"
            logger.info(
                f"SIGNAL [{signal_id}] [{mode_str}] {pair} {signal['direction'].upper()} "
                f"| strategy={strategy} regime={regime.label}({regime.confidence:.2f}) "
                f"age={regime.age_candles}h | entry={signal['entry_price']} "
                f"stop={signal['suggested_stop_loss']}"
            )
            if commentary:
                logger.info(f"  Commentary: {commentary}")

            send_signal_alert(signal)
            fired.append(signal)

    return fired


def signal_job(exchange, pairs: list, timeframe: str, limit: int,
               dedup_window: int, shadow_mode: bool) -> None:
    with get_conn() as conn:
        regime_context = _build_regime_context(exchange, pairs, timeframe, limit)
        fired = run_once(exchange, conn, pairs, timeframe, limit, dedup_window,
                         regime_context, shadow_mode)
        if not fired:
            logger.debug(f"No signals this run at {datetime.now(timezone.utc).isoformat()}")


def eval_job(exchange) -> None:
    with get_conn() as conn:
        result = run_evaluation(conn, exchange)
        logger.info(f"Outcome evaluation complete | resolved={result['resolved']}")


def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    init_db()
    c = cfg()

    exchange = _make_exchange(env("MEXC_API_KEY"), env("MEXC_SECRET"))
    pairs = c["pairs"]
    timeframe = c["timeframe"]
    limit = c["candle_limit"]
    dedup_window = c["deduplication"]["window_candles"]
    outcome_window_h = c["walk_forward"]["outcome_window_hours"]
    shadow_mode = c.get("shadow_mode", True)

    mode_label = "SHADOW" if shadow_mode else "LIVE"
    logger.info(f"Signal engine starting | pairs={pairs} timeframe={timeframe} mode={mode_label}")

    scheduler = BlockingScheduler(timezone="UTC")

    # Signal scan: every hour, aligned to the candle close
    scheduler.add_job(
        signal_job,
        "interval",
        hours=1,
        args=[exchange, pairs, timeframe, limit, dedup_window, shadow_mode],
        next_run_time=datetime.now(timezone.utc),
    )

    # Outcome evaluation: every outcome_window_hours (default 4h)
    scheduler.add_job(
        eval_job,
        "interval",
        hours=outcome_window_h,
        args=[exchange],
        next_run_time=datetime.now(timezone.utc),
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Signal engine stopped by user")


if __name__ == "__main__":
    main()
