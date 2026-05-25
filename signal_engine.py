"""
signal_engine.py — Multi-exchange signal generator.
Runs every 15 minutes via APScheduler. Uses 1h candles for regime
classification (MTF) and 15m candles for signal indicator calculation.

Per cycle: collects candidates from all exchanges, picks the highest-confidence
signal per (base_asset, direction, strategy, regime), then emits the winner.
"""
import sys
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from zoneinfo import ZoneInfo
from utils.config import env, get as cfg
from utils.ccxt_wrapper import make_exchange, fetch_ohlcv_safe, fetch_ticker_safe
from utils.market_hours import is_index_market_open
from db.schema import init_db, get_conn, log_signal, is_duplicate, log_regime
from regime.classifier import classify, RegimeResult, _to_df
from signals.selector import active_strategies
from signals.generator import run_strategy, _calc_take_profit
from signals.quality import compute_quality_score, is_stop_in_range, update_strategy_health
from llm.commentary import generate_commentary
from apscheduler.triggers.cron import CronTrigger
from eval.outcomes import run_evaluation
from alerts.telegram import send_signal_alert
from strategy_advisor import run_strategy_review




_is_market_open = is_index_market_open


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


def _collect_candidates(
    exchange,
    pairs: list,
    timeframe: str,
    limit: int,
    regimes_1h: dict[str, RegimeResult],
    df_1h_map: dict | None,
    exchange_id: str,
    shadow_mode: bool,
    conn,
) -> list[dict]:
    """Collect potential signals from one exchange without emitting.
    No dedup check, no LLM commentary, no alerts. Returns raw candidates
    so signal_job can compare quality across exchanges before firing."""
    candidates = []
    c = cfg()
    sq_cfg = c.get("signal_quality", {})
    min_quality = sq_cfg.get("min_quality_score", 40)
    rg_gates = c.get("regime_gates", {}).get("min_regime_age_candles", {})

    regime_context_for_llm = {
        p: {"regime": r.label, "confidence": r.confidence,
            "age_candles": r.age_candles, "stable": r.stable}
        for p, r in regimes_1h.items()
    }

    for pair in pairs:
        regime = regimes_1h.get(pair)
        if regime is None:
            logger.warning(f"Skipping {pair}: no 1h regime available")
            continue

        if not regime.stable:
            logger.debug(f"{pair}: regime {regime.label} not stable yet ({regime.age_candles} candles)")
            continue

        # Regime age gate: require minimum consecutive candles in this regime
        min_age = rg_gates.get(regime.label, 0)
        if regime.age_candles < min_age:
            logger.debug(f"{pair}: regime {regime.label} too young ({regime.age_candles} < {min_age} candles)")
            continue

        strategies = active_strategies(regime.label)
        if not strategies:
            logger.debug(f"{pair}: no active strategies for regime {regime.label}")
            continue

        ohlcv = fetch_ohlcv_safe(exchange, pair, timeframe, limit)
        if ohlcv is None:
            logger.warning(f"Skipping {pair}: no 15m candle data")
            continue
        if len(ohlcv) < 55:
            logger.warning(f"Skipping {pair}: only {len(ohlcv)} candles (need 55)")
            continue

        df = _to_df(ohlcv)

        live_price: float | None = None
        ticker = fetch_ticker_safe(exchange, pair)
        if ticker and ticker.get("last"):
            live_price = float(ticker["last"])
        else:
            logger.warning(f"{pair} [{exchange_id}]: ticker failed, using candle close")

        df_1h = (df_1h_map or {}).get(pair)

        for strategy in strategies:
            signal = run_strategy(strategy, pair, df, regime, timeframe, df_1h=df_1h)
            if signal is None:
                continue

            if live_price is not None:
                risk = abs(signal["entry_price"] - signal["suggested_stop_loss"])
                live_stop = (round(live_price - risk, 8) if signal["direction"] == "long"
                             else round(live_price + risk, 8))
                signal["entry_price"] = round(live_price, 8)
                signal["suggested_stop_loss"] = live_stop
                signal["suggested_take_profit"] = _calc_take_profit(
                    live_price, live_stop, signal["direction"], regime.label,
                    signal.get("strategy", ""),
                )

            # Stop distance hard gate (per asset class)
            if not is_stop_in_range(signal["entry_price"], signal["suggested_stop_loss"], pair):
                logger.debug(
                    f"{pair} {strategy}: stop distance out of range — skipping "
                    f"(entry={signal['entry_price']}, stop={signal['suggested_stop_loss']})"
                )
                continue

            # Strategy health gate: skip DISABLED combos
            health_row = conn.execute(
                """SELECT status FROM strategy_health
                   WHERE strategy=? AND regime=? AND direction=?""",
                (strategy, regime.label, signal["direction"]),
            ).fetchone()
            if health_row and health_row["status"] == "DISABLED":
                logger.debug(f"{pair} {strategy} {signal['direction']}: DISABLED by strategy health — skipping")
                continue

            # Quality score gate
            quality_score = compute_quality_score(
                conn, strategy, regime.label, regime.confidence,
                signal["direction"], pair, signal["entry_price"], signal["suggested_stop_loss"],
            )
            if quality_score < min_quality:
                logger.debug(
                    f"{pair} {strategy}: quality_score={quality_score} < {min_quality} — skipping"
                )
                continue

            signal["quality_score"] = quality_score
            signal["exchange"] = exchange_id
            signal["shadow_mode"] = shadow_mode
            signal["_regime_context"] = regime_context_for_llm
            candidates.append(signal)

    return candidates


