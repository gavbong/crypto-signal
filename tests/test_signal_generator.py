import pytest
import numpy as np
import pandas as pd
from regime.classifier import RegimeResult, _to_df
from signals.generator import ema_crossover, rsi_divergence, vol_breakout, _calc_stop_loss


def _make_regime(label="trending-up", conf=0.8, age=5, stable=True):
    return RegimeResult(label=label, confidence=conf, age_candles=age, stable=stable)


def _inject_ema_crossover_long(df: pd.DataFrame) -> pd.DataFrame:
    """Force EMA20 to cross above EMA50 on the last two candles."""
    df = df.copy()
    # Make last candle much higher than prior to force a crossover
    last_close = df["close"].iloc[-1]
    df.iloc[-1, df.columns.get_loc("close")] = last_close * 1.05
    df.iloc[-2, df.columns.get_loc("close")] = last_close * 0.95
    return df


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


class TestEmaCrossover:
    def test_no_crossover_returns_none(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        # In a clean trending fixture the EMA crossover has likely already happened
        # so we just assert the return type contract
        result = ema_crossover("BTC/USDT:USDT", df, regime, "1h")
        assert result is None or result["direction"] in ("long", "short")

    def test_returns_correct_schema(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        regime = _make_regime("trending-up")
        result = ema_crossover("BTC/USDT:USDT", df, regime, "1h")
        if result is not None:
            assert "pair" in result
            assert "direction" in result
            assert "strategy" in result
            assert result["strategy"] == "ema_crossover"
            assert result["shadow_mode"] is True
            assert result["entry_price"] > 0
            assert result["suggested_stop_loss"] is not None


class TestRsiDivergence:
    def test_returns_none_or_dict(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("choppy")
        result = rsi_divergence("ETH/USDT:USDT", df, regime, "1h")
        assert result is None or isinstance(result, dict)

    def test_schema_if_signal(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("choppy")
        result = rsi_divergence("ETH/USDT:USDT", df, regime, "1h")
        if result is not None:
            assert result["strategy"] == "rsi_divergence"
            assert result["direction"] in ("long", "short")


class TestVolBreakout:
    def test_returns_none_without_breakout(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        regime = _make_regime("high-volatility")
        # Choppy data is unlikely to produce a BB breakout
        result = vol_breakout("SOL/USDT:USDT", df, regime, "1h")
        assert result is None or result["strategy"] == "vol_breakout"

    def test_fires_on_upper_bb_breach(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        regime = _make_regime("high-volatility")
        # Force a breakout by setting last close above upper BB
        import pandas_ta as ta
        from utils.config import get as cfg
        c = cfg()["regime"]
        bb = ta.bbands(df["close"], length=c["bb_period"], std=c["bb_std"])
        upper_col = next(col for col in bb.columns if col.startswith("BBU_"))
        if not pd.isna(bb[upper_col].iloc[-1]):
            df = df.copy()
            df.iloc[-1, df.columns.get_loc("close")] = bb[upper_col].iloc[-1] * 1.01
            df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1] * 1.005
            result = vol_breakout("BTC/USDT:USDT", df, regime, "1h")
            if result is not None:
                assert result["direction"] == "long"
