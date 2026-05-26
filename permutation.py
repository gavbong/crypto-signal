"""
permutation.py — Monte Carlo permutation test for strategy validation.

Implements the in-sample permutation test from:
  Timothy Masters, "Permutation and Randomization Tests for Trading System Development"

For each strategy×regime combination, we ask: is the observed avg_R genuinely
from market patterns, or could a worthless strategy achieve this by luck?

Algorithm per combo:
  1. Run strategies on REAL candles → real_avg_R
  2. For N permutations: shuffle bar-level price moves (preserving statistical
     properties) → run strategies → perm_avg_R
  3. p-value = fraction of permutations where perm_avg_R >= real_avg_R
  4. Grade: A (p<1%), B (p<5%), C (p<10%), D (p≥10%)

Usage:
    python permutation.py                           # all pairs, 200 perms
    python permutation.py --n-perms 500             # more precision (slower)
    python permutation.py --pair BTC/USDT:USDT      # single pair
    python permutation.py --since 2025-08-01        # custom date range
    python permutation.py --run-id 7                # link to a permutation_tests run
"""
import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from utils.config import env, get as cfg
from utils.ccxt_wrapper import _make_exchange, fetch_ohlcv_safe
from backtest import fetch_history, load_index_csv, resolve_outcome
from db.schema import init_db, get_conn
from regime.classifier import classify_series, _to_df
from signals.selector import active_strategies
from signals.generator import run_strategy
from signals.quality import is_stop_in_range


logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


# ── PERMUTATION ALGORITHM ─────────────────────────────────────────────────────

def permute_candles(candles: list, seed: int | None = None) -> list:
    """
    Shuffle bar-level price moves while preserving statistical properties.

    Decomposes each bar into:
      - gap:      log(O_t / C_{t-1})   — period-open gap from prior close
      - intrabar: log(H/O), log(L/O), log(C/O)  — moves relative to open

    Shuffles both independently, then reconstructs. The overall start-price
    is preserved; end-price will differ (trend not preserved — intentional, as
    it removes any genuine trend/momentum edge from the permuted series).

    The permuted series has nearly identical per-bar return distribution
    (mean, std, skew, kurtosis) to the original but all multi-bar patterns
    (trends, mean-reversion, volatility clustering) are destroyed.
    """
    if seed is not None:
        random.seed(seed)

    n = len(candles)
    if n < 3:
        return [row[:] for row in candles]

    # Convert to log space; work entirely in log-prices to avoid compounding errors
    try:
        log_c = [math.log(max(candle[4], 1e-12)) for candle in candles]
        log_o = [math.log(max(candle[1], 1e-12)) for candle in candles]
        log_h = [math.log(max(candle[2], 1e-12)) for candle in candles]
        log_l = [math.log(max(candle[3], 1e-12)) for candle in candles]
    except (ValueError, TypeError):
        return [row[:] for row in candles]

    # Extract intrabar relative moves (log differences from open)
    intrabar = [
        (log_h[i] - log_o[i], log_l[i] - log_o[i], log_c[i] - log_o[i])
        for i in range(n)
    ]
    # Extract gaps (open relative to prior close); first bar has no gap
    gaps = [log_o[i] - log_c[i - 1] for i in range(1, n)]

    # Shuffle indices 1..n-1 for intrabar (bar 0 is unchanged anchor)
    shuffled_idx = list(range(1, n))
    random.shuffle(shuffled_idx)
    shuffled_intrabar = [intrabar[0]] + [intrabar[j] for j in shuffled_idx]

    shuffled_gaps = gaps[:]
    random.shuffle(shuffled_gaps)

    # Reconstruct price series
    result: list = [list(candles[0])]  # first bar preserved
    prev_log_c = log_c[0]

    for i in range(1, n):
        ts = candles[i][0]
        vol = candles[i][5] if len(candles[i]) > 5 else 0.0

        new_log_o = prev_log_c + shuffled_gaps[i - 1]
        h_rel, l_rel, c_rel = shuffled_intrabar[i]
        new_log_h = new_log_o + h_rel
        new_log_l = new_log_o + l_rel
        new_log_c = new_log_o + c_rel

        # Enforce OHLC invariants (shuffle can violate them at the edges)
        new_log_h = max(new_log_h, new_log_o, new_log_c)
        new_log_l = min(new_log_l, new_log_o, new_log_c)

        result.append([
            ts,
            math.exp(new_log_o),
            math.exp(new_log_h),
            math.exp(new_log_l),
            math.exp(new_log_c),
            vol,
        ])
        prev_log_c = new_log_c

    return result


# ── STRATEGY RUNNER (permutation-safe, no DB dependencies) ───────────────────

