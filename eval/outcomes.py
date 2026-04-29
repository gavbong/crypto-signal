from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta, timezone
from loguru import logger

from db.schema import get_pending_outcomes, update_outcome, get_accuracy_stats
from utils.ccxt_wrapper import fetch_ohlcv_safe
from utils.config import get as cfg


def resolve_outcome(signal: sqlite3.Row, exchange) -> tuple[str, float, float | None] | None:
    """
    Fetch 1h candles from signal.fired_at to fired_at + outcome_window_hours.
    Returns (outcome, outcome_price, pnl_r) or None if candle data unavailable.

    outcome: 'win' | 'loss' | 'stopped_out' | 'tp_hit'
    pnl_r: P&L in R-multiples (1R = entry-to-stop distance), None if stop is missing
    """
    c = cfg()["walk_forward"]
    window_h = c["outcome_window_hours"]

    fired_at = datetime.fromisoformat(signal["fired_at"])
    since_ms = int(fired_at.timestamp() * 1000)
    # Fetch one extra candle beyond the window in case of timing offsets
    candles = fetch_ohlcv_safe(
        exchange, signal["pair"], signal["timeframe"],
        limit=window_h + 2, since=since_ms
    )

    if not candles:
        logger.warning(f"No candle data at T+{window_h}h for signal {signal['id']} ({signal['pair']})")
        return None

    entry = signal["entry_price"]
    stop = signal["suggested_stop_loss"]
    take_profit = signal["suggested_take_profit"] if "suggested_take_profit" in signal.keys() else None
    direction = signal["direction"]
    risk = abs(entry - stop) if stop is not None else None

    # Walk forward: check each candle for stop-loss or take-profit hit (in candle order)
    for candle in candles:
        ts_ms, o, h, l, c_close, vol = candle
        if direction == "long":
            if stop is not None and l <= stop:
                logger.debug(f"Signal {signal['id']} stopped out at {stop}")
                return "stopped_out", stop, -1.0
            if take_profit is not None and h >= take_profit:
                pnl_r = (take_profit - entry) / risk if risk else None
                logger.debug(f"Signal {signal['id']} take-profit hit at {take_profit}")
                return "tp_hit", take_profit, pnl_r
        else:
            if stop is not None and h >= stop:
                logger.debug(f"Signal {signal['id']} stopped out at {stop}")
                return "stopped_out", stop, -1.0
            if take_profit is not None and l <= take_profit:
                pnl_r = (entry - take_profit) / risk if risk else None
                logger.debug(f"Signal {signal['id']} take-profit hit at {take_profit}")
                return "tp_hit", take_profit, pnl_r

    # Neither stop nor TP hit — use the last candle's close
    final_close = candles[-1][4]
    if direction == "long":
        outcome = "win" if final_close > entry else "loss"
        pnl_r = (final_close - entry) / risk if risk else None
    else:
        outcome = "win" if final_close < entry else "loss"
        pnl_r = (entry - final_close) / risk if risk else None

    logger.debug(f"Signal {signal['id']} {direction} entry={entry} T+{window_h}h={final_close} → {outcome}")
    return outcome, final_close, pnl_r


def run_evaluation(conn: sqlite3.Connection, exchange) -> dict:
    """
    Resolve all pending signals older than outcome_window_hours.
    Returns stats dict.
    """
    c = cfg()["walk_forward"]
    pending = get_pending_outcomes(conn, c["outcome_window_hours"])
    logger.info(f"Resolving {len(pending)} pending signal outcomes")

    resolved = 0
    for signal in pending:
        result = resolve_outcome(signal, exchange)
        if result is not None:
            outcome, price, pnl_r = result
            update_outcome(conn, signal["id"], outcome, price, pnl_r)
            resolved += 1

    stats = get_accuracy_stats(conn)
    _log_stats(stats, c)
    return {"resolved": resolved, "stats": stats}


def _log_stats(stats: dict, c: dict) -> None:
    total_resolved = sum(s["resolved"] for s in stats.values())
    total_wins = sum(s["wins"] for s in stats.values())
    total_signals = sum(s["total"] for s in stats.values())
    overall_acc = total_wins / total_resolved if total_resolved > 0 else None

    if overall_acc is not None:
        logger.info(
            f"Walk-forward stats | signals={total_signals} resolved={total_resolved} "
            f"overall_accuracy={overall_acc:.1%}"
        )
    else:
        logger.info(
            f"Walk-forward stats | signals={total_signals} resolved={total_resolved} accuracy=N/A"
        )
    for regime, s in stats.items():
        acc = s["accuracy"]
        acc_str = f"{acc:.1%}" if acc is not None else "N/A"
        logger.info(f"  {regime}: {s['resolved']}/{s['total']} resolved, accuracy={acc_str}")

    gate = c["promotion_gate_total"]
    gate_per = c["promotion_gate_per_regime"]
    gate_acc = c["promotion_accuracy"]

    all_regime_counts = {r: s["resolved"] for r, s in stats.items()}
    per_regime_ok = all(v >= gate_per for v in all_regime_counts.values()) if all_regime_counts else False
    total_ok = total_resolved >= gate
    acc_ok = overall_acc is not None and overall_acc >= gate_acc

    if total_ok and per_regime_ok and acc_ok:
        logger.success(
            f"PROMOTION GATE MET: {total_resolved} signals, {overall_acc:.1%} accuracy, "
            f"all regimes >= {gate_per} signals. Ready to promote to live alerts."
        )
    else:
        gaps = []
        if not total_ok:
            gaps.append(f"need {gate - total_resolved} more total signals")
        if not per_regime_ok:
            for r, cnt in all_regime_counts.items():
                if cnt < gate_per:
                    gaps.append(f"{r} needs {gate_per - cnt} more")
        if not acc_ok:
            gaps.append(f"accuracy {overall_acc:.1%} < {gate_acc:.0%}" if overall_acc else "no accuracy yet")
        logger.info(f"Promotion gate not yet met: {', '.join(gaps)}")
