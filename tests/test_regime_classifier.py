import pytest
from regime.classifier import classify, classify_single, _to_df


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
