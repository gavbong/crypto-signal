REGIME_STRATEGY_MAP: dict[str, dict[str, str]] = {
    "trending-up": {
        "ema_crossover": "FIRE",
        "rsi_divergence": "SKIP",
        "rsi_extreme":    "SKIP",
        "vol_breakout":   "SKIP",
        "volume_spike":   "GATE",
    },
    "trending-down": {
        "ema_crossover": "FIRE",
        "rsi_divergence": "SKIP",
        "rsi_extreme":    "SKIP",
        "vol_breakout":   "SKIP",
        "volume_spike":   "GATE",
    },
    "choppy": {
        "ema_crossover": "SKIP",
        "rsi_divergence": "FIRE",
        "rsi_extreme":    "FIRE",
        "vol_breakout":   "SKIP",
        "volume_spike":   "GATE",
    },
    "high-volatility": {
        "ema_crossover": "SKIP",
        "rsi_divergence": "SKIP",
        "rsi_extreme":    "SKIP",
        "vol_breakout":   "SKIP",
        "volume_spike":   "GATE",
    },
}


def active_strategies(regime: str) -> list[str]:
    """Return strategies with FIRE action for this regime."""
    mapping = REGIME_STRATEGY_MAP.get(regime, {})
    return [s for s, action in mapping.items() if action == "FIRE"]


def action_for(regime: str, strategy: str) -> str:
    """Return FIRE | SKIP | GATE for a specific regime+strategy pair."""
    return REGIME_STRATEGY_MAP.get(regime, {}).get(strategy, "SKIP")
