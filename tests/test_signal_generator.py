import pytest
import numpy as np
import pandas as pd
from regime.classifier import RegimeResult, _to_df
from signals.generator import ema_9_21_crossover, rsi_divergence, vol_breakout, _calc_stop_loss


def _make_regime(label="trending-up", conf=0.8, age=5, stable=True):
    return RegimeResult(label=label, confidence=conf, age_candles=age, stable=stable)


class TestStopLoss:
    def test_long_stop_below_entry(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        entry = df["close"].iloc[-1]
        stop = _calc_stop_loss(df, "long")
        assert stop is not None
        assert stop < entry

    def test_short_stop_above_entry(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        entry = df["close"].iloc[-1]
        stop = _calc_stop_loss(df, "short")
        assert stop is not None
        assert stop > entry

    def test_stop_uses_atr_multiplier(self, trending_up_ohlcv):
        import pandas_ta as ta
        from utils.config import get as cfg
        df = _to_df(trending_up_ohlcv)
        c = cfg()["signals"]
        atr = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
        stop = _calc_stop_loss(df, "long")
        entry = df["close"].iloc[-1]
        expected = round(entry - atr * c["atr_stop_multiplier"], 8)
        assert abs(stop - expected) < 0.01


class TestEma9_21Crossover:
    def test_returns_none_or_signal(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        assert result is None or result["direction"] in ("long", "short")

    def test_returns_correct_schema(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        result = ema_9_21_crossover("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert "pair" in result
            assert "direction" in result
            assert result["strategy"] == "ema_9_21_crossover"
            assert result["shadow_mode"] is True
            assert result["entry_price"] > 0
            assert result["suggested_stop_loss"] is not None


class TestRsiDivergence:
    def test_returns_none_or_dict(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("choppy")
        result = rsi_divergence("ETH/USDT:USDT", df, regime, "15m")
        assert result is None or isinstance(result, dict)

    def test_schema_if_signal(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("choppy")
        result = rsi_divergence("ETH/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["strategy"] == "rsi_divergence"
            assert result["direction"] in ("long", "short")


class TestVolBreakout:
    def test_returns_none_without_breakout(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("high-volatility")
        result = vol_breakout("SOL/USDT:USDT", df, regime, "15m")
        assert result is None or result["strategy"] == "vol_breakout"

    def test_momentum_breakout_not_mean_reversion(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        regime = _make_regime("high-volatility")
        import pandas_ta as ta
        from utils.config import get as cfg
        c = cfg()["regime"]
        bb = ta.bbands(df["close"], length=c["bb_period"], std=c["bb_std"])
        upper_col = next(col for col in bb.columns if col.startswith("BBU_"))
        lower_col = next(col for col in bb.columns if col.startswith("BBL_"))
        if not pd.isna(bb[upper_col].iloc[-1]):
            df = df.copy()
            # Old mean-reversion scenario: prev outside, curr inside → must NOT fire
            df.iloc[-2, df.columns.get_loc("close")] = bb[upper_col].iloc[-2] * 1.01
            df.iloc[-1, df.columns.get_loc("close")] = bb[upper_col].iloc[-1] * 0.99
            result = vol_breakout("BTC/USDT:USDT", df, regime, "15m")
            assert result is None, "vol_breakout must not fire on mean-reversion pattern"
