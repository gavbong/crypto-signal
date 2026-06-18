"""Tests for the ict_session_sweep strategy."""
import numpy as np
import pandas as pd
import pytest
from zoneinfo import ZoneInfo

from regime.classifier import RegimeResult
from signals.generator import ict_session_sweep, _ict_find_ndog


def _make_regime(label="choppy"):
    return RegimeResult(label=label, confidence=0.60, age_candles=5, stable=True)


def _make_ict_df(
    direction: str = "long",
    in_killzone: bool = True,
    has_sweep: bool = True,
    has_fvg: bool = True,
    fvg_price_inside: bool = True,
) -> pd.DataFrame:
    """
    Build an 80-candle 15m DataFrame ending inside the NY killzone (10:00 ET).

    Layout (all in ET):
      - Candles 0–22:   pre-Asia filler
      - Candle  30:     session-defining candle  (high=101.0, low=99.0)  → Asia H/L
      - Candle  60:     session-defining candle  (high=100.6, low=99.4)  → London H/L
      - Candle  75:     sweep candle (wick through combined_high or combined_low)
      - Candles 76–78:  FVG window (c0=76, c1=77, c2=78)
      - Candle  79:     current candle (close inside FVG if fvg_price_inside=True)

    combined_high = 101.0, combined_low = 99.0
    """
    tz_et = ZoneInfo("America/New_York")
    today = pd.Timestamp.now(tz=tz_et).normalize()

    if in_killzone:
        current_time = today + pd.Timedelta(hours=10)   # 10:00 ET — inside 09:00–11:00
    else:
        current_time = today + pd.Timedelta(hours=14)   # 14:00 ET — outside killzone

    n = 80
    times_et = [current_time - pd.Timedelta(minutes=15 * (n - 1 - i)) for i in range(n)]
    times_utc = pd.DatetimeIndex([t.tz_convert("UTC") for t in times_et])

    base = 100.0
    session_high = 101.0
    session_low = 99.0
    atr_approx = 0.4   # with high=100.2, low=99.8 → range ≈ 0.4

    opens  = np.full(n, base)
    closes = np.full(n, base)
    highs  = np.full(n, base + 0.2)
    lows   = np.full(n, base - 0.2)
    volumes = np.full(n, 1000.0)

    # Set one Asia-session candle to define combined_high/combined_low
    highs[30] = session_high
    lows[30]  = session_low

    # Set one London-session candle with narrower range (doesn't widen the bounds)
    highs[60] = base + 0.6
    lows[60]  = base - 0.6

    if direction == "long":
        # Sweep of session_low: wick below 99.0, close above
        if has_sweep:
            lows[75]   = session_low - 0.3   # 98.7 < 99.0
            closes[75] = base + 0.05          # 100.05 > 99.0
            opens[75]  = base + 0.05
            highs[75]  = base + 0.15

        # Bullish FVG: c0.high < c2.low, current close inside
        if has_fvg:
            #  c0 (76): tight, high = 99.5
            highs[76]  = base - 0.5    # 99.5
            lows[76]   = base - 0.7    # 99.3
            closes[76] = base - 0.6
            opens[76]  = base - 0.6

            #  c1 (77): impulse up
            opens[77]  = base - 0.6
            closes[77] = base + 0.5
            highs[77]  = base + 0.6
            lows[77]   = base - 0.6

            #  c2 (78): low = 99.8 > c0.high (99.5) → bullish FVG [99.5, 99.8]
            lows[78]   = base - 0.2    # 99.8
            closes[78] = base + 0.1
            opens[78]  = base + 0.1
            highs[78]  = base + 0.3

            #  current (79): close inside FVG [99.5, 99.8]
            if fvg_price_inside:
                closes[79] = base - 0.35   # 99.65 — inside [99.5, 99.8]
                opens[79]  = base - 0.35
                highs[79]  = base - 0.25
                lows[79]   = base - 0.45
            else:
                closes[79] = base + 0.5    # 100.5 — outside FVG
                opens[79]  = base + 0.5
                highs[79]  = base + 0.6
                lows[79]   = base + 0.4

    else:  # short
        # Sweep of session_high: wick above 101.0, close below
        if has_sweep:
            highs[75]  = session_high + 0.3   # 101.3 > 101.0
            closes[75] = base - 0.05           # 99.95 < 101.0
            opens[75]  = base - 0.05
            lows[75]   = base - 0.15

        # Bearish FVG: c0.low > c2.high, current close inside
        if has_fvg:
            #  c0 (76): low = 100.5
            lows[76]   = base + 0.5    # 100.5
            highs[76]  = base + 0.7    # 100.7
            opens[76]  = base + 0.6
            closes[76] = base + 0.6

            #  c1 (77): impulse down
            opens[77]  = base + 0.6
            closes[77] = base - 0.5
            highs[77]  = base + 0.6
            lows[77]   = base - 0.6

            #  c2 (78): high = 100.2 < c0.low (100.5) → bearish FVG [100.2, 100.5]
            highs[78]  = base + 0.2    # 100.2
            closes[78] = base - 0.1
            opens[78]  = base - 0.1
            lows[78]   = base - 0.3

            #  current (79): close inside FVG [100.2, 100.5]
            if fvg_price_inside:
                closes[79] = base + 0.35   # 100.35 — inside [100.2, 100.5]
                opens[79]  = base + 0.35
                highs[79]  = base + 0.45
                lows[79]   = base + 0.25
            else:
                closes[79] = base - 0.5    # 99.5 — outside FVG
                opens[79]  = base - 0.5
                highs[79]  = base - 0.4
                lows[79]   = base - 0.6

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=times_utc,
    )


