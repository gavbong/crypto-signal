"""
signal_engine.py — Phase 1a shadow mode signal generator.
Runs every 15 minutes via APScheduler. Uses 1h candles for regime
classification (MTF) and 15m candles for signal indicator calculation.
"""
import sys
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, get as cfg
from utils.ccxt_wrapper import make_exchange, fetch_ohlcv_safe, fetch_ticker_safe
from db.schema import init_db, get_conn, log_signal, is_duplicate, log_regime
from regime.classifier import classify, RegimeResult, _to_df
from signals.selector import active_strategies
from signals.generator import run_strategy, _calc_take_profit
from llm.commentary import generate_commentary
from apscheduler.triggers.cron import CronTrigger
from eval.outcomes import run_evaluation
from alerts.telegram import send_signal_alert
from strategy_advisor import run_strategy_review




def _market_session(utc_hour: int) -> str:
    if 0 <= utc_hour < 8:
        return "Asia 🌏"
    if 8 <= utc_hour < 13:
        return "London 🇬🇧"
    if 13 <= utc_hour < 17:
        return "Overlap (London/NY) 🌍"
    if 17 <= utc_hour < 22:
        return "New York 🗽"
    return "Off-hours 🌙"


def _build_regime_context(
    exchange, pairs: list, timeframe: str, limit: int
) -> tuple[dict[str, RegimeResult], dict]:
    """Fetch 1h regime for all pairs.
    Returns (regimes, df_1h_map) — the 1h dataframes are reused by S/D zone detection."""
    context: dict[str, RegimeResult] = {}
    df_1h_map: dict = {}
    for pair in pairs:
        ohlcv = fetch_ohlcv_safe(exchange, pair, timeframe, limit)
        if ohlcv is None or len(ohlcv) < 55:
            continue
        try:
            result = classify(ohlcv)
            context[pair] = result
            df_1h_map[pair] = _to_df(ohlcv)
        except ValueError:
            pass
    return context, df_1h_map


def run_once(exchange, conn, pairs: list, timeframe: str, limit: int,
             dedup_window: int, regimes_1h: dict[str, RegimeResult],
             df_1h_map: dict | None = None,
             shadow_mode: bool = True,
             exchange_id: str = "mexc") -> list[dict]:
    """One signal engine cycle. Uses pre-built 1h regimes; fetches 15m candles for indicators."""
    fired = []

    for pair in pairs:
        # Use 1h regime from pre-built MTF context
        regime = regimes_1h.get(pair)
        if regime is None:
            logger.warning(f"Skipping {pair}: no 1h regime available")
            continue

        if not regime.stable:
            logger.debug(f"{pair}: regime {regime.label} not stable yet ({regime.age_candles} candles)")
            continue

        strategies = active_strategies(regime.label)
        if not strategies:
            logger.debug(f"{pair}: no active strategies for regime {regime.label}")
            continue

        # Fetch 15m candles for signal indicator calculation
        ohlcv = fetch_ohlcv_safe(exchange, pair, timeframe, limit)
        if ohlcv is None:
            logger.warning(f"Skipping {pair}: no 15m candle data")
            continue

        if len(ohlcv) < 55:
            logger.warning(f"Skipping {pair}: only {len(ohlcv)} candles (need 55)")
            continue

        df = _to_df(ohlcv)

        # Fetch live price once per pair — candle close can be up to 14 min stale on 15m
        live_price: float | None = None
        ticker = fetch_ticker_safe(exchange, pair)
        if ticker and ticker.get("last"):
            live_price = float(ticker["last"])
        else:
            logger.warning(f"{pair}: ticker fetch failed, using candle close as entry price")

        df_1h = (df_1h_map or {}).get(pair)

        for strategy in strategies:
            signal = run_strategy(strategy, pair, df, regime, timeframe, df_1h=df_1h)
            if signal is None:
                continue

            # Reanchor entry/stop/TP to live market price using per-regime RR
            if live_price is not None:
                risk = abs(signal["entry_price"] - signal["suggested_stop_loss"])
                live_stop = (round(live_price - risk, 8) if signal["direction"] == "long"
                             else round(live_price + risk, 8))
                signal["entry_price"] = round(live_price, 8)
                signal["suggested_stop_loss"] = live_stop
                signal["suggested_take_profit"] = _calc_take_profit(
                    live_price, live_stop, signal["direction"], regime.label
                )

            # Deduplication check (per-exchange — each exchange fires independently)
            if is_duplicate(conn, pair, signal["direction"], strategy,
                            regime.label, dedup_window, exchange=exchange_id):
                logger.debug(f"Duplicate suppressed: {pair} {signal['direction']} {strategy} {regime.label}")
                continue

            # Serialize RegimeResult to plain dict for LLM commentary (JSON-safe)
            regime_context_for_llm = {
                p: {"regime": r.label, "confidence": r.confidence,
                    "age_candles": r.age_candles, "stable": r.stable}
                for p, r in regimes_1h.items()
            }
            commentary = generate_commentary(signal, regime_context_for_llm)
            signal["llm_commentary"] = commentary
            signal["commentary_status"] = "done" if commentary else "pending"

            signal["shadow_mode"] = shadow_mode
            signal["exchange"] = exchange_id
            signal["market_session"] = _market_session(datetime.now(timezone.utc).hour)
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


