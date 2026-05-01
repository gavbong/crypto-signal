import pandas as pd
import numpy as np
from regime.classifier import RegimeResult, _to_df
from signals.generator import liquidity_grab
import pandas_ta as ta


def _make_regime(label="high-volatility"):
    return RegimeResult(label=label, confidence=0.8, age_candles=5, stable=True)


def _make_range_df(n=60, price=100.0) -> pd.DataFrame:
    """Sideways market oscillating slightly around price."""
    times = pd.date_range("2024-01-01", periods=n, freq="15min")
    noise = np.sin(np.linspace(0, 4 * np.pi, n)) * 0.5
    closes = price + noise
    opens = closes - 0.1
    highs = closes + 0.3
    lows = closes - 0.3
    volumes = np.full(n, 1000.0)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": volumes}, index=times)


def _get_atr(df: pd.DataFrame) -> float:
    from utils.config import get as cfg
    c = cfg()["signals"]
    return ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]


class TestLiquidityGrab:
    def test_long_sweep_and_reversal(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        atr = _get_atr(df)
        if pd.isna(atr):
            return

        prior = df.iloc[:-1].iloc[-20:]
        swing_low = prior["low"].min()

        # Engineer last candle: sweeps swing low, closes well above it
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("low")] = swing_low - 0.4 * atr
        df.iloc[-1, df.columns.get_loc("close")] = swing_low + 0.3 * atr
        df.iloc[-1, df.columns.get_loc("open")] = swing_low - 0.1 * atr
        df.iloc[-1, df.columns.get_loc("high")] = swing_low + 0.35 * atr

        regime = _make_regime("high-volatility")
        result = liquidity_grab("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "long"
        assert result["strategy"] == "liquidity_grab"

    def test_short_sweep_and_reversal(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        atr = _get_atr(df)
        if pd.isna(atr):
            return

        prior = df.iloc[:-1].iloc[-20:]
        swing_high = prior["high"].max()

        df = df.copy()
        df.iloc[-1, df.columns.get_loc("high")] = swing_high + 0.4 * atr
        df.iloc[-1, df.columns.get_loc("close")] = swing_high - 0.3 * atr
        df.iloc[-1, df.columns.get_loc("open")] = swing_high + 0.1 * atr
        df.iloc[-1, df.columns.get_loc("low")] = swing_high - 0.35 * atr

        regime = _make_regime("high-volatility")
        result = liquidity_grab("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "short"
        assert result["strategy"] == "liquidity_grab"

    def test_sweep_without_sufficient_reversal_returns_none(self, choppy_ohlcv):
        """Sweeps swing low but closes just at swing level, not 0.2 ATR inside."""
        df = _to_df(choppy_ohlcv)
        atr = _get_atr(df)
        if pd.isna(atr):
            return

        prior = df.iloc[:-1].iloc[-20:]
        swing_low = prior["low"].min()

        df = df.copy()
        df.iloc[-1, df.columns.get_loc("low")] = swing_low - 0.4 * atr
        # Close just at swing_low — does NOT satisfy +0.2 ATR reversal
        df.iloc[-1, df.columns.get_loc("close")] = swing_low + 0.05 * atr

        regime = _make_regime("high-volatility")
        result = liquidity_grab("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_insufficient_lookback_returns_none(self):
        """Fewer than 8 prior candles → None."""
        times = pd.date_range("2024-01-01", periods=8, freq="15min")
        closes = np.linspace(100, 105, 8)
        df = pd.DataFrame({
            "open": closes - 0.1, "high": closes + 0.3,
            "low": closes - 0.3, "close": closes, "volume": np.ones(8) * 500,
        }, index=times)
        regime = _make_regime("high-volatility")
        result = liquidity_grab("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_atr_nan_returns_none(self):
        """Only 5 candles → ATR period (14) not satisfied → NaN → None."""
        times = pd.date_range("2024-01-01", periods=5, freq="15min")
        df = pd.DataFrame({
            "open": [100] * 5, "high": [101] * 5,
            "low": [99] * 5, "close": [100] * 5, "volume": [500] * 5,
        }, index=times)
        regime = _make_regime("high-volatility")
        result = liquidity_grab("BTC/USDT:USDT", df, regime, "15m")
        assert result is None
