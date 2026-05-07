"""
strategy_advisor.py — Daily strategy performance reviewer.

Queries the signals DB for resolved outcomes over a 21-day rolling window,
computes per-strategy+regime win rates, compares against regime-specific
breakeven thresholds, and assigns a status tier:
  WATCH   — n < 15  (not enough data)
  CAUTION — n 15-29 (show stats, low-confidence marker)
  HEALTHY — n >= 30, win_rate >= breakeven
  DISABLE — n >= 30, win_rate < breakeven
  N/A     — strategy is SKIP in REGIME_STRATEGY_MAP

Writes analysis/review-YYYY-MM-DD.json and .md each run.
Sends a Telegram alert if any DISABLE rows exist.
Scheduled at 06:00 UTC daily from signal_engine.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from loguru import logger

from db.schema import get_conn
from utils.config import get as cfg

PROHIBITED_PARAM_KEYS = frozenset({"ema_fast", "ema_slow"})  # regime keys — never tune these

LOOKBACK_DAYS = 21
MIN_CAUTION = 15
MIN_DISABLE = 30

_ANALYSIS_DIR = Path(__file__).parent / "analysis"


def run_strategy_review() -> list[dict]:
    from signals.selector import REGIME_STRATEGY_MAP

    skip_pairs = {
        (s, r)
        for r, m in REGIME_STRATEGY_MAP.items()
        for s, a in m.items()
        if a == "SKIP"
    }
    fire_pairs = {
        (s, r)
        for r, m in REGIME_STRATEGY_MAP.items()
        for s, a in m.items()
        if a == "FIRE"
    }

    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    rows: list[dict] = []
    with get_conn() as conn:
        data = conn.execute(
            """
            SELECT strategy, regime,
                   COUNT(*) as n,
                   SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
                   SUM(COALESCE(pnl_r, 0)) as net_r
            FROM signals
            WHERE outcome IS NOT NULL
              AND DATE(fired_at) >= ?
            GROUP BY strategy, regime
            """,
            (since,),
        ).fetchall()

    signals_cfg = cfg()["signals"]
    rr_map = {
        "choppy":          signals_cfg.get("rr_ratio_choppy",   signals_cfg["rr_ratio"]),
        "trending-up":     signals_cfg.get("rr_ratio_trending",  signals_cfg["rr_ratio"]),
        "trending-down":   signals_cfg.get("rr_ratio_trending",  signals_cfg["rr_ratio"]),
        "high-volatility": signals_cfg.get("rr_ratio_high_vol",  signals_cfg["rr_ratio"]),
    }

    for row in data:
        s = row["strategy"]
        r = row["regime"]
        n = row["n"]
        wins = row["wins"]
        net_r = row["net_r"]

        if (s, r) in skip_pairs:
            continue

        win_rate = wins / n if n > 0 else 0.0
        rr = rr_map.get(r, signals_cfg["rr_ratio"])
        breakeven = 1 / (1 + rr)

        if n < MIN_CAUTION:
            status = "WATCH"
        elif n < MIN_DISABLE:
            status = "CAUTION"
        elif win_rate >= breakeven:
            status = "HEALTHY"
        else:
            status = "DISABLE"

        # WR above breakeven but net_r/trade is negative means actual losses exceed
        # assumed RR (slippage, partial fills, early stops). Demote to CAUTION.
        if status == "HEALTHY" and n > 0 and (net_r / n) < -0.1:
            status = "CAUTION"

        rows.append({
            "strategy": s,
            "regime": r,
            "n": n,
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "breakeven": round(breakeven, 4),
            "rr_used": rr,
            "net_r": round(net_r, 3),
            "status": status,
        })

    seen = {(row["strategy"], row["regime"]) for row in rows}
    for s, r in fire_pairs - seen:
        rows.append({
            "strategy": s, "regime": r, "status": "WATCH",
            "n": 0, "wins": 0, "win_rate": None,
            "breakeven": None, "rr_used": None, "net_r": None,
        })

    for s, r in skip_pairs:
        rows.append({
            "strategy": s, "regime": r, "status": "N/A",
            "n": 0, "wins": 0, "win_rate": None,
            "breakeven": None, "rr_used": None, "net_r": None,
        })

    _write_review(rows)
    _alert_if_disable(rows)
    return rows


def _write_review(rows: list[dict]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _ANALYSIS_DIR.mkdir(exist_ok=True)

    payload = {"date": today, "rows": rows}
    (_ANALYSIS_DIR / f"review-{today}.json").write_text(json.dumps(payload, indent=2))

    _STATUS_ORDER = {"DISABLE": 0, "CAUTION": 1, "WATCH": 2, "HEALTHY": 3, "N/A": 4}
    md_lines = [
        f"# Strategy Review {today}\n",
        "| Strategy | Regime | n | Win% | Breakeven | Status | Action |",
        "|---|---|---|---|---|---|---|",
    ]
    action_map = {
        "DISABLE": "Set SKIP in selector.py",
        "CAUTION": "Watch (low confidence)",
        "WATCH":   "Insufficient data",
        "HEALTHY": "No action",
        "N/A":     "SKIP in map",
    }
    for r in sorted(rows, key=lambda x: _STATUS_ORDER.get(x["status"], 9)):
        wr = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "—"
        be = f"{r['breakeven']:.1%}" if r["breakeven"] is not None else "—"
        md_lines.append(
            f"| {r['strategy']} | {r['regime']} | {r['n']} | {wr} | {be} "
            f"| {r['status']} | {action_map.get(r['status'], '')} |"
        )
    (_ANALYSIS_DIR / f"review-{today}.md").write_text("\n".join(md_lines))

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    for f in _ANALYSIS_DIR.glob("review-*.json"):
        try:
            file_date = datetime.strptime(f.stem.replace("review-", ""), "%Y-%m-%d")
            if file_date.replace(tzinfo=timezone.utc) < cutoff:
                f.unlink(missing_ok=True)
                _ANALYSIS_DIR.joinpath(f.stem + ".md").unlink(missing_ok=True)
        except ValueError:
            pass

    logger.info(f"Strategy review written: {_ANALYSIS_DIR / f'review-{today}.json'}")


def _alert_if_disable(rows: list[dict]) -> None:
    disable_rows = [r for r in rows if r["status"] == "DISABLE"]
    if not disable_rows:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Strategy Health Alert — {today}"]
    lines.append(f"{len(disable_rows)} pair(s) flagged DISABLE:")
    for r in disable_rows[:3]:
        lines.append(
            f"  {r['strategy']}/{r['regime']}: "
            f"{r['win_rate']:.0%} WR (need {r['breakeven']:.0%}, n={r['n']})"
        )
    lines.append("Review at: http://127.0.0.1:5000")
    msg = "\n".join(lines)[:280]

    try:
        from alerts.telegram import send_telegram
        send_telegram(msg)
    except Exception:
        logger.warning("Telegram alert failed for strategy review")
