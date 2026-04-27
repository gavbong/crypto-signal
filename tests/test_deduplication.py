from datetime import datetime, timedelta, timezone
import pytest
from db.schema import init_db, get_conn, log_signal, is_duplicate


def _make_signal(pair="BTC/USDT:USDT", direction="long", strategy="ema_crossover",
                 regime="trending-up", fired_at: datetime | None = None):
    if fired_at is None:
        fired_at = datetime.now(timezone.utc)
    return {
        "pair": pair,
        "direction": direction,
        "strategy": strategy,
        "regime": regime,
        "regime_confidence": 0.8,
        "regime_age_candles": 5,
        "entry_price": 50000.0,
        "suggested_stop_loss": 49000.0,
        "timeframe": "1h",
        "fired_at": fired_at.isoformat(),
        "shadow_mode": True,
        "llm_commentary": None,
        "commentary_status": "pending",
    }


class TestDeduplication:
    def test_no_prior_signal_not_duplicate(self, tmp_db):
        with get_conn(tmp_db) as conn:
            assert is_duplicate(conn, "BTC/USDT:USDT", "long", "ema_crossover",
                                 "trending-up", 3) is False

    def test_duplicate_within_window(self, tmp_db):
        with get_conn(tmp_db) as conn:
            fired = datetime.now(timezone.utc) - timedelta(hours=2)
            log_signal(conn, _make_signal(fired_at=fired))
            assert is_duplicate(conn, "BTC/USDT:USDT", "long", "ema_crossover",
                                 "trending-up", 3) is True

    def test_not_duplicate_after_window(self, tmp_db):
        with get_conn(tmp_db) as conn:
            fired = datetime.now(timezone.utc) - timedelta(hours=4)
            log_signal(conn, _make_signal(fired_at=fired))
            assert is_duplicate(conn, "BTC/USDT:USDT", "long", "ema_crossover",
                                 "trending-up", 3) is False

    def test_different_direction_not_duplicate(self, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _make_signal(direction="long"))
            assert is_duplicate(conn, "BTC/USDT:USDT", "short", "ema_crossover",
                                 "trending-down", 3) is False

    def test_different_strategy_not_duplicate(self, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _make_signal(strategy="ema_crossover"))
            assert is_duplicate(conn, "BTC/USDT:USDT", "long", "rsi_divergence",
                                 "trending-up", 3) is False

    def test_regime_flip_allows_new_signal(self, tmp_db):
        """Key test: dedup key includes regime — a regime flip unlocks a new signal."""
        with get_conn(tmp_db) as conn:
            fired = datetime.now(timezone.utc) - timedelta(hours=1)
            log_signal(conn, _make_signal(strategy="ema_crossover", regime="trending-up",
                                          fired_at=fired))
            # Same pair+direction+strategy but different regime: should NOT be duplicate
            assert is_duplicate(conn, "BTC/USDT:USDT", "long", "ema_crossover",
                                 "choppy", 3) is False

    def test_different_pair_not_duplicate(self, tmp_db):
        with get_conn(tmp_db) as conn:
            log_signal(conn, _make_signal(pair="BTC/USDT:USDT"))
            assert is_duplicate(conn, "ETH/USDT:USDT", "long", "ema_crossover",
                                 "trending-up", 3) is False