def _pick_best(candidates: list[dict]) -> list[dict]:
    """For each base asset, keep the single candidate with the highest
    regime_confidence. Prevents conflicting long/short signals for the same
    token in the same cycle. Ties go to the first exchange in config order."""
    best: dict[str, dict] = {}
    for signal in candidates:
        base_asset = signal["pair"].split("/")[0]
        existing = best.get(base_asset)
        if existing is None or signal["regime_confidence"] > existing["regime_confidence"]:
            best[base_asset] = signal
    return list(best.values())


def signal_job(exchanges_config: list, timeframe: str, limit: int,
               dedup_window: int, shadow_mode: bool) -> None:
    """exchanges_config: list of (exchange_id, exchange_obj, pairs).

    Flow: collect candidates from all exchanges → pick best per (base_asset,
    direction, strategy, regime) by regime confidence → dedup check → emit winners.
    """
    c = cfg()
    with get_conn() as conn:
        # Pause gate: check settings table before running
        paused_row = conn.execute(
            "SELECT value FROM settings WHERE key='paused'"
        ).fetchone()
        if paused_row and paused_row["value"] == "1":
            logger.info("Signal engine paused via /pause command — skipping cycle")
            return

        all_candidates: list[dict] = []

        for exchange_id, exchange, pairs in exchanges_config:
            active_pairs = [p for p in pairs if _is_market_open(p)]
            if not active_pairs:
                logger.debug(f"{exchange_id}: all pairs outside market hours — skipping")
                continue
            regimes_1h, df_1h_map = _build_regime_context(
                exchange, active_pairs, c["regime_timeframe"], c["regime_limit"]
            )
            candidates = _collect_candidates(
                exchange, active_pairs, timeframe, limit,
                regimes_1h, df_1h_map, exchange_id, shadow_mode, conn,
            )
            all_candidates.extend(candidates)

            for pair, regime in regimes_1h.items():
                log_regime(conn, pair, regime.label, regime.confidence,
                           regime.age_candles, regime.stable)

        winners = _pick_best(all_candidates)
        if not winners:
            logger.debug(f"No signals at {datetime.now(timezone.utc).isoformat()}")
            return

        fired = []
        for signal in winners:
            base_asset = signal["pair"].split("/")[0]
            if is_duplicate(conn, base_asset, signal["direction"],
                            signal["strategy"], signal["regime"], dedup_window):
                logger.debug(
                    f"Duplicate suppressed: {base_asset} {signal['direction']} "
                    f"{signal['strategy']} {signal['regime']}"
                )
                continue

            regime_context = signal.pop("_regime_context", {})
            commentary = generate_commentary(signal, regime_context)
            signal["llm_commentary"] = commentary
            signal["commentary_status"] = "done" if commentary else "pending"
            signal["market_session"] = _market_session(datetime.now(timezone.utc).hour)

            signal_id = log_signal(conn, signal)
            signal["id"] = signal_id

            mode_str = "SHADOW" if shadow_mode else "LIVE"
            logger.info(
                f"SIGNAL [{signal_id}] [{mode_str}] [{signal['exchange'].upper()}] "
                f"{signal['pair']} {signal['direction'].upper()} "
                f"| strategy={signal['strategy']} "
                f"regime={signal['regime']}({signal['regime_confidence']:.2f}) "
                f"age={signal['regime_age_candles']}h | entry={signal['entry_price']} "
                f"stop={signal['suggested_stop_loss']}"
            )
            if commentary:
                logger.info(f"  Commentary: {commentary}")

            send_signal_alert(signal)
            fired.append(signal)


