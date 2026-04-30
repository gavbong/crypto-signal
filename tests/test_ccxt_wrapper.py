import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import ccxt

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ccxt_wrapper import _make_exchange, fetch_ohlcv_safe, fetch_ticker_safe


class TestMakeExchange:
    def test_ignores_passed_credentials(self):
        """G4: credentials passed to _make_exchange() are never attached to the exchange object."""
        exchange = _make_exchange("real-api-key-12345", "real-secret-abcde")

        assert not exchange.apiKey, "apiKey must be empty — engine only uses public endpoints"
        assert not exchange.secret, "secret must be empty — attaching it triggers private auth"

    def test_uses_swap_defaulttype(self):
        exchange = _make_exchange("", "")
        assert exchange.options.get("defaultType") == "swap"

    def test_rate_limit_enabled(self):
        exchange = _make_exchange("", "")
        assert exchange.enableRateLimit is True


class TestFetchOhlcvSafe:
    def _exchange(self):
        return MagicMock(spec=ccxt.Exchange)

    def test_returns_data_on_success(self):
        exchange = self._exchange()
        expected = [[1_000_000, 1.0, 1.1, 0.9, 1.05, 100.0]]
        exchange.fetch_ohlcv.return_value = expected

        result = fetch_ohlcv_safe(exchange, "BTC/USDT:USDT", "1h", 100)

        assert result == expected
        exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT:USDT", "1h", since=None, limit=100)

    def test_returns_none_on_exchange_error(self):
        exchange = self._exchange()
        exchange.fetch_ohlcv.side_effect = ccxt.ExchangeError("bad symbol")

        result = fetch_ohlcv_safe(exchange, "BTC/USDT:USDT", "1h", 100)

        assert result is None

    def test_returns_none_after_exhausting_retries_rate_limit(self):
        exchange = self._exchange()
        exchange.fetch_ohlcv.side_effect = ccxt.RateLimitExceeded("too many requests")

        with patch("utils.ccxt_wrapper.time.sleep"):
            result = fetch_ohlcv_safe(exchange, "BTC/USDT:USDT", "1h", 100, retries=2)

        assert result is None
        assert exchange.fetch_ohlcv.call_count == 2

    def test_retries_on_network_error_then_succeeds(self):
        exchange = self._exchange()
        expected = [[1_000_000, 1.0, 1.1, 0.9, 1.05, 100.0]]
        exchange.fetch_ohlcv.side_effect = [ccxt.NetworkError("timeout"), expected]

        with patch("utils.ccxt_wrapper.time.sleep"):
            result = fetch_ohlcv_safe(exchange, "BTC/USDT:USDT", "1h", 100)

        assert result == expected
        assert exchange.fetch_ohlcv.call_count == 2

    def test_passes_since_param(self):
        exchange = self._exchange()
        exchange.fetch_ohlcv.return_value = []

        fetch_ohlcv_safe(exchange, "ETH/USDT:USDT", "1h", 50, since=1_700_000_000_000)

        exchange.fetch_ohlcv.assert_called_once_with("ETH/USDT:USDT", "1h", since=1_700_000_000_000, limit=50)


class TestFetchTickerSafe:
    def _exchange(self):
        return MagicMock(spec=ccxt.Exchange)

    def test_returns_ticker_on_success(self):
        exchange = self._exchange()
        expected = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        exchange.fetch_ticker.return_value = expected

        result = fetch_ticker_safe(exchange, "BTC/USDT:USDT")

        assert result == expected

    def test_returns_none_on_exchange_error(self):
        exchange = self._exchange()
        exchange.fetch_ticker.side_effect = ccxt.ExchangeError("bad symbol")

        result = fetch_ticker_safe(exchange, "BTC/USDT:USDT")

        assert result is None

    def test_returns_none_after_exhausting_retries(self):
        exchange = self._exchange()
        exchange.fetch_ticker.side_effect = ccxt.RateLimitExceeded("rate limited")

        with patch("utils.ccxt_wrapper.time.sleep"):
            result = fetch_ticker_safe(exchange, "BTC/USDT:USDT", retries=2)

        assert result is None
        assert exchange.fetch_ticker.call_count == 2

    def test_retries_on_network_error(self):
        exchange = self._exchange()
        exchange.fetch_ticker.side_effect = [ccxt.NetworkError("drop"), {"last": 100.0}]

        with patch("utils.ccxt_wrapper.time.sleep"):
            result = fetch_ticker_safe(exchange, "BTC/USDT:USDT")

        assert result == {"last": 100.0}
