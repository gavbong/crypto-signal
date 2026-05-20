#!/usr/bin/env python3
"""
check_t6_conditions.py — Daily check for T6 unlock conditions.

T6: Reduce RISK_PCT 1% -> 0.5% (config: risk_pct_default: 0.005)

Conditions that must BOTH be true:
  1. Rolling 30d paper trade win rate > 40%
  2. 50+ closed paper trades since selector recalibration (2026-05-19)

Sends a Telegram message when both are met, then creates a sentinel file
so subsequent runs don't re-notify. Delete the sentinel to re-arm.

Sentinel: /opt/mexc-signal-engine/.t6-notified
Run via systemd timer: mexc-t6-check.timer (daily at 01:00 UTC)
"""
import sys
import sqlite3
from pathlib import Path

SENTINEL       = Path(__file__).parent.parent / ".t6-notified"
DB_PATH        = Path(__file__).parent.parent / "signals.db"
RECAL_DATE     = "2026-05-19"
WR_THRESHOLD   = 0.40
TRADE_THRESHOLD = 50


def main() -> None:
    if SENTINEL.exists():
        print("T6 already notified — sentinel present. Delete .t6-notified to re-arm.")
        sys.exit(0)

    if not DB_PATH.exists():
        print(f"signals.db not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Condition 1: rolling 30d WR (needs enough sample — require n >= 10)
    row = conn.execute("""
        SELECT COUNT(*) as n,
               SUM(CASE WHEN exit_reason='take_profit' THEN 1 ELSE 0 END) as wins
        FROM paper_positions
        WHERE closed_at >= datetime('now', '-30 days') AND closed_at IS NOT NULL
    """).fetchone()
    n_30d  = row["n"]
    wr_30d = row["wins"] / n_30d if n_30d > 0 else 0.0

    # Condition 2: closed trades since recalibration
    row2 = conn.execute("""
        SELECT COUNT(*) as n
        FROM paper_positions
        WHERE closed_at >= ? AND closed_at IS NOT NULL
    """, (RECAL_DATE,)).fetchone()
    n_since_recal = row2["n"]

    conn.close()

    cond1 = n_30d >= 10 and wr_30d > WR_THRESHOLD
    cond2 = n_since_recal >= TRADE_THRESHOLD

    print(
        f"T6 check | "
        f"30d WR={wr_30d:.1%} (n={n_30d}, need >40% with n>=10) {'✅' if cond1 else '❌'} | "
        f"Post-recal={n_since_recal}/{TRADE_THRESHOLD} {'✅' if cond2 else '❌'}"
    )

    if cond1 and cond2:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from alerts.telegram import send_telegram

        msg = "\n".join([
            "🎯 T6 Unlock: RISK_PCT reduction ready",
            "",
            "Both conditions met:",
            f"  ✅ 30d WR: {wr_30d:.1%} > 40%  (n={n_30d})",
            f"  ✅ Post-recal trades: {n_since_recal} ≥ {TRADE_THRESHOLD}",
            "",
            "Action: in config.yaml set  risk_pct_default: 0.005",
            "        then restart mexc-paper-trader",
            "(See T6 in TODOS.md for full context)",
        ])
        send_telegram(msg)
        SENTINEL.touch()
        print("Both conditions met — Telegram sent, sentinel created.")
    else:
        print("Conditions not yet met — no action taken.")


if __name__ == "__main__":
    main()