def eval_job(exchange_map: dict) -> None:
    with get_conn() as conn:
        result = run_evaluation(conn, exchange_map)
        logger.info(f"Outcome evaluation complete | resolved={result['resolved']}")
        # Update strategy health for all combos that had new outcomes
        for signal in result.get("resolved_signals", []):
            try:
                update_strategy_health(
                    conn, signal["strategy"], signal["regime"],
                    signal["direction"], signal["pair"],
                )
            except Exception as e:
                logger.warning(f"strategy_health update failed for {signal}: {e}")


def review_job() -> None:
    try:
        rows = run_strategy_review()
        disable_count = sum(1 for r in rows if r["status"] == "DISABLE")
        logger.info(f"Strategy review complete | pairs={len(rows)} disable={disable_count}")
    except Exception as e:
        logger.error(f"Strategy review failed: {e}")


def daily_digest_job() -> None:
    try:
        from alerts.telegram import send_telegram
        from paper_trader import INITIAL_BALANCE

        conn = get_conn()

        state = conn.execute(
            "SELECT value FROM paper_state WHERE key='balance'"
        ).fetchone()
        balance = float(state[0]) if state else INITIAL_BALANCE

        trades = conn.execute("""
            SELECT exit_reason, COUNT(*) as n, COALESCE(SUM(pnl_usdt), 0) as pnl
            FROM paper_positions
            WHERE closed_at >= datetime('now', '-1 day') AND closed_at IS NOT NULL
            GROUP BY exit_reason
        """).fetchall()

        wrs = conn.execute("""
            SELECT strategy, COUNT(*) as n,
                   SUM(CASE WHEN exit_reason='take_profit' THEN 1 ELSE 0 END) as wins
            FROM paper_positions
            WHERE closed_at >= datetime('now', '-7 days') AND closed_at IS NOT NULL
            GROUP BY strategy HAVING n >= 2
        """).fetchall()

        cb = conn.execute(
            "SELECT value FROM paper_state WHERE key='circuit_breaker_until'"
        ).fetchone()

        today_pnl = sum(r["pnl"] for r in trades)
        today_n   = sum(r["n"] for r in trades)
        tp_n  = next((r["n"] for r in trades if r["exit_reason"] == "take_profit"), 0)
        sl_n  = next((r["n"] for r in trades if r["exit_reason"] == "stop_loss"), 0)
        flip_n = next((r["n"] for r in trades if r["exit_reason"] == "signal_flip"), 0)

        cb_val = cb[0] if cb else "0"
        try:
            from datetime import datetime, timezone
            cb_active = cb_val != "0" and datetime.now(timezone.utc) < datetime.fromisoformat(cb_val.replace("Z", "+00:00"))
        except Exception:
            cb_active = False

        sign = "+" if today_pnl >= 0 else ""
        lines = [
            f"📊 Signal Engine — Daily Report {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "",
            f"Paper account: {balance:.0f} USDT ({balance - INITIAL_BALANCE:+.0f} all-time)",
            f"Today ({today_n} trades): {sign}{today_pnl:.2f} USDT  "
            f"({tp_n} TP · {sl_n} SL · {flip_n} flip)",
            "",
            "7d WR by strategy:",
        ]

        for r in sorted(wrs, key=lambda x: x["n"], reverse=True):
            wr = r["wins"] / r["n"] if r["n"] else 0
            icon = "✅" if wr >= 0.40 else ("⚠️" if wr >= 0.30 else "❌")
            lines.append(f"  {r['strategy']:<18} {r['wins']}/{r['n']}  {wr:.0%} {icon}")

        lines.append("")
        lines.append(f"Circuit breaker: {'ON' if cb_active else 'OFF'}")

        send_telegram("\n".join(lines))
        logger.info("Daily digest sent")
    except Exception as e:
        logger.error(f"Daily digest failed: {e}")


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

    indices_cfg = c.get("indices", {})
    if indices_cfg.get("enabled", False):
        from exchanges.index_reader import IndexReader
        index_reader = IndexReader()
        index_pairs = indices_cfg.get("pairs", [])
        exchanges_config.append(("tradenation", index_reader, index_pairs))
        logger.info(f"Index reader enabled | pairs={index_pairs}")

    if not exchanges_config:
        logger.error("No exchanges enabled — check config.yaml")
        return

    exchange_map = {exc_id: exc_obj for exc_id, exc_obj, _ in exchanges_config}

    mode_label = "SHADOW" if shadow_mode else "LIVE"
    logger.info(
        f"Signal engine starting | exchanges={[e[0] for e in exchanges_config]} "
        f"timeframe={timeframe} mode={mode_label}"
    )

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
        args=[exchange_map],
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        review_job,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        daily_digest_job,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    review_job()

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Signal engine stopped by user")


if __name__ == "__main__":
    main()