def _run_strategies_on_candles(
    pair: str,
    candles: list,
    c: dict,
    precomputed_regimes: list | None = None,
) -> dict:
    """
    Run all strategies on the given candles. Returns per (strategy, regime)
    list of pnl_r values for every signal that fired and resolved.

    precomputed_regimes: if supplied, regime classification is skipped (major
    speedup for permutation runs — regimes are fixed from real data, only
    OHLCV is permuted). This tests whether entry signals have edge given the
    same market regime structure, isolating the strategy's pattern recognition.

    Intentionally omits:
      - quality score gate  (depends on DB history, invalid on permuted data)
      - strategy health gate (same reason)
    """
    limit = c["candle_limit"]
    dedup_window = c["deduplication"]["window_candles"]
    timeframe = c["timeframe"]
    outcome_window_h = c["walk_forward"]["outcome_window_hours"]

    results: dict[tuple, list] = {}
    dedup_state: dict[tuple, int] = {}

    if len(candles) < limit + outcome_window_h:
        return results

    full_df = _to_df(candles)

    if precomputed_regimes is not None:
        regimes = precomputed_regimes
    else:
        regimes = classify_series(full_df)

    start_idx = limit
    end_idx = len(candles) - outcome_window_h

    for i in range(start_idx, end_idx):
        regime = regimes[i]
        if regime is None or not regime.stable:
            continue

        strategies = active_strategies(regime.label)
        if not strategies:
            continue

        df = full_df.iloc[i - limit: i]

        for strategy in strategies:
            signal = run_strategy(strategy, pair, df, regime, timeframe)
            if signal is None:
                continue

            key = (pair, signal["direction"], strategy, regime.label)
            last_fired = dedup_state.get(key, -(dedup_window + 1))
            if i - last_fired <= dedup_window:
                continue

            if not is_stop_in_range(signal["entry_price"], signal["suggested_stop_loss"], pair):
                continue

            dedup_state[key] = i

            future = candles[i: i + outcome_window_h + 1]
            result = resolve_outcome(signal, future, outcome_window_h)
            if result is None:
                continue

            _, _, pnl_r = result
            combo = (strategy, regime.label)
            results.setdefault(combo, []).append(pnl_r)

    return results


def _avg_r(pnl_list: list[float]) -> float | None:
    if not pnl_list:
        return None
    return sum(pnl_list) / len(pnl_list)


def _profit_factor(pnl_list: list[float]) -> float | None:
    if not pnl_list:
        return None
    gross_win = sum(p for p in pnl_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_list if p < 0))
    if gross_loss == 0:
        return None  # all winners — can't compute meaningful PF
    return round(gross_win / gross_loss, 4)


# ── PERMUTATION TEST ──────────────────────────────────────────────────────────

