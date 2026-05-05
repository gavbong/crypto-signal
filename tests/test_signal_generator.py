import pytest
import numpy as np
import pandas as pd
from regime.classifier import RegimeResult, _to_df
from signals.generator import ema_9_21_crossover, rsi_divergence, vol_breakout, _calc_stop_loss, _calc_take_profit


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


class TestCalcTakeProfit:
    """Verify per-regime RR ratios are applied by _calc_take_profit."""

    def test_choppy_uses_lower_rr(self):
        from utils.config import get as cfg
        c = cfg()["signals"]
        entry, stop = 100.0, 98.0  # risk = 2.0
        tp_choppy = _calc_take_profit(entry, stop, "long", "choppy")
        tp_default = _calc_take_profit(entry, stop, "long", "")
        rr_choppy = c.get("rr_ratio_choppy", c["rr_ratio"])
        rr_default = c["rr_ratio"]
        assert abs(tp_choppy - (entry + 2.0 * rr_choppy)) < 1e-6
        assert rr_choppy < rr_default, "choppy RR should be lower (tighter target)"

    def test_trending_uses_higher_rr(self):
        from utils.config import get as cfg
        c = cfg()["signals"]
        entry, stop = 100.0, 98.0
        tp_trending = _calc_take_profit(entry, stop, "long", "trending-up")
        rr_trending = c.get("rr_ratio_trending", c["rr_ratio"])
        assert abs(tp_trending - (entry + 2.0 * rr_trending)) < 1e-6

    def test_high_vol_rr_between_choppy_and_trending(self):
        from utils.config import get as cfg
        c = cfg()["signals"]
        entry, stop = 100.0, 98.0
        tp_hv = _calc_take_profit(entry, stop, "long", "high-volatility")
        rr_hv = c.get("rr_ratio_high_vol", c["rr_ratio"])
        rr_choppy = c.get("rr_ratio_choppy", c["rr_ratio"])
        rr_trending = c.get("rr_ratio_trending", c["rr_ratio"])
        assert rr_choppy <= rr_hv <= rr_trending, "high-vol RR should be between choppy and trending"
        assert abs(tp_hv - (entry + 2.0 * rr_hv)) < 1e-6

    def test_short_direction_tp_below_entry(self):
        entry, stop = 100.0, 102.0
        for regime in ("choppy", "trending-down", "high-volatility", ""):
            tp = _calc_take_profit(entry, stop, "short", regime)
            assert tp < entry, f"Short TP must be below entry for regime={regime!r}"

    def test_unknown_regime_uses_default_rr(self):
        from utils.config import get as cfg
        c = cfg()["signals"]
        entry, stop = 100.0, 98.0
        tp = _calc_take_profit(entry, stop, "long", "nonexistent-regime")
        assert abs(tp - (entry + 2.0 * c["rr_ratio"])) < 1e-6


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
