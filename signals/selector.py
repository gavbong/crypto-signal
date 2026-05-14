REGIME_STRATEGY_MAP: dict[str, dict[str, str]] = {
    "trending-up": {
        "ema_9_21_crossover": "FIRE",  # LONG only — generator blocks counter-trend SHORTs via regime gate
        "macd_crossover":     "SKIP",  # n=28, net_r=-3.53R, lagging indicator — entries too late into move
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "SKIP",
        "vol_breakout":       "SKIP",  # backtest: -23.05R, 27% WR — lagging entry after breakout already done
        "supply_demand":      "SKIP",  # S/D zones require faster reaction than 15-min polling allows
        "liquidity_grab":     "SKIP",
        "volume_spike":       "FIRE",  # institutional participation on trend continuation
    },
    "trending-down": {
        "ema_9_21_crossover": "FIRE",  # SHORT only — generator blocks counter-trend LONGs via regime gate
        "macd_crossover":     "SKIP",  # crossovers in downtrends produce more whipsaw than uptrends
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "SKIP",
        "vol_breakout":       "FIRE",  # consolidation-then-breakdown continuation
        "supply_demand":      "SKIP",  # S/D zones require faster reaction than 15-min polling allows
        "liquidity_grab":     "SKIP",
        "volume_spike":       "SKIP",  # backtest: -17.45R, 32% WR — trend exhaustion, not participation
    },
    "choppy": {
        "ema_9_21_crossover": "SKIP",
        "macd_crossover":     "SKIP",  # lagging crossover whipsaws in sideways markets
        "rsi_divergence":     "FIRE",  # long only (live: long WR=56%; short WR=35% -11.86R) — see DIRECTION_BLOCK
        "rsi_extreme":        "SKIP",  # WR 37.5% < BE 40%, net_r=-5.28R — false reversals in ranging markets
        "vol_breakout":       "SKIP",
        "supply_demand":      "FIRE",  # 1H zones + approach detection — replaces old zone-entry logic
        "liquidity_grab":     "FIRE",  # both directions (live: long WR=56% +1.09R; short WR=56% +2.13R)
        "volume_spike":       "SKIP",  # spikes in choppy = noise, no trend to ride
    },
    "high-volatility": {
        "ema_9_21_crossover": "SKIP",
        "macd_crossover":     "SKIP",
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "FIRE",  # short only (live: short WR=62% +5.77R; long WR=33% -2.22R) — see DIRECTION_BLOCK
        "vol_breakout":       "FIRE",
        "supply_demand":      "SKIP",  # removed entirely — 17% WR across all regimes
        "liquidity_grab":     "FIRE",
        "volume_spike":       "SKIP",  # high-vol already captures spike energy via vol_breakout
    },
}

# Per-direction blocks applied AFTER REGIME_STRATEGY_MAP says FIRE.
# Format: {regime: {strategy: set_of_blocked_directions}}
# Updated 2026-05-14: live evidence (n=48-51) overrides backtest — all three were backwards.
DIRECTION_BLOCK: dict[str, dict[str, set]] = {
    "choppy": {
        "rsi_divergence": {"short"},  # live: short WR=35% -11.86R | long WR=56% -0.39R
    },
    "high-volatility": {
        "rsi_extreme": {"long"},      # live: short WR=62% +5.77R | long WR=33% -2.22R
    },
}


def active_strategies(regime: str) -> list[str]:
    """Return strategies with FIRE action for this regime."""
    mapping = REGIME_STRATEGY_MAP.get(regime, {})
    return [s for s, action in mapping.items() if action == "FIRE"]


def action_for(regime: str, strategy: str) -> str:
    """Return FIRE | SKIP for a specific regime+strategy pair."""
    return REGIME_STRATEGY_MAP.get(regime, {}).get(strategy, "SKIP")


def is_direction_allowed(regime: str, strategy: str, direction: str) -> bool:
    """Return False if this direction is blocked for this regime+strategy combo."""
    blocked = DIRECTION_BLOCK.get(regime, {}).get(strategy, set())
    return direction not in blocked
