import json
from datetime import datetime, timedelta, timezone

import pytest

from db.schema import get_conn, log_signal, update_outcome


def _signal(direction="long", shadow=0, regime="trending-up", fired_at=None):
    if fired_at is None:
        fired_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return {
        "pair": "BTC/USDT:USDT",
        "direction": direction,
        "strategy": "ema_crossover",
        "regime": regime,
        "regime_confidence": 0.8,
        "regime_age_candles": 5,
        "entry_price": 50000.0,
        "suggested_stop_loss": 49000.0,
        "suggested_take_profit": 52000.0,
        "timeframe": "1h",
        "fired_at": (fired_at if isinstance(fired_at, str) else fired_at.isoformat()),
        "shadow_mode": shadow,
        "llm_commentary": None,
        "commentary_status": "pending",
    }


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
def client_auth(tmp_db, monkeypatch):
    """Client fixture with token auth required (host=0.0.0.0 + DASHBOARD_TOKEN set)."""
    import db.schema as schema_module
    monkeypatch.setattr(schema_module, "db_path", lambda: tmp_db)
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-secret-xyz")

    import dashboard as dash_mod
    from utils.config import get as original_cfg
    monkeypatch.setattr(dash_mod, "cfg", lambda: {
        **original_cfg(),
        "dashboard": {"host": "0.0.0.0", "port": 5000, "debug": False},
    })

    app = dash_mod.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── /api/signals ─────────────────────────────────────────────────────────────

class TestSignalsAPI:
    def test_live_filter_returns_only_live(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))
            log_signal(conn, _signal(shadow=0))
            log_signal(conn, _signal(shadow=1))

        r = client.get("/api/signals?filter=live")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["total"] == 2
        assert len(data["signals"]) == 2
        assert all(not s["shadow_mode"] for s in data["signals"])

    def test_shadow_filter_returns_only_shadow(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))
            log_signal(conn, _signal(shadow=1))
            log_signal(conn, _signal(shadow=1))

        r = client.get("/api/signals?filter=shadow")
        data = json.loads(r.data)
        assert data["total"] == 2
        assert all(s["shadow_mode"] for s in data["signals"])

    def test_all_filter_returns_everything(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))
            log_signal(conn, _signal(shadow=1))

        r = client.get("/api/signals?filter=all")
        data = json.loads(r.data)
        assert data["total"] == 2

    def test_default_filter_is_live(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))
            log_signal(conn, _signal(shadow=1))

        r = client.get("/api/signals")
        data = json.loads(r.data)
        assert data["total"] == 1
        assert not data["signals"][0]["shadow_mode"]

    def test_timestamps_have_z_suffix(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))

        r = client.get("/api/signals?filter=live")
        data = json.loads(r.data)
        assert data["signals"][0]["fired_at"].endswith("Z")


# ── /api/stats ───────────────────────────────────────────────────────────────

