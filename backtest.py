"""
backtest.py — Historical signal replay for walk-forward validation.

Fetches OHLCV history candle-by-candle, runs the same classify -> select ->
generate pipeline as the live engine, resolves outcomes immediately from
future candles, and writes results to signals.db.

P&L is tracked in R-multiples: each trade risks 1R (distance to stop).
  tp_hit     = +rr_ratio R  (e.g. +2.0R)
  stopped_out = -1.0R
  win/loss    = actual move / risk (fractional R)

Usage:
    python backtest.py                        # 180 days back, all configured pairs
    python backtest.py --since 2025-06-01     # custom start date
    python backtest.py --dry-run              # preview without DB writes
    python backtest.py --clear                # wipe existing backtest data first
    python backtest.py --clear --since 2025-06-01
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from loguru import logger

from utils.config import env, get as cfg
from utils.ccxt_wrapper import _make_exchange, fetch_ohlcv_safe
from db.schema import init_db, get_conn, log_signal, update_outcome
from regime.classifier import classify, _to_df
from signals.selector import active_strategies
from signals.generator import run_strategy


logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


def fetch_history(exchange, pair: str, since_dt: datetime, timeframe: str) -> list:
    """Page through OHLCV history in 1000-candle chunks until present."""
    since_ms = int(since_dt.timestamp() * 1000)
    all_candles: list = []
    page_limit = 1000

    while True:
        batch = fetch_ohlcv_safe(exchange, pair, timeframe, limit=page_limit, since=since_ms)
        if not batch:
            break
        all_candles.extend(batch)
        if len(batch) < page_limit:
            break
        since_ms = batch[-1][0] + 1
        time.sleep(0.25)

    seen: set = set()
    unique: list = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    return sorted(unique, key=lambda x: x[0])


def resolve_outcome(signal: dict, future_candles: list, window_h: int) -> tuple[str, float, float] | None:
    """
    Check the next window_h candles for stop or TP hit, else use final close.
    Returns (outcome, price, pnl_r) or None if no future data.

    pnl_r is P&L in R-multiples (1R = distance from entry to stop).
    """
    if not future_candles:
        return None

    entry = signal["entry_price"]
    stop = signal["suggested_stop_loss"]
    take_profit = signal.get("suggested_take_profit")
    direction = signal["direction"]
    risk = abs(entry - stop) if stop is not None else None

    for candle in future_candles[:window_h]:
        _, _o, h, l, _c, _v = candle
        if direction == "long":
            if stop is not None and l <= stop:
                pnl_r = -1.0
                return "stopped_out", stop, pnl_r
            if take_profit is not None and h >= take_profit:
                pnl_r = (take_profit - entry) / risk if risk else 0.0
                return "tp_hit", take_profit, pnl_r
        else:
            if stop is not None and h >= stop:
                pnl_r = -1.0
                return "stopped_out", stop, pnl_r
            if take_profit is not None and l <= take_profit:
                pnl_r = (entry - take_profit) / risk if risk else 0.0
                return "tp_hit", take_profit, pnl_r

    final_close = future_candles[min(window_h - 1, len(future_candles) - 1)][4]
    if direction == "long":
        outcome = "win" if final_close > entry else "loss"
        pnl_r = (final_close - entry) / risk if risk else 0.0
    else:
        outcome = "win" if final_close < entry else "loss"
        pnl_r = (entry - final_close) / risk if risk else 0.0
    return outcome, final_close, pnl_r


def _regime_stats() -> dict:
    return {"fired": 0, "win": 0, "tp_hit": 0, "loss": 0, "stopped_out": 0, "pnl_r": 0.0}


def run_pair(pair: str, candles: list, conn, c: dict, dry_run: bool) -> dict:
    """Replay one pair's full history. Returns per-pair stats."""
    limit = c["candle_limit"]
    dedup_window = c["deduplication"]["window_candles"]
    timeframe = c["timeframe"]
    outcome_window_h = c["walk_forward"]["outcome_window_hours"]

    dedup_state: dict[tuple, int] = {}

    stats = {
        "fired": 0, "win": 0, "tp_hit": 0, "loss": 0, "stopped_out": 0,
        "skipped_dedup": 0, "skipped_unstable": 0, "unresolved": 0,
        "pnl_r": 0.0,
        "by_regime": {},
    }

    start_idx = limit
    end_idx = len(candles) - outcome_window_h

    if end_idx <= start_idx:
        logger.warning(f"{pair}: only {len(candles)} candles, need {limit + outcome_window_h}+")
        return stats

    for i in range(start_idx, end_idx):
        window = candles[i - limit: i]

        try:
            regime = classify(window)
        except ValueError:
            continue

        if not regime.stable:
            stats["skipped_unstable"] += 1
            continue

        strategies = active_strategies(regime.label)
        if not strategies:
            continue

        df = _to_df(window)

        for strategy in strategies:
            signal = run_strategy(strategy, pair, df, regime, timeframe)
            if signal is None:
                continue

            key = (pair, signal["direction"], strategy, regime.label)
            last_fired = dedup_state.get(key, -(dedup_window + 1))
            if i - last_fired <= dedup_window:
                stats["skipped_dedup"] += 1
                continue

            candle_ts = datetime.fromtimestamp(candles[i][0] / 1000, tz=timezone.utc)
            signal["fired_at"] = candle_ts.isoformat()
            signal["shadow_mode"] = True
            signal["llm_commentary"] = None
            signal["commentary_status"] = "skipped"

            dedup_state[key] = i
            stats["fired"] += 1

            r = regime.label
            rb = stats["by_regime"].setdefault(r, _regime_stats())
            rb["fired"] += 1

            future = candles[i: i + outcome_window_h + 1]
            result = resolve_outcome(signal, future, outcome_window_h)

            if result:
                outcome, price, pnl_r = result
                stats[outcome] = stats.get(outcome, 0) + 1
                stats["pnl_r"] += pnl_r
                rb[outcome] = rb.get(outcome, 0) + 1
                rb["pnl_r"] += pnl_r

                if not dry_run:
                    signal_id = log_signal(conn, signal)
                    update_outcome(conn, signal_id, outcome, price)
            else:
                stats["unresolved"] += 1
                if not dry_run:
                    log_signal(conn, signal)

    return stats