class TestIctSessionSweepLong:
    def test_long_signal_fires(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "long"
        assert result["strategy"] == "ict_session_sweep"

    def test_long_sl_below_entry(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["suggested_stop_loss"] < result["entry_price"]

    def test_long_tp_above_entry(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["suggested_take_profit"] > result["entry_price"]

    def test_long_sl_near_sweep_wick(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        # SL should be below the sweep low (98.7), within ATR buffer distance
        assert result["suggested_stop_loss"] < 99.0   # below session low

    def test_long_signal_schema(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["pair"] == "BTC/USDT:USDT"
        assert result["entry_price"] > 0
        assert "fired_at" in result
        assert "regime" in result


class TestIctSessionSweepShort:
    def test_short_signal_fires(self):
        df = _make_ict_df(direction="short")
        regime = _make_regime("trending-down")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["direction"] == "short"
        assert result["strategy"] == "ict_session_sweep"

    def test_short_sl_above_entry(self):
        df = _make_ict_df(direction="short")
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["suggested_stop_loss"] > result["entry_price"]

    def test_short_tp_below_entry(self):
        df = _make_ict_df(direction="short")
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert result["suggested_take_profit"] < result["entry_price"]

    def test_short_sl_near_sweep_wick(self):
        df = _make_ict_df(direction="short")
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is not None
        # SL should be above the sweep high (101.3)
        assert result["suggested_stop_loss"] > 101.0  # above session high


class TestIctSessionSweepBlocking:
    def test_no_signal_outside_killzone(self):
        df = _make_ict_df(direction="long", in_killzone=False)
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_high_volatility(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("high-volatility")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_without_sweep(self):
        df = _make_ict_df(direction="long", has_sweep=False, has_fvg=False)
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_without_fvg(self):
        df = _make_ict_df(direction="long", has_fvg=False)
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_price_outside_fvg(self):
        df = _make_ict_df(direction="long", fvg_price_inside=False)
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_wrong_timeframe(self):
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "1h")
        assert result is None

    def test_fires_for_index_pair_in_killzone(self):
        """Index pair (US500/USD) should use the killzone_hours config, not default."""
        tz_et = ZoneInfo("America/New_York")
        today = pd.Timestamp.now(tz=tz_et).normalize()
        # Build standard long setup — killzone_hours for US500/USD = 09:00-11:00 ET
        df = _make_ict_df(direction="long", in_killzone=True)
        regime = _make_regime("choppy")
        # US500/USD uses the same 09:00-11:00 ET window, so it should fire too
        result = ict_session_sweep("US500/USD", df, regime, "15m")
        # Fires if killzone matches (10:00 ET is inside 09:00-11:00 ET)
        assert result is not None

    def test_fires_across_all_non_high_vol_regimes(self):
        for label in ("trending-up", "trending-down", "choppy"):
            df = _make_ict_df(direction="long")
            regime = _make_regime(label)
            result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
            assert result is not None, f"Expected signal in {label} regime"


class TestIctSessionSweepTP:
    def test_tp_uses_session_liquidity_when_rr_in_range(self):
        """When the session high/low gives a reasonable RR, TP should equal session level."""
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        # session_high = 101.0; entry ≈ 99.65; stop ≈ 98.66
        # risk ≈ 0.99; reward to target ≈ 1.35; RR ≈ 1.36 → inside [0.5, 4.0] → use target
        assert abs(result["suggested_take_profit"] - 101.0) < 0.01

    def test_short_tp_uses_session_liquidity(self):
        df = _make_ict_df(direction="short")
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is not None
        # session_low = 99.0; entry ≈ 100.35; stop ≈ 101.34
        # risk ≈ 0.99; reward to target ≈ 1.35; RR ≈ 1.36 → inside [0.5, 4.0] → use target
        assert abs(result["suggested_take_profit"] - 99.0) < 0.01


class TestIctSessionSweepFVGQuality:
    def test_no_signal_bearish_impulse_for_long(self):
        """BISI filter: a down-close c1 on a long setup must be rejected."""
        df = _make_ict_df(direction="long")
        # Flip c1 (idx 77) to bearish: close below open
        df.iloc[77, df.columns.get_loc("close")] = df.iloc[77]["open"] - 0.1
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_bullish_impulse_for_short(self):
        """SIBI filter: an up-close c1 on a short setup must be rejected."""
        df = _make_ict_df(direction="short")
        # Flip c1 (idx 77) to bullish: close above open
        df.iloc[77, df.columns.get_loc("close")] = df.iloc[77]["open"] + 0.1
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_signal_contains_fvg_ce(self):
        """Signal dict must include fvg_ce (Consequent Encroachment = FVG midpoint)."""
        df = _make_ict_df(direction="long")
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert "fvg_ce" in result
        # Long FVG: [fvg_bottom=99.5, fvg_top=99.8] → CE = 99.65
        assert abs(result["fvg_ce"] - 99.65) < 0.001

    def test_no_signal_close_below_ce_for_long(self):
        """CE half-split: close in lower half of BISI must be rejected (breakaway gap absent)."""
        df = _make_ict_df(direction="long")
        # Move close to 99.60 — inside FVG [99.5, 99.8] but below CE (99.65)
        df.iloc[79, df.columns.get_loc("close")] = 99.60
        df.iloc[79, df.columns.get_loc("open")]  = 99.60
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_no_signal_close_above_ce_for_short(self):
        """CE half-split: close in upper half of SIBI must be rejected (breakaway gap absent)."""
        df = _make_ict_df(direction="short")
        # Move close to 100.40 — inside FVG [100.2, 100.5] but above CE (100.35)
        df.iloc[79, df.columns.get_loc("close")] = 100.40
        df.iloc[79, df.columns.get_loc("open")]  = 100.40
        regime = _make_regime("choppy")
        result = ict_session_sweep("ETH/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_fvg_ce_is_midpoint(self):
        """CE must equal (fvg_top + fvg_bottom) / 2 for both directions."""
        for direction, pair in [("long", "BTC/USDT:USDT"), ("short", "ETH/USDT:USDT")]:
            df = _make_ict_df(direction=direction)
            regime = _make_regime("choppy")
            result = ict_session_sweep(pair, df, regime, "15m")
            assert result is not None
            # Derive expected CE from the FVG bounds in _make_ict_df:
            # long  FVG: [99.5, 99.8] → CE = 99.65
            # short FVG: [100.2, 100.5] → CE = 100.35
            expected_ce = 99.65 if direction == "long" else 100.35
            assert abs(result["fvg_ce"] - expected_ce) < 0.001


def _set_ndog_gap(df: pd.DataFrame, close_5pm: float, open_6pm: float) -> bool:
    """Inject NDOG prices into the fixture df.  Returns False if the df doesn't span
    the prior weekday's 5PM–6PM ET window (e.g. Monday morning run)."""
    tz_et = ZoneInfo("America/New_York")
    idx_et = df.index.tz_convert(tz_et)
    last_et = idx_et[-1]

    for offset in range(1, 8):
        d = (last_et - pd.Timedelta(days=offset)).normalize()
        if d.dayofweek >= 5:
            continue
        cut5 = d + pd.Timedelta(hours=17)
        cut6 = d + pd.Timedelta(hours=18)
        arr5 = idx_et < cut5
        pre_idxs  = arr5.nonzero()[0] if hasattr(arr5, "nonzero") else arr5.values.nonzero()[0]
        arr6 = (idx_et >= cut6) & (idx_et < cut6 + pd.Timedelta(hours=1))
        post_idxs = arr6.nonzero()[0] if hasattr(arr6, "nonzero") else arr6.values.nonzero()[0]
        if not len(pre_idxs) or not len(post_idxs):
            continue
        df.iloc[pre_idxs[-1], df.columns.get_loc("close")] = close_5pm
        df.iloc[post_idxs[0],  df.columns.get_loc("open")]  = open_6pm
        return True
    return False


class TestIctSessionSweepNDOG:
    def test_ndog_tp_used_for_long_on_index_pair(self):
        """NDOG level nearer than session H/L must be used as TP for index pairs."""
        df = _make_ict_df(direction="long")
        found = _set_ndog_gap(df, close_5pm=99.8, open_6pm=100.2)
        if not found:
            pytest.skip("NDOG candles not in 80-candle window (Monday/weekend run)")
        regime = _make_regime("choppy")
        result = ict_session_sweep("US500/USD", df, regime, "15m")
        assert result is not None
        # NDOG gap [99.8, 100.2]: only high=100.2 clears min_rr=0.5
        # (entry≈99.65, risk≈0.99 → RR=(100.2-99.65)/0.99≈0.56 ✓)
        assert "ndog_tp" in result
        assert abs(result["suggested_take_profit"] - 100.2) < 0.01

    def test_ndog_tp_not_applied_to_crypto(self):
        """NDOG logic must be skipped for crypto pairs; TP falls back to session level."""
        df = _make_ict_df(direction="long")
        _set_ndog_gap(df, close_5pm=99.8, open_6pm=100.2)
        regime = _make_regime("choppy")
        result = ict_session_sweep("BTC/USDT:USDT", df, regime, "15m")
        assert result is not None
        assert "ndog_tp" not in result
        assert abs(result["suggested_take_profit"] - 101.0) < 0.01

    def test_ndog_tp_used_for_short_on_index_pair(self):
        """NDOG level nearer than session low must be used as TP for a short."""
        df = _make_ict_df(direction="short")
        found = _set_ndog_gap(df, close_5pm=100.8, open_6pm=99.8)
        if not found:
            pytest.skip("NDOG candles not in 80-candle window (Monday/weekend run)")
        regime = _make_regime("choppy")
        result = ict_session_sweep("US500/USD", df, regime, "15m")
        assert result is not None
        # NDOG gap [99.8, 100.8]: only low=99.8 clears min_rr=0.5 for a short
        # (entry≈100.35, risk≈0.99 → RR=(100.35-99.8)/0.99≈0.56 ✓)
        assert "ndog_tp" in result
        assert abs(result["suggested_take_profit"] - 99.8) < 0.01

    def test_ndog_falls_back_to_session_when_no_gap_in_range(self):
        """When no NDOG level passes the RR filter, TP must use session level."""
        df = _make_ict_df(direction="long")
        # Default df: close/open at 100.0 → only NDOG level is 100.0
        # RR=(100.0-99.65)/0.99≈0.35 < min_rr=0.5 → no valid NDOG level
        regime = _make_regime("choppy")
        result = ict_session_sweep("US500/USD", df, regime, "15m")
        assert result is not None
        assert "ndog_tp" not in result
        assert abs(result["suggested_take_profit"] - 101.0) < 0.01
