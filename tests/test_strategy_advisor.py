"""
Tests for strategy_advisor.py
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from db.schema import get_conn, log_signal, update_outcome


def _signal(strategy="ema_9_21_crossover", regime="trending-up",
            shadow=0, fired_at=None):
    if fired_at is None:
        fired_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return {
        "pair": "BTC/USDT:USDT",
        "direction": "long",
        "strategy": strategy,
        "regime": regime,
        "regime_confidence": 0.8,
        "regime_age_candles": 5,
        "entry_price": 50000.0,
        "suggested_stop_loss": 49000.0,
        "suggested_take_profit": 52000.0,
        "timeframe": "15m",
        "fired_at": (fired_at if isinstance(fired_at, str) else fired_at.isoformat()),
        "shadow_mode": shadow,
        "llm_commentary": None,
        "commentary_status": "pending",
    }


def _seed(conn, strategy, regime, wins, losses, pnl_r_win=2.5, pnl_r_loss=-1.0, days_ago=1):
    fired_at = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    for _ in range(wins):
        sid = log_signal(conn, _signal(strategy=strategy, regime=regime, fired_at=fired_at))
        update_outcome(conn, sid, "tp_hit", 52000.0, pnl_r=pnl_r_win)
        fired_at += timedelta(hours=1)
    for _ in range(losses):
        sid = log_signal(conn, _signal(strategy=strategy, regime=regime, fired_at=fired_at))
        update_outcome(conn, sid, "stopped_out", 49000.0, pnl_r=pnl_r_loss)
        fired_at += timedelta(hours=1)


@pytest.fixture
def client(tmp_db):
    import db.schema as schema_module
    original = schema_module.db_path
    schema_module.db_path = lambda: tmp_db
    from dashboard import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    schema_module.db_path = original


@pytest.fixture
def patched_db(tmp_db, tmp_path, monkeypatch):
    """Patch both utils.config and db.schema to use the test DB, and chdir to tmp_path
    so strategy_advisor writes analysis/ files into the temp dir."""
    import db.schema as schema_module
    monkeypatch.setattr(schema_module, "db_path", lambda: tmp_db)
    monkeypatch.chdir(tmp_path)
    return tmp_db


def _review(patched_db):
    from strategy_advisor import run_strategy_review
    return run_strategy_review()


class TestStatusThresholds:
    """Status tiers based on n and win rate against breakeven."""

    def test_watch_when_fewer_than_15(self, patched_db):
        with get_conn(patched_db) as conn:
            _seed(conn, "ema_9_21_crossover", "trending-up", wins=5, losses=5)
        rows = _review(patched_db)
        row = next(r for r in rows if r["strategy"] == "ema_9_21_crossover"
                   and r["regime"] == "trending-up")
        assert row["status"] == "WATCH"
        assert row["n"] == 10

    def test_caution_at_15_to_29(self, patched_db):
        with get_conn(patched_db) as conn:
            _seed(conn, "ema_9_21_crossover", "trending-up", wins=12, losses=8)
        rows = _review(patched_db)
        row = next(r for r in rows if r["strategy"] == "ema_9_21_crossover"
                   and r["regime"] == "trending-up")
        assert row["status"] == "CAUTION"
        assert row["n"] == 20

    def test_healthy_at_30_above_breakeven(self, patched_db):
        # trending rr=2.5, breakeven=1/3.5≈0.286; 12/30≈40% > breakeven
        with get_conn(patched_db) as conn:
            _seed(conn, "ema_9_21_crossover", "trending-up", wins=12, losses=18)
        rows = _review(patched_db)
        row = next(r for r in rows if r["strategy"] == "ema_9_21_crossover"
                   and r["regime"] == "trending-up")
        assert row["status"] == "HEALTHY"
        assert row["n"] == 30
        assert abs(row["breakeven"] - round(1 / 3.5, 4)) < 0.001

    def test_disable_at_30_below_breakeven(self, patched_db):
        # trending rr=2.5, breakeven≈28.6%; 5/30≈16.7% < breakeven
        with get_conn(patched_db) as conn:
            _seed(conn, "ema_9_21_crossover", "trending-up", wins=5, losses=25)
        rows = _review(patched_db)
        row = next(r for r in rows if r["strategy"] == "ema_9_21_crossover"
                   and r["regime"] == "trending-up")
        assert row["status"] == "DISABLE"

    def test_choppy_breakeven_is_40_pct(self, patched_db):
        # choppy rr=1.5, breakeven=1/2.5=0.40 — use rsi_divergence (FIRE in choppy)
        with get_conn(patched_db) as conn:
            _seed(conn, "rsi_divergence", "choppy", wins=0, losses=30)
        rows = _review(patched_db)
        row = next(r for r in rows if r["strategy"] == "rsi_divergence"
                   and r["regime"] == "choppy")
        assert abs(row["breakeven"] - 0.4) < 0.001
        assert row["status"] == "DISABLE"


class TestFirePairsWithNoData:
    """FIRE pairs that haven't fired yet should appear as WATCH with n=0."""

    def test_active_pair_no_db_data_is_watch(self, patched_db):
        rows = _review(patched_db)
        # ema_9_21_crossover/trending-up is FIRE in selector.py
        row = next((r for r in rows if r["strategy"] == "ema_9_21_crossover"
                    and r["regime"] == "trending-up"), None)
        assert row is not None, "FIRE pair missing from rows"
        assert row["status"] == "WATCH"
        assert row["n"] == 0
        assert row["win_rate"] is None

    def test_all_fire_pairs_present(self, patched_db):
        from signals.selector import REGIME_STRATEGY_MAP
        rows = _review(patched_db)
        fire_pairs = {
            (s, r)
            for r, m in REGIME_STRATEGY_MAP.items()
            for s, a in m.items()
            if a == "FIRE"
        }
        returned = {(row["strategy"], row["regime"]) for row in rows if row["status"] != "N/A"}
        assert fire_pairs == returned


class TestSkipPairsGetNA:
    """SKIP pairs must appear as N/A in every review."""

    def test_skip_pairs_are_na(self, patched_db):
        from signals.selector import REGIME_STRATEGY_MAP
        rows = _review(patched_db)
        skip_pairs = {
            (s, r)
            for r, m in REGIME_STRATEGY_MAP.items()
            for s, a in m.items()
            if a == "SKIP"
        }
        na_pairs = {(row["strategy"], row["regime"]) for row in rows if row["status"] == "N/A"}
        assert skip_pairs == na_pairs


class TestEmptyStateAPI:
    """GET /api/analysis/latest must always return HTTP 200 with date + rows fields."""

    def test_returns_200_with_valid_shape(self, client):
        # The contract: always HTTP 200, never 404/500, always has date + rows keys.
        # Whether files exist depends on runtime — we test shape not contents.
        r = client.get("/api/analysis/latest")
        assert r.status_code == 200
        data = r.get_json()
        assert "date" in data
        assert "rows" in data
        assert isinstance(data["rows"], list)
