from signals.selector import active_strategies, action_for, REGIME_STRATEGY_MAP

ALL_STRATEGIES = (
    "ema_9_21_crossover", "rsi_divergence", "rsi_extreme", "vol_breakout",
    "supply_demand", "liquidity_grab", "volume_spike", "session_open_breakout",
)


class TestActiveStrategies:
    def test_trending_up_fires_ema_vol_sd_orb(self):
        active = active_strategies("trending-up")
        assert "ema_9_21_crossover" in active
        assert "supply_demand" in active       # trending-only from 2026-05-26 — zone rejection with trend
        assert "session_open_breakout" in active
        assert "vol_breakout" not in active    # backtest: -23.05R, 27% WR — lagging entry
        assert "volume_spike" not in active    # permutation: avg_R=-0.24, consistent negative
        assert "rsi_divergence" not in active
        assert "liquidity_grab" not in active
        assert "rsi_extreme" not in active

    def test_trending_down_fires_ema_vol_rsi_div_sd_orb(self):
        active = active_strategies("trending-down")
        assert "ema_9_21_crossover" in active
        assert "rsi_divergence" in active      # bearish divergence (short) — momentum-confirming
        assert "supply_demand" in active       # supply zone rejection with downtrend
        assert "session_open_breakout" in active
        assert "vol_breakout" not in active    # permutation: avg_R=-0.47, no edge
        assert "rsi_extreme" not in active
        assert "liquidity_grab" not in active

    def test_choppy_fires_rsi_and_liq(self):
        active = active_strategies("choppy")
        assert "rsi_divergence" not in active  # 2026-05-31: both directions unprofitable — changed to SKIP
        assert "liquidity_grab" in active
        assert "rsi_extreme" in active         # ETH A-grade: 59.5% WR, +0.191R (BTC/SOL blocked via skip_strategies_for_pairs)
        assert "supply_demand" not in active   # moved to trending-only 2026-05-26
        assert "ema_9_21_crossover" not in active
        assert "vol_breakout" not in active
        assert "session_open_breakout" not in active  # choppy opens prone to false breakout

    def test_high_vol_fires_breakout_liq_extreme_orb(self):
        active = active_strategies("high-volatility")
        assert "vol_breakout" in active
        assert "rsi_extreme" in active
        assert "liquidity_grab" in active
        assert "session_open_breakout" in active
        assert "supply_demand" not in active   # 17% WR — removed
        assert "ema_9_21_crossover" not in active
        assert "rsi_divergence" not in active

    def test_unknown_regime_returns_empty(self):
        active = active_strategies("unknown-regime")
        assert active == []


class TestActionFor:
    def test_skip_returns_skip(self):
        assert action_for("trending-up", "rsi_divergence") == "SKIP"
        assert action_for("choppy", "ema_9_21_crossover") == "SKIP"
        assert action_for("high-volatility", "ema_9_21_crossover") == "SKIP"
        assert action_for("choppy", "supply_demand") == "SKIP"      # moved to trending-only

    def test_fire_returns_fire(self):
        assert action_for("trending-up", "ema_9_21_crossover") == "FIRE"
        assert action_for("trending-down", "ema_9_21_crossover") == "FIRE"
        assert action_for("high-volatility", "vol_breakout") == "FIRE"
        assert action_for("high-volatility", "liquidity_grab") == "FIRE"
        assert action_for("trending-down", "rsi_divergence") == "FIRE"   # bearish divergence in downtrend
        assert action_for("trending-up", "supply_demand") == "FIRE"      # trending-only S&D
        assert action_for("trending-down", "supply_demand") == "FIRE"    # trending-only S&D
        assert action_for("trending-up", "session_open_breakout") == "FIRE"
        assert action_for("trending-down", "session_open_breakout") == "FIRE"
        assert action_for("high-volatility", "session_open_breakout") == "FIRE"

    def test_unknown_strategy_returns_skip(self):
        for regime in ("trending-up", "trending-down", "choppy", "high-volatility"):
            assert action_for(regime, "nonexistent_strategy") == "SKIP"

    def test_supply_demand_trending_only(self):
        assert action_for("trending-up", "supply_demand") == "FIRE"      # zone rejection with trend
        assert action_for("trending-down", "supply_demand") == "FIRE"    # zone rejection with trend
        assert action_for("choppy", "supply_demand") == "SKIP"           # moved out 2026-05-26
        assert action_for("high-volatility", "supply_demand") == "SKIP"  # 17% WR

    def test_session_open_breakout_regime_map(self):
        assert action_for("trending-up", "session_open_breakout") == "FIRE"
        assert action_for("trending-down", "session_open_breakout") == "FIRE"
        assert action_for("high-volatility", "session_open_breakout") == "FIRE"
        assert action_for("choppy", "session_open_breakout") == "SKIP"


class TestMapCompleteness:
    def test_all_regimes_covered(self):
        regimes = ("trending-up", "trending-down", "choppy", "high-volatility")
        for r in regimes:
            assert r in REGIME_STRATEGY_MAP

    def test_all_strategies_in_each_regime(self):
        for regime, mapping in REGIME_STRATEGY_MAP.items():
            for s in ALL_STRATEGIES:
                assert s in mapping, f"{s} missing from {regime}"

    def test_no_unknown_actions(self):
        valid_actions = {"FIRE", "SKIP"}
        for regime, mapping in REGIME_STRATEGY_MAP.items():
            for strategy, action in mapping.items():
                assert action in valid_actions, f"{regime}/{strategy} has invalid action: {action}"
