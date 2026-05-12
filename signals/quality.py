"""
Signal quality scoring (0-100 composite).
  30% regime confidence
  40% rolling 30d win rate for this strategy×regime×direction combo
  30% stop quality (stop distance relative to asset-class optimal range)

Used by both signal_engine (live) and backtest (historical).
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta, timezone

from utils.config import get as cfg


def _asset_class_for(pair: str) -> str:
    profiles = cfg().get("asset_class_profiles", {})
    for cls, profile in profiles.items():
        if pair in profile.get("pairs", []):
            return cls
    return "crypto"


def _stop_quality_score(entry: float, stop: float, pair: str) -> float:
    """Score 0-1: 1.0 when stop distance is in the optimal range for this asset class."""
    if entry == 0:
        return 0.0
    stop_pct = abs(entry - stop) / entry
    cls = _asset_class_for(pair)
    profiles = cfg().get("asset_class_profiles", {})
    profile = profiles.get(cls, {})
    stop_min = profile.get("stop_min_pct", cfg().get("stop_quality", {}).get("min_stop_pct", 0.003))
    stop_max = profile.get("stop_max_pct", cfg().get("stop_quality", {}).get("max_stop_pct", 0.030))
    optimal_mid = (stop_min + stop_max) / 2
    if stop_pct < stop_min or stop_pct > stop_max:
        return 0.0
    # Bell curve peaking at optimal_mid
    half_range = (stop_max - stop_min) / 2
    deviation = abs(stop_pct - optimal_mid) / half_range
    return max(0.0, 1.0 - deviation)


def _rolling_wr(conn: sqlite3.Connection, strategy: str, regime: str,
                direction: str, days: int = 30) -> float:
    """Rolling win rate for this combo over the last N days from live signals only."""
    sq_cfg = cfg().get("signal_quality", {})
    min_signals = cfg().get("strategy_health", {}).get("auto_disable_min_signals", 20)
    bootstrap_wr = sq_cfg.get("bootstrap_wr", 0.35)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = conn.execute(
        """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins
           FROM signals
           WHERE strategy=? AND regime=? AND direction=? AND backtest_run_id IS NULL
             AND outcome IS NOT NULL AND fired_at >= ?""",
        (strategy, regime, direction, cutoff),
    ).fetchone()
    if row is None or row["total"] < min_signals:
        return bootstrap_wr
    return row["wins"] / row["total"] if row["total"] > 0 else bootstrap_wr


def compute_quality_score(
    conn: sqlite3.Connection,
    strategy: str,
    regime_label: str,
    regime_confidence: float,
    direction: str,
    pair: str,
    entry: float,
    stop: float,
) -> float:
    """Return quality score 0-100. Used by signal_engine and backtest."""
    weights = cfg().get("signal_quality", {}).get("quality_weights", {})
    w_regime = weights.get("regime_confidence", 0.30)
    w_wr = weights.get("rolling_30d_wr", 0.40)
    w_stop = weights.get("stop_quality", 0.30)

    wr = _rolling_wr(conn, strategy, regime_label, direction)
    stop_score = _stop_quality_score(entry, stop, pair)

    raw = w_regime * regime_confidence + w_wr * wr + w_stop * stop_score
    return round(raw * 100, 1)


def is_stop_in_range(entry: float, stop: float, pair: str) -> bool:
    """Hard gate: stop distance must be within asset-class min/max range."""
    if entry == 0:
        return False
    stop_pct = abs(entry - stop) / entry
    cls = _asset_class_for(pair)
    profiles = cfg().get("asset_class_profiles", {})
    profile = profiles.get(cls, {})
    stop_min = profile.get("stop_min_pct", cfg().get("stop_quality", {}).get("min_stop_pct", 0.003))
    stop_max = profile.get("stop_max_pct", cfg().get("stop_quality", {}).get("max_stop_pct", 0.030))
    return stop_min <= stop_pct <= stop_max


def update_strategy_health(conn: sqlite3.Connection, strategy: str,
                           regime: str, direction: str, pair: str) -> None:
    """Recalculate and upsert strategy_health row after an outcome is resolved."""
    h_cfg = cfg().get("strategy_health", {})
    days = h_cfg.get("auto_disable_window_days", 30)
    min_signals = h_cfg.get("auto_disable_min_signals", 20)
    watch_t = h_cfg.get("watch_threshold", 0.38)
    caution_t = h_cfg.get("caution_threshold", 0.33)
    disable_t = h_cfg.get("disable_threshold", 0.30)

    asset_class = _asset_class_for(pair)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()

    row = conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN outcome IN ('win','tp_hit') THEN 1 ELSE 0 END) as wins,
                  SUM(COALESCE(pnl_r, 0)) as net_r,
                  MIN(DATE(fired_at)) as window_start,
                  MAX(DATE(fired_at)) as window_end
           FROM signals
           WHERE strategy=? AND regime=? AND direction=? AND backtest_run_id IS NULL
             AND outcome IS NOT NULL AND fired_at >= ?""",
        (strategy, regime, direction, cutoff),
    ).fetchone()
    if row is None or row["total"] < min_signals:
        return

    total = row["total"]
    wins = row["wins"] or 0
    net_r = row["net_r"] or 0.0
    wr = wins / total

    existing = conn.execute(
        "SELECT status, disabled_at FROM strategy_health WHERE strategy=? AND regime=? AND direction=? AND asset_class=?",
        (strategy, regime, direction, asset_class),
    ).fetchone()

    if wr < disable_t:
        status = "DISABLED"
        disabled_at = now if (existing is None or existing["status"] != "DISABLED") else existing["disabled_at"]
    elif wr < caution_t:
        status = "CAUTION"
        disabled_at = None
    elif wr < watch_t:
        status = "WATCH"
        disabled_at = None
    else:
        status = "HEALTHY"
        disabled_at = None

    conn.execute(
        """INSERT INTO strategy_health
               (strategy, regime, direction, asset_class, window_start, window_end,
                signal_count, win_count, win_rate, net_r, status, disabled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(strategy, regime, direction, asset_class) DO UPDATE SET
               window_start=excluded.window_start, window_end=excluded.window_end,
               signal_count=excluded.signal_count, win_count=excluded.win_count,
               win_rate=excluded.win_rate, net_r=excluded.net_r,
               status=excluded.status, disabled_at=excluded.disabled_at""",
        (strategy, regime, direction, asset_class,
         row["window_start"], row["window_end"],
         total, wins, round(wr, 4), round(net_r, 4), status, disabled_at),
    )
    conn.commit()