def signal_job(exchanges_config: list, timeframe: str, limit: int,
               dedup_window: int, shadow_mode: bool) -> None:
    """exchanges_config: list of (exchange_id, exchange_obj, pairs)"""
    c = cfg()
    with get_conn() as conn:
        for exchange_id, exchange, pairs in exchanges_config:
            regimes_1h, df_1h_map = _build_regime_context(
                exchange, pairs, c["regime_timeframe"], c["regime_limit"]
            )
            fired = run_once(exchange, conn, pairs, timeframe, limit, dedup_window,
                             regimes_1h, df_1h_map, shadow_mode, exchange_id=exchange_id)
            if not fired:
                logger.debug(f"[{exchange_id}] No signals at {datetime.now(timezone.utc).isoformat()}")
            for pair, regime in regimes_1h.items():
                log_regime(conn, pair, regime.label, regime.confidence,
                           regime.age_candles, regime.stable)


def eval_job(exchange) -> None:
    with get_conn() as conn:
        result = run_evaluation(conn, exchange)
        logger.info(f"Outcome evaluation complete | resolved={result['resolved']}")


def review_job() -> None:
    try:
        rows = run_strategy_review()
        disable_count = sum(1 for r in rows if r["status"] == "DISABLE")
        logger.info(f"Strategy review complete | pairs={len(rows)} disable={disable_count}")
    except Exception as e:
        logger.error(f"Strategy review failed: {e}")


def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="{time:HH:mm:ss} | {level:<7} | signal | {message}")
    logger.add("logs/signal_engine.log", rotation="1 day", retention="7 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}")

    init_db()
    c = cfg()

    timeframe = c["timeframe"]
    limit = c["candle_limit"]
    dedup_window = c["deduplication"]["window_candles"]
    outcome_window_h = c["walk_forward"]["outcome_window_hours"]
    shadow_mode = c.get("shadow_mode", True)

    exchanges_config = []
    for exc_id, exc_cfg in c.get("exchanges", {}).items():
        if not exc_cfg.get("enabled", False):
            continue
        try:
            exchange = make_exchange(exc_id)
            exchanges_config.append((exc_id, exchange, exc_cfg["pairs"]))
            logger.info(f"Exchange enabled: {exc_id} | pairs={exc_cfg['pairs']}")
        except Exception as e:
            logger.error(f"Failed to init exchange {exc_id}: {e}")

    if not exchanges_config:
        logger.error("No exchanges enabled — check config.yaml")
        return

    # Use the first exchange for outcome evaluation (price lookups)
    primary_exchange = exchanges_config[0][1]

    mode_label = "SHADOW" if shadow_mode else "LIVE"
    logger.info(f"Signal engine starting | exchanges={[e[0] for e in exchanges_config]} timeframe={timeframe} mode={mode_label}")

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        signal_job,
        "interval",
        minutes=15,
        args=[exchanges_config, timeframe, limit, dedup_window, shadow_mode],
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        eval_job,
        "interval",
        hours=outcome_window_h,
        args=[primary_exchange],
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        review_job,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        misfire_grace_time=3600,
    )

    # Run once at startup so the first deployment always has fresh review data
    review_job()

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Signal engine stopped by user")


if __name__ == "__main__":
    main()
