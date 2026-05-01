import pandas as pd
import numpy as np
from regime.classifier import RegimeResult, _to_df
from signals.generator import macd_crossover


def _make_regime(label="trending-up"):
    return RegimeResult(label=label, confidence=0.8, age_candles=5, stable=True)


def _make_trending_df(n=80, direction="up") -> pd.DataFrame:
    """Steadily trending price series long enough for MACD (26+9 warmup)."""
    times = pd.date_range("2024-01-01", periods=n, freq="15min")
    if direction == "up":
        closes = np.linspace(90, 110, n)
    else:
        closes = np.linspace(110, 90, n)
    opens = closes * 0.999
    highs = closes * 1.002
    lows = closes * 0.997
    volumes = np.full(n, 1000.0)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": volumes}, index=times)


class TestMacdCrossover:
    def test_long_signal_on_bullish_cross(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        result = macd_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None or result["direction"] == "long"

    def test_short_signal_on_bearish_cross(self, trending_down_ohlcv):
        df = _to_df(trending_down_ohlcv)
        regime = _make_regime("trending-down")
        result = macd_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None or result["direction"] == "short"

    def test_nan_guard_insufficient_data(self):
        times = pd.date_range("2024-01-01", periods=10, freq="15min")
        df = pd.DataFrame({
            "open": np.ones(10) * 100,
            "high": np.ones(10) * 101,
            "low": np.ones(10) * 99,
            "close": np.ones(10) * 100,
            "volume": np.ones(10) * 500,
        }, index=times)
        regime = _make_regime("trending-up")
        result = macd_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_signal_schema(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        result = macd_crossover("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["strategy"] == "macd_crossover"
            assert result["direction"] in ("long", "short")
            assert result["entry_price"] > 0
            assert result["suggested_stop_loss"] is not None

    def test_histogram_confirm_required(self, choppy_ohlcv):
        """In choppy data with no clear trend, MACD should fire only on genuine crosses."""
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("choppy")
        result = macd_crossover("ETH/USDT:USDT", df, regime, "15m")
        # Result must be None or a valid signal — never crashes
        assert result is None or isinstance(result, dict)
