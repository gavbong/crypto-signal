from unittest.mock import MagicMock, patch
from regime.classifier import RegimeResult
from signal_engine import run_once


def _make_regime(label="trending-up", stable=True, age=5):
    return RegimeResult(label=label, confidence=0.82, age_candles=age, stable=stable)


def _make_mock_ohlcv(n=60):
    """Generate minimal OHLCV list with enough candles."""
    import time
    now_ms = int(time.time() * 1000)
    candles = []
    for i in range(n):
        ts = now_ms - (n - i) * 15 * 60 * 1000
        candles.append([ts, 100.0, 101.0, 99.0, 100.5, 500.0])
    return candles


class TestMtfRegimePassthrough:
    def test_pair_with_stable_regime_processes_strategies(self, tmp_db):
        """Pair present in regimes_1h with stable=True → strategies are evaluated."""
        pair = "BTC/USDT:USDT"
        regimes_1h = {pair: _make_regime("choppy", stable=True)}

        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = _make_mock_ohlcv()

        with patch("signal_engine.fetch_ohlcv_safe", return_value=_make_mock_ohlcv()), \
             patch("signal_engine.fetch_ticker_safe", return_value={"last": 100.5}), \
             patch("signal_engine.run_strategy", return_value=None), \
             patch("signal_engine.generate_commentary", return_value=None):
            from db.schema import init_db, get_conn
            init_db(tmp_db)
            with get_conn(tmp_db) as conn:
                fired = run_once(
                    mock_exchange, conn, [pair], "15m", 100, 3,
                    regimes_1h, shadow_mode=True
                )
            # No signals fired (run_strategy returns None) but no crash
            assert isinstance(fired, list)

    def test_pair_missing_from_regimes_skipped(self, tmp_db):
        """Pair NOT in regimes_1h → skipped with warning, no signals."""
        pair = "ETH/USDT:USDT"
        regimes_1h = {}  # empty — ETH not classified

        mock_exchange = MagicMock()

        with patch("signal_engine.fetch_ohlcv_safe", return_value=_make_mock_ohlcv()), \
             patch("signal_engine.fetch_ticker_safe", return_value={"last": 200.0}):
            from db.schema import init_db, get_conn
            init_db(tmp_db)
            with get_conn(tmp_db) as conn:
                fired = run_once(
                    mock_exchange, conn, [pair], "15m", 100, 3,
                    regimes_1h, shadow_mode=True
                )
            assert fired == []

    def test_pair_with_unstable_regime_skipped(self, tmp_db):
        """Pair present but regime.stable=False → skipped, no strategies run."""
        pair = "SOL/USDT:USDT"
        regimes_1h = {pair: _make_regime("trending-up", stable=False, age=2)}

        mock_exchange = MagicMock()

        with patch("signal_engine.run_strategy") as mock_run:
            from db.schema import init_db, get_conn
            init_db(tmp_db)
            with get_conn(tmp_db) as conn:
                fired = run_once(
                    mock_exchange, conn, [pair], "15m", 100, 3,
                    regimes_1h, shadow_mode=True
                )
            mock_run.assert_not_called()
            assert fired == []
