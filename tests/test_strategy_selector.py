from signals.selector import active_strategies, action_for, REGIME_STRATEGY_MAP


class TestActiveStrategies:
    def test_trending_up_fires_ema(self):
        active = active_strategies("trending-up")
        assert "ema_crossover" in active
        assert "rsi_divergence" not in active
        assert "vol_breakout" not in active

    def test_trending_down_fires_ema(self):
        active = active_strategies("trending-down")
        assert "ema_crossover" in active
        assert "rsi_divergence" not in active

    def test_choppy_fires_rsi(self):
        active = active_strategies("choppy")
        assert "rsi_divergence" in active
        assert "ema_crossover" not in active
        assert "vol_breakout" not in active

    def test_high_vol_fires_breakout(self):
        active = active_strategies("high-volatility")
        assert "vol_breakout" in active
        assert "ema_crossover" not in active
        assert "rsi_divergence" not in active

    def test_unknown_regime_returns_empty(self):
        active = active_strategies("unknown-regime")
        assert active == []


class TestActionFor:
    def test_volume_spike_always_gate(self):
        for regime in ("trending-up", "trending-down", "choppy", "high-volatility"):
            assert action_for(regime, "volume_spike") == "GATE"

    def test_skip_returns_skip(self):
        assert action_for("trending-up", "rsi_divergence") == "SKIP"
        assert action_for("choppy", "ema_crossover") == "SKIP"
        assert action_for("high-volatility", "ema_crossover") == "SKIP"

    def test_fire_returns_fire(self):
        assert action_for("trending-up", "ema_crossover") == "FIRE"
        assert action_for("trending-down", "ema_crossover") == "FIRE"
        assert action_for("choppy", "rsi_divergence") == "FIRE"
        assert action_for("high-volatility", "vol_breakout") == "FIRE"


class TestMapCompleteness:
    def test_all_regimes_covered(self):
        regimes = ("trending-up", "trending-down", "choppy", "high-volatility")
        for r in regimes:
            assert r in REGIME_STRATEGY_MAP

    def test_all_strategies_in_each_regime(self):
        strategies = ("ema_crossover", "rsi_divergence", "vol_breakout", "volume_spike")
        for regime, mapping in REGIME_STRATEGY_MAP.items():
            for s in strategies:
                assert s in mapping, f"{s} missing from {regime}"
