import pandas as pd
import numpy as np
import pandas_ta as ta
from regime.classifier import RegimeResult, _to_df
from signals.generator import vol_breakout
from utils.config import get as cfg


def _make_regime(label="high-volatility"):
    return RegimeResult(label=label, confidence=0.85, age_candles=6, stable=True)


def _get_bb(df: pd.DataFrame):
    c = cfg()["regime"]
    bb = ta.bbands(df["close"], length=c["bb_period"], std=c["bb_std"])
    upper_col = next(col for col in bb.columns if col.startswith("BBU_"))
    lower_col = next(col for col in bb.columns if col.startswith("BBL_"))
    return bb, upper_col, lower_col


def _add_consolidation(df: pd.DataFrame, upper_col: str, lower_col: str, bb) -> pd.DataFrame:
    """Force 6 of 8 prior candles inside the BB bands."""
    df = df.copy()
    bb_recomputed = ta.bbands(df["close"], length=cfg()["regime"]["bb_period"],
                               std=cfg()["regime"]["bb_std"])
    for i in range(-9, -1):
        mid = (bb_recomputed[upper_col].iloc[i] + bb_recomputed[lower_col].iloc[i]) / 2
        df.iloc[i, df.columns.get_loc("close")] = mid
        df.iloc[i, df.columns.get_loc("open")] = mid * 0.999
    return df


class TestVolBreakoutMomentum:
    def test_long_breakout_with_consolidation(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        bb, upper_col, lower_col = _get_bb(df)
        upper = bb[upper_col].iloc[-1]
        if pd.isna(upper):
            return

        df = _add_consolidation(df, upper_col, lower_col, bb)

        # Spike last candle above upper band with high volume
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = upper * 1.02
        df.iloc[-1, df.columns.get_loc("high")] = upper * 1.025
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-20:].mean() * 2.0

        regime = _make_regime("high-volatility")
        result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "long"
        assert result["strategy"] == "vol_breakout"

    def test_short_breakout_with_consolidation(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        bb, upper_col, lower_col = _get_bb(df)
        lower = bb[lower_col].iloc[-1]
        if pd.isna(lower):
            return

        df = _add_consolidation(df, upper_col, lower_col, bb)

        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = lower * 0.98
        df.iloc[-1, df.columns.get_loc("low")] = lower * 0.975
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-20:].mean() * 2.0

        regime = _make_regime("high-volatility")
        result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "short"
        assert result["strategy"] == "vol_breakout"

    def test_breakout_without_consolidation_returns_none(self, high_vol_ohlcv):
        """Price outside band for several prior candles → no consolidation → None."""
        df = _to_df(high_vol_ohlcv)
        bb, upper_col, lower_col = _get_bb(df)
        upper = bb[upper_col].iloc[-1]
        if pd.isna(upper):
            return

        df = df.copy()
        # Force 8 prior candles above upper band (no consolidation)
        for i in range(-9, -1):
            df.iloc[i, df.columns.get_loc("close")] = upper * 1.05
        df.iloc[-1, df.columns.get_loc("close")] = upper * 1.06
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-20:].mean() * 2.0

        regime = _make_regime("high-volatility")
        result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_breakout_without_volume_spike_returns_none(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        bb, upper_col, lower_col = _get_bb(df)
        upper = bb[upper_col].iloc[-1]
        if pd.isna(upper):
            return

        df = _add_consolidation(df, upper_col, lower_col, bb)
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = upper * 1.02
        # Volume below threshold
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-20:].mean() * 0.5

        regime = _make_regime("high-volatility")
        result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_old_mean_reversion_does_not_fire(self, high_vol_ohlcv):
        """Old behavior: close_prev > upper AND close_now <= upper → must NOT fire."""
        df = _to_df(high_vol_ohlcv)
        bb, upper_col, lower_col = _get_bb(df)
        upper_prev = bb[upper_col].iloc[-2]
        upper_now = bb[upper_col].iloc[-1]
        if pd.isna(upper_prev) or pd.isna(upper_now):
            return

        df = df.copy()
        df.iloc[-2, df.columns.get_loc("close")] = upper_prev * 1.01  # prev outside
        df.iloc[-1, df.columns.get_loc("close")] = upper_now * 0.99   # now inside
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-20:].mean() * 2.0

        regime = _make_regime("high-volatility")
        result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is None, "vol_breakout must not fire on old mean-reversion pattern"
