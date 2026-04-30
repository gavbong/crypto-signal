import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from regime.classifier import classify, classify_single, _to_df


def _mock_df(n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.ones(n) * 100.0
    return pd.DataFrame(
        {"open": close * 0.999, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": np.ones(n) * 1000},
        index=idx,
    )


class TestClassifySingle:
    def test_trending_up(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        label, conf = classify_single(df)
        assert label == "trending-up", f"Expected trending-up, got {label}"
        assert 0.0 < conf <= 1.0

    def test_trending_down(self, trending_down_ohlcv):
        df = _to_df(trending_down_ohlcv)
        label, conf = classify_single(df)
        assert label == "trending-down", f"Expected trending-down, got {label}"
        assert 0.0 < conf <= 1.0

    def test_choppy(self, choppy_ohlcv):
        df = _to_df(choppy_ohlcv)
        label, conf = classify_single(df)
        assert label == "choppy", f"Expected choppy, got {label}"
        assert 0.0 <= conf <= 1.0

    def test_high_volatility(self, high_vol_ohlcv):
        df = _to_df(high_vol_ohlcv)
        label, conf = classify_single(df)
        assert label == "high-volatility", f"Expected high-volatility, got {label}"
        assert 0.0 < conf <= 1.0

    def test_insufficient_candles_raises(self, insufficient_ohlcv):
        df = _to_df(insufficient_ohlcv)
        with pytest.raises(ValueError, match="Insufficient"):
            classify_single(df)

    def test_confidence_range(self, trending_up_ohlcv):
        df = _to_df(trending_up_ohlcv)
        _, conf = classify_single(df)
        assert 0.0 <= conf <= 1.0


class TestClassifyFull:
    def test_returns_named_tuple(self, trending_up_ohlcv):
        result = classify(trending_up_ohlcv)
        assert hasattr(result, "label")
        assert hasattr(result, "confidence")
        assert hasattr(result, "age_candles")
        assert hasattr(result, "stable")

    def test_stability_true_on_stable_trend(self, trending_up_ohlcv):
        result = classify(trending_up_ohlcv)
        # Strongly trending fixture should be stable
        assert result.stable is True

    def test_age_candles_positive(self, trending_up_ohlcv):
        result = classify(trending_up_ohlcv)
        assert result.age_candles >= 1

    def test_stability_raises_on_insufficient(self, insufficient_ohlcv):
        with pytest.raises(ValueError):
            classify(insufficient_ohlcv)

    def test_choppy_fixture(self, choppy_ohlcv):
        result = classify(choppy_ohlcv)
        assert result.label == "choppy"


class TestCompositeConfidenceGaps:
    """Coverage for the new composite confidence scoring paths."""

    def _adx_df(self, val: float, n: int = 60) -> pd.DataFrame:
        return pd.DataFrame({"ADX_14": [val] * n, "DMP_14": [15.0] * n, "DMN_14": [10.0] * n})

    def _bb_df(self, val: float, n: int = 60, col: str = "BBB_20_2.0") -> pd.DataFrame:
        return pd.DataFrame({col: [val] * n})

    def test_adx_trending_but_ema_flat_falls_to_choppy(self):
        """G1: ADX > threshold but slope=0 and fast==slow → neither trending branch fires → choppy."""
        n = 60
        df = _mock_df(n)
        adx_df = self._adx_df(30.0, n)          # ADX=30 > 25 thresh
        ema_flat = pd.Series([100.0] * n)        # fast == slow, slope == 0
        bb_df = self._bb_df(0.02, n)             # constant BB → avg == value → no high-vol

        with patch("regime.classifier.ta.adx", return_value=adx_df), \
             patch("regime.classifier.ta.ema", side_effect=[ema_flat, ema_flat]), \
             patch("regime.classifier.ta.bbands", return_value=bb_df):
            label, conf = classify_single(df)

        assert label == "choppy", f"Expected choppy when slope is flat despite ADX=30, got {label}"
        assert 0.0 <= conf <= 1.0

    def test_choppy_bb_invalid_uses_fallback(self):
        """G2: bb_valid=False (NaN bb_width_avg) → bb_tight_score fallback of 0.5, conf in [0,1]."""
        n = 60
        df = _mock_df(n)
        adx_df = self._adx_df(10.0, n)          # low ADX → choppy
        ema_flat = pd.Series([100.0] * n)
        bb_nan = pd.DataFrame({"BBB_20_2.0": [float("nan")] * n})   # all NaN → bb_valid=False

        with patch("regime.classifier.ta.adx", return_value=adx_df), \
             patch("regime.classifier.ta.ema", side_effect=[ema_flat, ema_flat]), \
             patch("regime.classifier.ta.bbands", return_value=bb_nan):
            label, conf = classify_single(df)

        assert label == "choppy"
        assert 0.0 <= conf <= 1.0

    def test_high_vol_extreme_bb_clamps_at_one(self):
        """G3: bb_width >> threshold → bb_score clamped to 1.0, confidence still ≤ 1.0."""
        n = 60
        df = _mock_df(n)
        adx_df = self._adx_df(15.0, n)
        ema_fast = pd.Series([105.0] * n)
        ema_slow = pd.Series([100.0] * n)
        # bb_width spikes at end: rolling-20 avg ≈ 3.25, last value = 10.0
        # 10.0 > 3.25 * 1.5 = 4.875 → high-vol fires; bb_score = min(1.051, 1.0) = 1.0
        bb_vals = [1.0] * (n - 5) + [10.0] * 5
        bb_df = pd.DataFrame({"BBB_20_2.0": bb_vals})

        with patch("regime.classifier.ta.adx", return_value=adx_df), \
             patch("regime.classifier.ta.ema", side_effect=[ema_fast, ema_slow]), \
             patch("regime.classifier.ta.bbands", return_value=bb_df):
            label, conf = classify_single(df)

        assert label == "high-volatility"
        assert conf <= 1.0