class TestStatsAPI:
    def test_accuracy_from_resolved_signals(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            for _ in range(3):
                sid = log_signal(conn, _signal(shadow=0))
                update_outcome(conn, sid, "win", 52000.0, pnl_r=2.0)
            for _ in range(2):
                sid = log_signal(conn, _signal(shadow=0))
                update_outcome(conn, sid, "loss", 49000.0, pnl_r=-1.0)

        r = client.get("/api/stats?filter=live")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert abs(data["accuracy"] - 0.6) < 0.01
        assert data["wins"] == 3
        assert data["losses"] == 2
        assert data["resolved"] == 5

    def test_empty_db_returns_zeros(self, client, tmp_db):
        r = client.get("/api/stats?filter=live")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["accuracy"] == 0.0
        assert data["total_fired"] == 0
        assert data["net_r"] == 0.0

    def test_net_r_sums_pnl(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            sid = log_signal(conn, _signal(shadow=0))
            update_outcome(conn, sid, "win", 52000.0, pnl_r=2.0)
            sid = log_signal(conn, _signal(shadow=0))
            update_outcome(conn, sid, "loss", 49000.0, pnl_r=-1.0)

        r = client.get("/api/stats?filter=live")
        data = json.loads(r.data)
        assert abs(data["net_r"] - 1.0) < 0.001

    def test_since_filter_excludes_old_signals(self, client, tmp_db):
        old = datetime.now(timezone.utc) - timedelta(days=10)
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0, fired_at=old))
            log_signal(conn, _signal(shadow=0, fired_at=recent))

        since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        r = client.get(f"/api/stats?filter=live&since={since}")
        data = json.loads(r.data)
        assert data["total_fired"] == 1

    def test_by_regime_breakdown(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            for _ in range(2):
                sid = log_signal(conn, _signal(shadow=0, regime="trending-up"))
                update_outcome(conn, sid, "win", 52000.0, pnl_r=2.0)
            sid = log_signal(conn, _signal(shadow=0, regime="choppy"))
            update_outcome(conn, sid, "loss", 49000.0, pnl_r=-1.0)

        r = client.get("/api/stats?filter=live")
        data = json.loads(r.data)
        assert "trending-up" in data["by_regime"]
        assert "choppy" in data["by_regime"]
        assert data["by_regime"]["trending-up"]["wins"] == 2
        assert data["by_regime"]["choppy"]["losses"] == 1


# ── /api/active ──────────────────────────────────────────────────────────────

class TestActiveAPI:
    def test_returns_open_live_signals(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0))           # open live
            sid = log_signal(conn, _signal(shadow=0))     # resolved live
            update_outcome(conn, sid, "win", 52000.0)
            log_signal(conn, _signal(shadow=1))            # open shadow (excluded)

        r = client.get("/api/active")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert len(data["signals"]) == 1

    def test_empty_returns_empty_list(self, client, tmp_db):
        r = client.get("/api/active")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["signals"] == []

    def test_capped_at_five(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            for _ in range(7):
                log_signal(conn, _signal(shadow=0))

        r = client.get("/api/active")
        data = json.loads(r.data)
        assert len(data["signals"]) == 5


# ── /api/health ──────────────────────────────────────────────────────────────

class TestHealthAPI:
    def _insert_regime_log(self, tmp_db, logged_at: datetime):
        with get_conn(tmp_db) as conn:
            conn.execute(
                """INSERT INTO regime_log
                   (pair, regime, confidence, age_candles, stable, logged_at)
                   VALUES (?,?,?,?,?,?)""",
                ("BTC/USDT:USDT", "trending-up", 0.9, 5, 1, logged_at.isoformat()),
            )
            conn.commit()

    def test_recent_log_engine_running(self, client, tmp_db):
        self._insert_regime_log(tmp_db, datetime.now(timezone.utc) - timedelta(minutes=2))
        r = client.get("/api/health")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["engine_running"] is True

    def test_old_log_engine_stale(self, client, tmp_db):
        self._insert_regime_log(tmp_db, datetime.now(timezone.utc) - timedelta(minutes=15))
        r = client.get("/api/health")
        data = json.loads(r.data)
        assert data["engine_running"] is False

    def test_empty_regime_log(self, client, tmp_db):
        r = client.get("/api/health")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["engine_running"] is False
        assert data["last_write"] is None


# ── /api/regime ──────────────────────────────────────────────────────────────

class TestRegimeAPI:
    def test_segments_grouped_by_regime(self, client, tmp_db):
        base = datetime.now(timezone.utc) - timedelta(days=5)
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0, regime="trending-up", fired_at=base))
            log_signal(conn, _signal(shadow=0, regime="trending-up",
                                     fired_at=base + timedelta(hours=1)))
            log_signal(conn, _signal(shadow=0, regime="choppy",
                                     fired_at=base + timedelta(hours=2)))

        r = client.get("/api/regime?filter=live")
        data = json.loads(r.data)
        assert r.status_code == 200
        regimes = {s["regime"] for s in data["segments"]}
        assert "trending-up" in regimes
        assert "choppy" in regimes

    def test_live_filter_excludes_shadow(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0, regime="trending-up"))
            log_signal(conn, _signal(shadow=1, regime="shadow-only-regime"))

        r = client.get("/api/regime?filter=live")
        data = json.loads(r.data)
        regimes = {s["regime"] for s in data["segments"]}
        assert "shadow-only-regime" not in regimes

    def test_empty_db_no_crash(self, client, tmp_db):
        r = client.get("/api/regime?filter=live")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["segments"] == []
        assert data["period_start"] is None

    def test_period_start_end_match_min_max(self, client, tmp_db):
        base = datetime(2026, 1, 10, tzinfo=timezone.utc)
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0, fired_at=base))
            log_signal(conn, _signal(shadow=0, fired_at=base + timedelta(days=5)))

        r = client.get("/api/regime?filter=live")
        data = json.loads(r.data)
        assert data["period_start"] == "2026-01-10"
        assert data["period_end"] == "2026-01-15"


# ── /api/stats all-filter ─────────────────────────────────────────────────────

class TestStatsAllFilter:
    def test_all_filter_includes_live_and_shadow(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            sid = log_signal(conn, _signal(shadow=0))
            update_outcome(conn, sid, "win", 52000.0, pnl_r=2.0)
            sid = log_signal(conn, _signal(shadow=1))
            update_outcome(conn, sid, "loss", 49000.0, pnl_r=-1.0)

        r = client.get("/api/stats?filter=all")
        data = json.loads(r.data)
        assert r.status_code == 200
        assert data["total_fired"] == 2
        assert data["wins"] == 1
        assert data["losses"] == 1

    def test_all_filter_regime_includes_shadow(self, client, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _signal(shadow=0, regime="trending-up"))
            log_signal(conn, _signal(shadow=1, regime="shadow-regime"))

        r = client.get("/api/regime?filter=all")
        data = json.loads(r.data)
        regimes = {s["regime"] for s in data["segments"]}
        assert "trending-up" in regimes
        assert "shadow-regime" in regimes


# ── token auth ───────────────────────────────────────────────────────────────

class TestTokenAuth:
    def test_missing_token_returns_401(self, client_auth):
        r = client_auth.get("/api/signals")
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, client_auth):
        r = client_auth.get("/api/signals",
                            headers={"Authorization": "Bearer wrong-token"})
        assert r.status_code == 401

    def test_correct_token_returns_200(self, client_auth):
        r = client_auth.get("/api/signals",
                            headers={"Authorization": "Bearer test-secret-xyz"})
        assert r.status_code == 200