def run_permtest_pair(
    pair: str,
    candles: list,
    n_perms: int,
    c: dict,
    log_progress: bool = True,
) -> dict:
    """
    Run Monte Carlo permutation test for one pair.

    Returns dict keyed by (strategy, regime) with:
      n          — number of resolved signals on real data
      real_avg_r — avg_R on real data
      p_value    — fraction of permutations beating real_avg_r
      grade      — A/B/C/D
      perm_avg_rs — list of avg_R from each permutation (for histogram)
    """
    if log_progress:
        logger.info(f"  {pair}: running on real candles ...")

    # Precompute regimes once on real data — reused for all permuted runs.
    # This tests whether entry signals have edge given the same regime structure,
    # while eliminating classify_series from O(n_perms) iterations (~10-20x speedup).
    real_df = _to_df(candles)
    real_regimes = classify_series(real_df)

    real_stats = _run_strategies_on_candles(pair, candles, c, precomputed_regimes=real_regimes)
    if not real_stats:
        if log_progress:
            logger.info(f"  {pair}: no signals on real data — skipping permutation test")
        return {}

    # Count permutation wins per combo
    perm_better: dict[tuple, int] = {k: 0 for k in real_stats}
    perm_avg_rs: dict[tuple, list] = {k: [] for k in real_stats}

    overall_real = [p for pnl_list in real_stats.values() for p in pnl_list]
    perm_overall_better = 0
    perm_overall_avg_rs: list[float] = []

    real_overall_avg = _avg_r(overall_real)

    for i in range(n_perms):
        if log_progress and (i + 1) % 50 == 0:
            logger.info(f"  {pair}: permutation {i+1}/{n_perms} ...")

        perm = permute_candles(candles)
        perm_stats = _run_strategies_on_candles(pair, perm, c, precomputed_regimes=real_regimes)

        for combo, real_pnls in real_stats.items():
            real_ar = _avg_r(real_pnls)
            if real_ar is None:
                continue
            perm_pnls = perm_stats.get(combo, [])
            perm_ar = _avg_r(perm_pnls) if perm_pnls else -999.0
            perm_avg_rs[combo].append(perm_ar)
            if perm_ar >= real_ar:
                perm_better[combo] += 1

        # Overall system
        perm_all = [p for pnl_list in perm_stats.values() for p in pnl_list]
        perm_overall_ar = _avg_r(perm_all) if perm_all else -999.0
        perm_overall_avg_rs.append(perm_overall_ar)
        if real_overall_avg is not None and perm_overall_ar >= real_overall_avg:
            perm_overall_better += 1

    # Assemble results
    output: dict = {}

    for combo, real_pnls in real_stats.items():
        real_ar = _avg_r(real_pnls)
        if real_ar is None:
            continue
        pval = perm_better[combo] / n_perms if n_perms > 0 else 1.0
        grade = "A" if pval < 0.01 else "B" if pval < 0.05 else "C" if pval < 0.10 else "D"
        wr = sum(1 for p in real_pnls if p > 0) / len(real_pnls) if real_pnls else 0.0
        output[combo] = {
            "strategy": combo[0],
            "regime":   combo[1],
            "n":           len(real_pnls),
            "real_avg_r":  round(real_ar, 4),
            "win_rate":    round(wr, 4),
            "profit_factor": _profit_factor(real_pnls),
            "p_value":     round(pval, 4),
            "grade":       grade,
            "perm_avg_rs": [round(x, 4) for x in perm_avg_rs[combo]],
        }

    # Overall combo
    if real_overall_avg is not None and overall_real:
        overall_pval = perm_overall_better / n_perms if n_perms > 0 else 1.0
        overall_grade = ("A" if overall_pval < 0.01 else "B" if overall_pval < 0.05
                         else "C" if overall_pval < 0.10 else "D")
        overall_wr = sum(1 for p in overall_real if p > 0) / len(overall_real)
        output[("_overall_", "_all_")] = {
            "strategy": "_overall_",
            "regime":   "_all_",
            "n":           len(overall_real),
            "real_avg_r":  round(real_overall_avg, 4),
            "win_rate":    round(overall_wr, 4),
            "profit_factor": _profit_factor(overall_real),
            "p_value":     round(overall_pval, 4),
            "grade":       overall_grade,
            "perm_avg_rs": [round(x, 4) for x in perm_overall_avg_rs],
        }

    return output


# ── OUTPUT ────────────────────────────────────────────────────────────────────

_GRADE_LABEL = {
    "A": "genuine edge  (p<1%)",
    "B": "marginal edge (p<5%)",
    "C": "weak edge     (p<10%)",
    "D": "likely noise  (p≥10%)",
}

def print_permtest_results(pair: str, results: dict, n_perms: int, since_dt: datetime) -> None:
    if not results:
        print(f"\n  {pair}: no results.")
        return

    print(f"\n{'=' * 72}")
    print(f"  PERMUTATION TEST: {pair}")
    print(f"  Period: {since_dt.date()} → today  |  N permutations: {n_perms}")
    print(f"{'=' * 72}")
    print(f"  {'STRATEGY':<22} {'REGIME':<18} {'n':>4} {'avg_R':>7} {'WR':>6} {'PF':>5} {'p-val':>6}  GRADE")
    print(f"  {'-'*22} {'-'*18} {'-'*4} {'-'*7} {'-'*6} {'-'*5} {'-'*6}  {'─'*28}")

    # Sort: overall last, rest by p-value
    combos = [(k, v) for k, v in results.items() if k != ("_overall_", "_all_")]
    combos.sort(key=lambda x: x[1]["p_value"])
    overall = results.get(("_overall_", "_all_"))
    if overall:
        combos.append((("_overall_", "_all_"), overall))

    for (strat, regime), row in combos:
        pf_str = f"{row['profit_factor']:.2f}" if row["profit_factor"] is not None else "  N/A"
        sep = "─" * 72 if strat == "_overall_" else ""
        if sep:
            print(f"  {sep}")
        grade_label = _GRADE_LABEL.get(row["grade"], "")
        print(
            f"  {strat:<22} {regime:<18} {row['n']:>4} "
            f"{row['real_avg_r']:>+7.3f} {row['win_rate']:>5.1%} {pf_str:>5} "
            f"{row['p_value']:>6.3f}  {row['grade']}  {grade_label}"
        )

    print(f"{'=' * 72}\n")


# ── DB PERSISTENCE ────────────────────────────────────────────────────────────

