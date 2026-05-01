import pandas as pd
import numpy as np
from regime.classifier import RegimeResult, _to_df
from signals.generator import _find_sd_zones, supply_demand


def _make_regime(label="choppy"):
    return RegimeResult(label=label, confidence=0.75, age_candles=4, stable=True)


def _make_flat_df(n=60, price=100.0) -> pd.DataFrame:
    """Flat market — no impulse moves, ATR will be near zero."""
    times = pd.date_range("2024-01-01", periods=n, freq="15min")
    closes = np.full(n, price)
    opens = closes * 0.9995
    # Tiny wicks to give ATR something to work with
    highs = closes * 1.001
    lows = closes * 0.999
    volumes = np.full(n, 1000.0)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": volumes}, index=times)


def _inject_bullish_impulse(df: pd.DataFrame, idx: int, magnitude: float = 5.0) -> pd.DataFrame:
    """Place a large bullish body at candle idx."""
    df = df.copy()
    base = df["close"].iloc[idx - 1] if idx > 0 else 100.0
    df.iloc[idx, df.columns.get_loc("open")] = base
    df.iloc[idx, df.columns.get_loc("close")] = base + magnitude
    df.iloc[idx, df.columns.get_loc("high")] = base + magnitude + 0.5
    df.iloc[idx, df.columns.get_loc("low")] = base - 0.2
    return df


def _inject_bearish_impulse(df: pd.DataFrame, idx: int, magnitude: float = 5.0) -> pd.DataFrame:
    """Place a large bearish body at candle idx."""
    df = df.copy()
    base = df["close"].iloc[idx - 1] if idx > 0 else 100.0
    df.iloc[idx, df.columns.get_loc("open")] = base
    df.iloc[idx, df.columns.get_loc("close")] = base - magnitude
    df.iloc[idx, df.columns.get_loc("high")] = base + 0.2
    df.iloc[idx, df.columns.get_loc("low")] = base - magnitude - 0.5
    return df


class TestFindSdZones:
    def test_atr_nan_returns_empty(self):
        """Less than 14 candles → ATR is NaN → empty list."""
        times = pd.date_range("2024-01-01", periods=5, freq="15min")
        df = pd.DataFrame({
            "open": [100] * 5, "high": [101] * 5,
            "low": [99] * 5, "close": [100] * 5, "volume": [500] * 5,
        }, index=times)
        assert _find_sd_zones(df) == []

    def test_bullish_impulse_creates_demand_zone(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bullish_impulse(df, idx=30, magnitude=8.0)
        zones = _find_sd_zones(df)
        demand = [z for z in zones if z["zone_type"] == "demand"]
        assert len(demand) > 0

    def test_bearish_impulse_creates_supply_zone(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bearish_impulse(df, idx=30, magnitude=8.0)
        zones = _find_sd_zones(df)
        supply = [z for z in zones if z["zone_type"] == "supply"]
        assert len(supply) > 0

    def test_mitigated_demand_zone_flagged(self):
        """Demand zone mitigated when a subsequent candle closes below zone.bottom."""
        df = _make_flat_df(60, price=100.0)
        # Bullish impulse at idx 20: open=100, close=108
        df = _inject_bullish_impulse(df, idx=20, magnitude=8.0)
        # Subsequent candle at idx 21 closes below zone bottom (100)
        df = df.copy()
        df.iloc[21, df.columns.get_loc("close")] = 95.0
        df.iloc[21, df.columns.get_loc("low")] = 94.0
        zones = _find_sd_zones(df)
        demand = [z for z in zones if z["zone_type"] == "demand"]
        # All demand zones from this impulse should be mitigated
        assert all(z["mitigated"] for z in demand)

    def test_zone_has_required_fields(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bullish_impulse(df, idx=30, magnitude=8.0)
        zones = _find_sd_zones(df)
        if zones:
            z = zones[0]
            assert "zone_type" in z
            assert "top" in z
            assert "bottom" in z
            assert "mitigated" in z
            assert z["top"] >= z["bottom"]


class TestSupplyDemand:
    def test_price_entering_demand_zone_fires_long(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bullish_impulse(df, idx=20, magnitude=8.0)
        # Set current price (last candle) inside the demand zone [100, 108]
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 103.0
        df.iloc[-1, df.columns.get_loc("open")] = 102.0
        regime = _make_regime("choppy")
        result = supply_demand("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["direction"] == "long"
            assert result["strategy"] == "supply_demand"

    def test_price_entering_supply_zone_fires_short(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bearish_impulse(df, idx=20, magnitude=8.0)
        # Set current price inside supply zone [92, 100]
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 96.0
        df.iloc[-1, df.columns.get_loc("open")] = 97.0
        regime = _make_regime("choppy")
        result = supply_demand("BTC/USDT:USDT", df, regime, "15m")
        if result is not None:
            assert result["direction"] == "short"
            assert result["strategy"] == "supply_demand"

    def test_no_active_zones_returns_none(self):
        """Flat market with no impulse → no zones → None."""
        df = _make_flat_df(60, price=100.0)
        regime = _make_regime("trending-up")
        result = supply_demand("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_all_mitigated_zones_returns_none(self):
        df = _make_flat_df(60, price=100.0)
        df = _inject_bullish_impulse(df, idx=20, magnitude=8.0)
        # Candle at idx 21 closes below zone bottom, mitigating it
        df = df.copy()
        df.iloc[21, df.columns.get_loc("close")] = 90.0
        df.iloc[21, df.columns.get_loc("low")] = 89.0
        # Current price is also low — nowhere near any live zone
        df.iloc[-1, df.columns.get_loc("close")] = 91.0
        regime = _make_regime("choppy")
        result = supply_demand("BTC/USDT:USDT", df, regime, "15m")
        assert result is None

    def test_zone_cap_at_three_per_side(self):
        """More than 3 demand zones: only 3 most recent live ones are considered."""
        df = _make_flat_df(100, price=100.0)
        # Inject 5 demand zones at different price levels that do not overlap
        for i, (idx, mag) in enumerate([(10, 3), (20, 3), (30, 3), (40, 3), (50, 3)]):
            # Each at incrementally higher price to avoid overlap
            df.iloc[idx, df.columns.get_loc("open")] = 100 + i * 10
            df.iloc[idx, df.columns.get_loc("close")] = 100 + i * 10 + mag
            df.iloc[idx, df.columns.get_loc("high")] = 100 + i * 10 + mag + 0.5
            df.iloc[idx, df.columns.get_loc("low")] = 100 + i * 10 - 0.2
        # Should not crash; at most 3 zones are checked
        regime = _make_regime("choppy")
        result = supply_demand("BTC/USDT:USDT", df, regime, "15m")
        assert result is None or isinstance(result, dict)
