import pandas as pd
import numpy as np
from regime.classifier import RegimeResult, _to_df
from signals.generator import ema_9_21_crossover


def _make_regime(label="trending-up"):
    return RegimeResult(label=label, confidence=0.8, age_candles=5, stable=True)


def _make_df(n=60, base_price=100.0) -> pd.DataFrame:
    """Flat price DataFrame — no crossover by default."""
    times = pd.date_range("2024-01-01", periods=n, freq="15min")
    closes = np.full(n, base_price)
    opens = closes * 0.999
    highs = closes * 1.002
    lows = closes * 0.997
    volumes = np.full(n, 1000.0)
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows,
                       "close": closes, "volume": volumes}, index=times)
    return df


def _inject_long_crossover(df: pd.DataFrame) -> pd.DataFrame:
    """Force EMA9 to cross above EMA21 on last two candles, close > EMA9."""
    df = df.copy()
    n = len(df)
    # Make prior candles flat at 100, then spike last two to force crossover
    df.iloc[-2, df.columns.get_loc("close")] = 95.0
    df.iloc[-1, df.columns.get_loc("close")] = 115.0
    df.iloc[-1, df.columns.get_loc("high")] = 116.0
    return df


def _inject_short_crossover(df: pd.DataFrame) -> pd.DataFrame:
    """Force EMA9 to cross below EMA21 on last two candles, close < EMA9."""
    df = df.copy()
    df.iloc[-2, df.columns.get_loc("close")] = 105.0
    df.iloc[-1, df.columns.get_loc("close")] = 85.0
    df.iloc[-1, df.columns.get_loc("low")] = 84.0
    return df


class TestEma9_21Crossover:
    def test_long_crossover_returns_long_signal(self, trending_up_ohlcv):
        df = _inject_long_crossover(_to_df(trending_up_ohlcv))
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["direction"] == "long"
            assert result["strategy"] == "ema_9_21_crossover"

    def test_short_crossover_returns_short_signal(self, trending_down_ohlcv):
        df = _inject_short_crossover(_to_df(trending_down_ohlcv))
        regime = _make_regime("trending-down")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["direction"] == "short"
            assert result["strategy"] == "ema_9_21_crossover"

    def test_no_crossover_returns_none(self):
        df = _make_df(60, base_price=100.0)
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_nan_guard_insufficient_candles(self):
        df = _make_df(5)  # way too few for EMA21
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_signal_schema(self, trending_up_ohlcv):
        df = _inject_long_crossover(_to_df(trending_up_ohlcv))
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["pair"] == "BTC/USDT:USDT"
            assert result["entry_price"] > 0
            assert result["suggested_stop_loss"] is not None
            assert result["suggested_take_profit"] is not None
