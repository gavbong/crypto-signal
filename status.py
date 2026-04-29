"""
status.py - Quick snapshot of signal engine health.
Usage: python status.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

from db.schema import get_conn, init_db
from utils.config import get as cfg


def _ago(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m = rem // 60
        return f"{h}h {m}m ago" if h else f"{m}m ago"
    except Exception:
        return iso


def main() -> None:
    init_db()
    c = cfg()
    gate_total = c["walk_forward"]["promotion_gate_total"]
    gate_per   = c["walk_forward"]["promotion_gate_per_regime"]
    gate_acc   = c["walk_forward"]["promotion_accuracy"]

    with get_conn() as conn:
        # -- Signal counts -----------------------------------------------------
        total_signals = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE shadow_mode=0"
        ).fetchone()[0]

        # -- Last signal -------------------------------------------------------
        last = conn.execute(
            "SELECT pair, direction, strategy, regime, entry_price, fired_at "
            "FROM signals WHERE shadow_mode=0 ORDER BY fired_at DESC LIMIT 1"
        ).fetchone()

        # -- Per-regime breakdown ----------------------------------------------
        rows = conn.execute(
            """SELECT regime,
                      COUNT(*) as total,
                      SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END) as wins,
                      SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
                      SUM(CASE WHEN outcome='stopped_out' THEN 1 ELSE 0 END) as stopped,
                      SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved
               FROM signals WHERE shadow_mode=0
               GROUP BY regime ORDER BY total DESC"""
        ).fetchall()

        # -- Pending outcomes --------------------------------------------------
        pending = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE shadow_mode=0 AND outcome IS NULL"
        ).fetchone()[0]

        # -- Commentary failures -----------------------------------------------
        commentary_pending = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE shadow_mode=0 AND commentary_status='pending'"
        ).fetchone()[0]

    # -- Render ----------------------------------------------------------------
    SEP = "-" * 58
    print(f"\n{SEP}")
    print(f"  MEXC Signal Engine - Status")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(SEP)

    print(f"\n  Total signals logged : {total_signals}")
    print(f"  Outcomes pending     : {pending}")
    print(f"  Commentary pending   : {commentary_pending}")

    if last:
        print(f"\n  Last signal  : {last['pair']} {last['direction'].upper()}"
              f" via {last['strategy']}")
        print(f"               {last['regime']}  entry={last['entry_price']}"
              f"  ({_ago(last['fired_at'])})")

    print(f"\n  {'REGIME':<20} {'TOTAL':>6} {'RESOLVED':>9} {'WIN':>5} {'LOSS':>6} {'STOP':>6} {'ACC':>7}")
    print(f"  {'-'*20} {'-'*6} {'-'*9} {'-'*5} {'-'*6} {'-'*6} {'-'*7}")

    total_resolved = total_wins = 0
    regime_ok = True
    for r in rows:
        acc = r["wins"] / r["resolved"] if r["resolved"] else None
        acc_str = f"{acc:.1%}" if acc is not None else "-"
        gate_str = " OK" if r["total"] >= gate_per else f" ({gate_per - r['total']} needed)"
        print(f"  {r['regime']:<20} {r['total']:>6} {r['resolved']:>9} "
              f"{r['wins']:>5} {r['losses']:>6} {r['stopped']:>6} {acc_str:>7}{gate_str}")
        total_resolved += r["resolved"]
        total_wins     += r["wins"]
        if r["total"] < gate_per:
            regime_ok = False

    # -- Overall accuracy ------------------------------------------------------
    overall_acc = total_wins / total_resolved if total_resolved else None
    overall_str = f"{overall_acc:.1%}" if overall_acc else "-"
    print(f"\n  Overall accuracy : {overall_str}  (target >={gate_acc:.0%})")

    # -- Promotion gate --------------------------------------------------------
    print(f"\n  Promotion gate:")
    checks = [
        (total_signals >= gate_total,
         f"    Signals  {total_signals}/{gate_total}"),
        (regime_ok,
         f"    Per-regime >={gate_per} each"),
        (overall_acc is not None and overall_acc >= gate_acc,
         f"    Accuracy  {overall_str} >={gate_acc:.0%}"),
    ]
    all_met = True
    for met, label in checks:
        mark = "OK" if met else "X"
        print(f"    [{mark}] {label.strip()}")
        if not met:
            all_met = False

    if all_met:
        print(f"\n  *** PROMOTION GATE MET - ready for live alerts ***")
    else:
        if total_signals == 0:
            print(f"\n  Engine running, waiting for first signal.")
        else:
            remaining = gate_total - total_signals
            print(f"\n  ~{remaining} more signals needed to reach total gate.")

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    main()