# ── / index route ─────────────────────────────────────────────────────────────

class TestIndexRoute:
    def test_index_serves_dashboard_html(self, client):
        r = client.get("/")
        assert r.status_code == 200


# ── /api/diagnostics/wr-comparison ───────────────────────────────────────────

class TestWrComparison:
    def test_empty_db_returns_empty_list(self, client, tmp_db):
        r = client.get("/api/diagnostics/wr-comparison")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data == []

    def test_live_signals_appear_without_backtest(self, client, tmp_db):
        from datetime import datetime, timezone, timedelta
        fired = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        with get_conn(tmp_db) as conn:
            conn.execute("""
                INSERT INTO signals (pair, direction, strategy, regime, entry_price,
                    suggested_stop_loss, suggested_take_profit, timeframe, fired_at,
                    shadow_mode, pnl_r)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, ("BTC/USDT:USDT", "long", "supply_demand", "choppy",
                  50000.0, 49000.0, 52000.0, "15m", fired, 0, 1.5))
            conn.commit()

        r = client.get("/api/diagnostics/wr-comparison")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert len(data) == 1
        row = data[0]
        assert row["strategy"] == "supply_demand"
        assert row["regime"] == "choppy"
        assert row["live_signal_wr"] == pytest.approx(1.0)
        assert row["live_n"] == 1
        assert row["backtest_signal_wr"] is None

    def test_divergence_computed_when_both_present(self, client, tmp_db):
        from datetime import datetime, timezone, timedelta
        fired = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        with get_conn(tmp_db) as conn:
            # Insert a completed backtest run
            conn.execute(
                "INSERT INTO backtest_runs (since_date, status) VALUES ('2025-01-01', 'done')"
            )
            run_id = conn.execute("SELECT MAX(id) FROM backtest_runs").fetchone()[0]

            # Backtest signal: 3 wins out of 4 = 75% WR
            for win in [1.0, 1.0, 1.0, -1.0]:
                conn.execute("""
                    INSERT INTO signals (pair, direction, strategy, regime, entry_price,
                        suggested_stop_loss, suggested_take_profit, timeframe, fired_at,
                        shadow_mode, pnl_r, backtest_run_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, ("BTC/USDT:USDT", "long", "supply_demand", "choppy",
                      50000.0, 49000.0, 52000.0, "15m", "2025-06-01T00:00:00",
                      0, win, run_id))

            # Live signal: 1 win out of 2 = 50% WR
            for win in [1.0, -1.0]:
                conn.execute("""
                    INSERT INTO signals (pair, direction, strategy, regime, entry_price,
                        suggested_stop_loss, suggested_take_profit, timeframe, fired_at,
                        shadow_mode, pnl_r)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, ("BTC/USDT:USDT", "long", "supply_demand", "choppy",
                      50000.0, 49000.0, 52000.0, "15m", fired, 0, win))
            conn.commit()

        r = client.get("/api/diagnostics/wr-comparison")
        assert r.status_code == 200
        data = json.loads(r.data)
        row = next(d for d in data if d["strategy"] == "supply_demand")
        assert row["backtest_signal_wr"] == pytest.approx(0.75)
        assert row["live_signal_wr"] == pytest.approx(0.5)
        assert row["signal_divergence"] == pytest.approx(25.0, abs=0.1)  # 75-50 = 25pp


# ── login / logout ────────────────────────────────────────────────────────────

class TestLoginFlow:
    def test_login_page_accessible_without_auth(self, client_auth):
        r = client_auth.get("/login")
        assert r.status_code == 200
        assert b"Signal Engine" in r.data

    def test_correct_password_sets_session_and_redirects(self, client_auth):
        r = client_auth.post("/login", data={"password": "test-secret-xyz", "next": "/"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")

    def test_wrong_password_redirects_with_error(self, client_auth):
        r = client_auth.post("/login", data={"password": "wrong-password", "next": "/"})
        assert r.status_code == 302
        assert "error=1" in r.headers["Location"]

    def test_unauthenticated_index_redirects_to_login(self, client_auth):
        r = client_auth.get("/")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_authenticated_session_serves_dashboard(self, client_auth):
        with client_auth.session_transaction() as sess:
            sess["authed"] = True
        r = client_auth.get("/")
        assert r.status_code == 200
        assert b"dashboard" in r.data.lower()

    def test_logout_clears_session_and_redirects(self, client_auth):
        with client_auth.session_transaction() as sess:
            sess["authed"] = True
        r = client_auth.get("/logout")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]
        # session should be cleared — index should now redirect
        r2 = client_auth.get("/")
        assert r2.status_code == 302