def _save_permtest(conn, run_id: int | None, pair: str, since_date: str,
                   n_perms: int, n_candles: int, results: dict) -> int:
    """Save permutation test results to DB. Returns row id."""
    cur = conn.execute(
        """INSERT INTO permutation_tests
           (run_id, pair, since_date, n_perms, n_candles, results_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (run_id, pair, since_date, n_perms, n_candles, json.dumps({
            f"{s}|{r}": v for (s, r), v in results.items()
        })),
    )
    conn.commit()
    return cur.lastrowid


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo permutation test — validates strategy edge vs random noise."
    )
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD",
                        help="Start date for candle history (default: 270 days)")
    parser.add_argument("--n-perms", type=int, default=200, metavar="N",
                        help="Number of permutations (default: 200; use 500+ for publication-quality)")
    parser.add_argument("--pair", default=None, metavar="PAIR",
                        help="Single pair to test (e.g. BTC/USDT:USDT). Default: all configured pairs")
    parser.add_argument("--indices", action="store_true",
                        help="Also include index pairs from data/indices/ CSVs")
    parser.add_argument("--indices-only", action="store_true",
                        help="Run only index pairs")
    parser.add_argument("--indices-dir", default="data/indices", metavar="DIR")
    parser.add_argument("--run-id", type=int, default=None, metavar="N",
                        help="permutation_tests run_id (set by dashboard API)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run test but do not save results to DB")
    args = parser.parse_args()

    c = cfg()
    init_db()

    since_dt = (
        datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.since
        else datetime.now(timezone.utc) - timedelta(days=270)
    )

    # Build pair list
    work: list[tuple[str, str]] = []
    if args.pair:
        src = "csv" if "/" not in args.pair or args.pair.split("/")[1].split(":")[0] in ("USD",) else "exchange"
        work.append((args.pair, src))
    else:
        if not args.indices_only:
            crypto_pairs = (c.get("pairs") or
                            c.get("exchanges", {}).get("mexc", {}).get("pairs", []))
            for p in crypto_pairs:
                work.append((p, "exchange"))
        if args.indices or args.indices_only:
            for p in c.get("indices", {}).get("pairs", []):
                work.append((p, "csv"))

    if not work:
        logger.error("No pairs to test — check --pair or config.yaml")
        sys.exit(1)

    exchange = None
    if any(src == "exchange" for _, src in work):
        exchange = _make_exchange(env("MEXC_API_KEY"), env("MEXC_SECRET"))

    run_id = args.run_id
    since_str = since_dt.strftime("%Y-%m-%d")

    logger.info(
        f"Permutation test | pairs={[p for p,_ in work]} | "
        f"n_perms={args.n_perms} | since={since_str}"
    )

    all_results: dict[str, dict] = {}

    for idx, (pair, source) in enumerate(work):
        t0 = time.time()
        if source == "csv":
            logger.info(f"Loading CSV for {pair} ...")
            candles = load_index_csv(pair, since_dt, args.indices_dir)
        else:
            logger.info(f"Fetching history for {pair} ...")
            candles = fetch_history(exchange, pair, since_dt, c["timeframe"])

        if not candles:
            logger.warning(f"  {pair}: no candle data — skipping")
            continue

        n_candles = len(candles)
        first_dt = datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc)
        last_dt = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
        logger.info(f"  {pair}: {n_candles} candles ({first_dt.date()} to {last_dt.date()})")

        results = run_permtest_pair(pair, candles, args.n_perms, c, log_progress=True)
        elapsed = time.time() - t0
        logger.info(f"  {pair}: done in {elapsed:.0f}s — {len(results)} combos tested")

        print_permtest_results(pair, results, args.n_perms, since_dt)
        all_results[pair] = {f"{s}|{r}": v for (s, r), v in results.items()}

        if not args.dry_run:
            with get_conn() as conn:
                _save_permtest(conn, run_id, pair, since_str, args.n_perms, n_candles, results)

        # Update progress if dashboard-spawned
        if run_id is not None and not args.dry_run:
            pct = int((idx + 1) / len(work) * 100)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE permutation_runs SET progress_pct=?, progress_msg=? WHERE id=?",
                    (pct, f"{pair} done ({idx+1}/{len(work)})", run_id),
                )
                conn.commit()

    # Final summary: flag any D-grade combos
    d_combos = [
        f"{pair} {s}/{r}"
        for pair, res in all_results.items()
        for key, row in res.items()
        for s, r in [key.split("|", 1)]
        if row["grade"] == "D" and s != "_overall_"
    ]
    if d_combos:
        print(f"\n  NOISE ALERT — D-grade combos (p≥10%, consider removing):")
        for c_ in d_combos:
            print(f"    • {c_}")
        print()

    if run_id is not None and not args.dry_run:
        with get_conn() as conn:
            conn.execute(
                """UPDATE permutation_runs
                   SET finished_at=CURRENT_TIMESTAMP, status='done',
                       progress_pct=100, progress_msg='Complete'
                   WHERE id=?""",
                (run_id,),
            )
            conn.commit()

    if not args.dry_run:
        logger.info("Results saved to DB (query via GET /api/permutation/results)")


if __name__ == "__main__":
    main()
