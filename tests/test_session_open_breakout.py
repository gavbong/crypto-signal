"""Tests for session_open_breakout strategy."""
import numpy as np
import pandas as pd
import pytest
from regime.classifier import RegimeResult
from signals.generator import session_open_breakout


def _make_regime(label="trending-up"):
    return RegimeResult(label=label, confidence=0.75, age_candles=5, stable=True)


def _make_orb_df(
    open_hour: int = 9,
    open_minute: int = 30,
    tz: str = "America/New_York",
    breakout_dir: str = "long",
    in_window: bool = True,
    vol_multiple: float = 2.0,
) -> pd.DataFrame:
    """Build a 25-candle 15m DataFrame where the last candle is a breakout of the ORB.

    tz: timezone of the session open (America/New_York for DJ30, etc.)
    breakout_dir: 'long' (close > range_high) or 'short' (close < range_low)
    in_window: if False, sets the last candle 3h after open (outside 30-90 min window)
    vol_multiple: volume multiplier on the breakout candle (vs avg)
    """
    from zoneinfo import ZoneInfo

    tz_zone = ZoneInfo(tz)
    today = pd.Timestamp.now(tz=tz_zone).normalize()

    open_ts = today.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)

    if in_window:
        breakout_offset = 30  # 30 min after open = start of window
    else:
        breakout_offset = 180  # 3h after open = outside 90-min window

    candle_times_local = [
        open_ts - pd.Timedelta(minutes=15 * (24 - i))
        for i in range(22)
    ] + [
        open_ts,
        open_ts + pd.Timedelta(minutes=15),
        open_ts + pd.Timedelta(minutes=breakout_offset),
    ]
    candle_times_utc = pd.DatetimeIndex([t.tz_convert("UTC") for t in candle_times_local])

    n = len(candle_times_utc)
    base_price = 100.0
    closes = np.full(n, base_price)
    opens = closes - 0.1
    range_high = base_price + 0.5
    range_low = base_price - 0.5
    highs = np.full(n, range_high)
    lows = np.full(n, range_low)

    avg_vol = 1000.0
    volumes = np.full(n, avg_vol)

    if breakout_dir == "long":
        closes[-1] = range_high + 0.2
        highs[-1] = range_high + 0.3
    else:
        closes[-1] = range_low - 0.2
        lows[-1] = range_low - 0.3

    volumes[-1] = avg_vol * vol_multiple

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=candle_times_utc,
    )


class TestSessionOpenBreakout:
    def test_long_signal_in_window(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("DJ30/USD", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "long"
        assert result["strategy"] == "session_open_breakout"
        assert result["suggested_stop_loss"] < result["entry_price"]
        assert result["suggested_take_profit"] > result["entry_price"]

    def test_short_signal_in_window(self):
        df = _make_orb_df(breakout_dir="short", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-down")
        result = session_open_breakout("DJ30/USD", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "short"
        assert result["suggested_stop_loss"] > result["entry_price"]
        assert result["suggested_take_profit"] < result["entry_price"]

    def test_no_signal_outside_window(self):
        df = _make_orb_df(breakout_dir="long", in_window=False, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("DJ30/USD", df, regime, "15m")
        assert result is None

    def test_no_signal_low_volume(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=0.5)
        regime = _make_regime("trending-up")
        result = session_open_breakout("DJ30/USD", df, regime, "15m")
        assert result is None

    def test_xau_skipped(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("XAU/USD", df, regime, "15m")
        assert result is None

    def test_crypto_pair_skipped(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_higher_tf_skipped(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("DJ30/USD", df, regime, "1h")
        assert result is None

    def test_signal_schema_complete(self):
        df = _make_orb_df(breakout_dir="long", in_window=True, vol_multiple=2.0)
        regime = _make_regime("trending-up")
        result = session_open_breakout("DJ30/USD", df, regime, "15m")
        if result is not None:
            assert result["pair"] == "DJ30/USD"
            assert result["entry_price"] > 0
            assert result["suggested_stop_loss"] is not None
            assert result["suggested_take_profit"] is not None
            assert "fired_at" in result