def print_summary(totals: dict, c: dict, since_dt: datetime, dry_run: bool, regime_breakdown: dict) -> None:
    mode = "DRY RUN" if dry_run else "WRITTEN TO DB"
    gate_total = c["walk_forward"]["promotion_gate_total"]
    gate_per = c["walk_forward"]["promotion_gate_per_regime"]
    gate_acc = c["walk_forward"]["promotion_accuracy"]
    rr = c["signals"]["rr_ratio"]

    wins = totals["win"] + totals["tp_hit"]
    total_resolved = wins + totals["loss"] + totals["stopped_out"]
    overall_acc = wins / total_resolved if total_resolved > 0 else None
    net_r = totals["pnl_r"]
    avg_r = net_r / total_resolved if total_resolved > 0 else None

    print("\n" + "=" * 66)
    print(f"  BACKTEST COMPLETE [{mode}]")
    print(f"  Period  : {since_dt.date()} to today   R:R = 1:{rr:.1f}")
    print("=" * 66)
    print(f"  Signals fired     : {totals['fired']}")
    print(f"  Resolved          : {total_resolved}")
    print(f"  TP Hit / Win / Loss / Stop : {totals['tp_hit']} / {totals['win']} / {totals['loss']} / {totals['stopped_out']}")
    if overall_acc is not None:
        print(f"  Accuracy          : {overall_acc:.1%}  (target >={gate_acc:.0%})")
    else:
        print("  Accuracy          : N/A")
    print(f"  Net P&L           : {net_r:+.2f}R  ({'PROFIT' if net_r > 0 else 'LOSS'})")
    if avg_r is not None:
        print(f"  Avg P&L per trade : {avg_r:+.3f}R")

    if regime_breakdown:
        print()
        print(f"  {'REGIME':<22} {'FIRED':>6} {'TP':>4} {'WIN':>5} {'LOSS':>5} {'STOP':>5} {'ACC':>7} {'NET R':>7}")
        print(f"  {'-'*22} {'-'*6} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*7}")
        for regime, s in sorted(regime_breakdown.items()):
            r_wins = s["win"] + s["tp_hit"]
            res = r_wins + s["loss"] + s["stopped_out"]
            acc = r_wins / res if res > 0 else None
            acc_str = f"{acc:.1%}" if acc is not None else "   N/A"
            per_ok = "[ok]" if res >= gate_per else "[x] "
            net_r_str = f"{s['pnl_r']:+.2f}"
            print(f"  {regime:<22} {s['fired']:>6} {s['tp_hit']:>4} {s['win']:>5} {s['loss']:>5} {s['stopped_out']:>5} {acc_str:>7} {net_r_str:>7}  {per_ok}")

    print()
    acc_ok = overall_acc is not None and overall_acc >= gate_acc
    total_ok = total_resolved >= gate_total
    per_regime_ok = all(
        (s["win"] + s["tp_hit"] + s["loss"] + s["stopped_out"]) >= gate_per
        for s in regime_breakdown.values()
    ) if regime_breakdown else False

    gate_str = "PASSED" if (total_ok and per_regime_ok and acc_ok) else "NOT MET"
    print(f"  Promotion gate ({gate_total} signals @ >={gate_acc:.0%}, >={gate_per}/regime): {gate_str}")
    if not (total_ok and per_regime_ok and acc_ok):
        if not total_ok:
            print(f"    need {gate_total - total_resolved} more resolved signals")
        if not per_regime_ok:
            for regime, s in regime_breakdown.items():
                res = s["win"] + s["tp_hit"] + s["loss"] + s["stopped_out"]
                if res < gate_per:
                    print(f"    {regime}: need {gate_per - res} more")
        if not acc_ok:
            print(f"    accuracy {'N/A' if overall_acc is None else f'{overall_acc:.1%}'} < {gate_acc:.0%}")
    print("=" * 66)
    if not dry_run:
        print("\n  Run `python status.py` for the live per-regime breakdown.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the signal engine on historical data.")
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                        help="Backtest start date (default: 180 days ago)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute signals without writing to DB")
    parser.add_argument("--clear", action="store_true",
                        help="Delete all existing shadow signals before running")
    args = parser.parse_args()

    c = cfg()
    init_db()

    since_dt = (
        datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.since
        else datetime.now(timezone.utc) - timedelta(days=180)
    )

    exchange = _make_exchange(env("MEXC_API_KEY"), env("MEXC_SECRET"))

    if args.clear and not args.dry_run:
        with get_conn() as conn:
            deleted = conn.execute("DELETE FROM signals WHERE shadow_mode=1").rowcount
            conn.commit()
            logger.info(f"Cleared {deleted} existing shadow signals from DB")

    mode = "DRY RUN" if args.dry_run else "WRITE"
    logger.info(f"Backtest [{mode}] | since={since_dt.date()} | pairs={c['pairs']}")

    totals = {"fired": 0, "win": 0, "tp_hit": 0, "loss": 0, "stopped_out": 0, "pnl_r": 0.0}
    regime_breakdown: dict[str, dict] = {}

    for pair in c["pairs"]:
        logger.info(f"Fetching history for {pair} ...")
        candles = fetch_history(exchange, pair, since_dt, c["timeframe"])
        if not candles:
            logger.warning(f"  No data for {pair}, skipping")
            continue

        first_dt = datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc)
        last_dt = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
        logger.info(f"  {pair}: {len(candles)} candles ({first_dt.date()} to {last_dt.date()})")

        with get_conn() as conn:
            stats = run_pair(pair, candles, conn, c, args.dry_run)

        wins = stats["win"] + stats["tp_hit"]
        resolved = wins + stats["loss"] + stats["stopped_out"]
        acc = wins / resolved if resolved > 0 else None
        logger.info(
            f"  {pair}: fired={stats['fired']} tp={stats['tp_hit']} win={stats['win']} "
            f"loss={stats['loss']} stop={stats['stopped_out']} "
            f"acc={f'{acc:.1%}' if acc else 'N/A'} "
            f"net={stats['pnl_r']:+.2f}R "
            f"(dedup={stats['skipped_dedup']} unstable={stats['skipped_unstable']})"
        )

        for k in ("fired", "win", "tp_hit", "loss", "stopped_out"):
            totals[k] += stats.get(k, 0)
        totals["pnl_r"] += stats["pnl_r"]

        for regime, rb in stats["by_regime"].items():
            dest = regime_breakdown.setdefault(regime, _regime_stats())
            for k in ("fired", "win", "tp_hit", "loss", "stopped_out"):
                dest[k] += rb[k]
            dest["pnl_r"] += rb["pnl_r"]

    print_summary(totals, c, since_dt, args.dry_run, regime_breakdown)


if __name__ == "__main__":
    main()
