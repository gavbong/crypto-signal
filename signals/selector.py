REGIME_STRATEGY_MAP: dict[str, dict[str, str]] = {
    "trending-up": {
        "ema_9_21_crossover": "FIRE",
        "macd_crossover":     "FIRE",
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "SKIP",
        "vol_breakout":       "FIRE",  # consolidation-then-breakout continuation
        "supply_demand":      "SKIP",  # S/D zones require faster reaction than 15-min polling allows
        "liquidity_grab":     "SKIP",
    },
    "trending-down": {
        "ema_9_21_crossover": "FIRE",
        "macd_crossover":     "SKIP",  # crossovers in downtrends produce more whipsaw than uptrends
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "SKIP",
        "vol_breakout":       "FIRE",  # consolidation-then-breakdown continuation
        "supply_demand":      "SKIP",  # S/D zones require faster reaction than 15-min polling allows
        "liquidity_grab":     "SKIP",
    },
    "choppy": {
        "ema_9_21_crossover": "SKIP",
        "macd_crossover":     "SKIP",  # lagging crossover whipsaws in sideways markets
        "rsi_divergence":     "FIRE",
        "rsi_extreme":        "FIRE",
        "vol_breakout":       "SKIP",
        "supply_demand":      "FIRE",  # 1H zones + approach detection — replaces old zone-entry logic
        "liquidity_grab":     "FIRE",
    },
    "high-volatility": {
        "ema_9_21_crossover": "SKIP",
        "macd_crossover":     "SKIP",
        "rsi_divergence":     "SKIP",
        "rsi_extreme":        "FIRE",
        "vol_breakout":       "FIRE",
        "supply_demand":      "SKIP",  # removed entirely — 17% WR across all regimes
        "liquidity_grab":     "FIRE",
    },
}


def active_strategies(regime: str) -> list[str]:
    """Return strategies with FIRE action for this regime."""
    mapping = REGIME_STRATEGY_MAP.get(regime, {})
    return [s for s, action in mapping.items() if action == "FIRE"]


def action_for(regime: str, strategy: str) -> str:
    """Return FIRE | SKIP for a specific regime+strategy pair."""
    return REGIME_STRATEGY_MAP.get(regime, {}).get(strategy, "SKIP")
