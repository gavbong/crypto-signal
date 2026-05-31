REGIME_STRATEGY_MAP: dict[str, dict[str, str]] = {
    "trending-up": {
        "ema_9_21_crossover":    "FIRE",  # LONG only — generator blocks counter-trend SHORTs via regime gate
        "rsi_divergence":        "SKIP",
        "rsi_extreme":           "SKIP",
        "vol_breakout":          "SKIP",  # backtest: -23.05R, 27% WR — lagging entry after breakout already done
        "supply_demand":         "FIRE",  # trending-only from 2026-05-26 — zone rejection with trend; was SKIP (wrong in choppy)
        "liquidity_grab":        "SKIP",
        "volume_spike":          "SKIP",  # permutation 2026-05-26: avg_R=-0.24, p=0.67-0.8 — consistent negative, no edge
        "session_open_breakout": "FIRE",  # ORB: indices only, DJ30/FTSE/DAX, 30-90 min after open
    },
    "trending-down": {
        "ema_9_21_crossover":    "FIRE",  # SHORT only — generator blocks counter-trend LONGs via regime gate
        "rsi_divergence":        "FIRE",  # bearish divergence (short) — momentum-confirming in downtrend; see DIRECTION_BLOCK
        "rsi_extreme":           "SKIP",
        "vol_breakout":          "SKIP",  # permutation 2026-05-26: avg_R=-0.47, p=0.67-1.0 — noise, no edge
        "supply_demand":         "FIRE",  # trending-only from 2026-05-26 — supply zone rejection with downtrend
        "liquidity_grab":        "SKIP",
        "volume_spike":          "SKIP",  # backtest: -17.45R, 32% WR — trend exhaustion, not participation
        "session_open_breakout": "FIRE",  # ORB: indices only, DJ30/FTSE/DAX, 30-90 min after open
    },
    "choppy": {
        "ema_9_21_crossover":    "SKIP",
        "rsi_divergence":        "SKIP",  # both directions unprofitable in choppy (short -11.86R; long -4.37R); was FIRE+DIRECTION_BLOCK(both) — simplified to SKIP
        "rsi_extreme":           "FIRE",  # ETH: A-grade p=0.005 n=79 WR=59.5% +0.191R (200-perm 2026-05-27); BTC/SOL skipped via skip_strategies_for_pairs
        "vol_breakout":          "SKIP",
        "supply_demand":         "SKIP",  # moved to trending-only 2026-05-26 — choppy S&D has no edge (blocked both directions)
        "liquidity_grab":        "FIRE",  # both directions (live: long WR=56% +1.09R; short WR=56% +2.13R)
        "volume_spike":          "SKIP",  # spikes in choppy = noise, no trend to ride
        "session_open_breakout": "SKIP",  # choppy opens prone to false breakout and rapid reversal
    },
    "high-volatility": {
        "ema_9_21_crossover":    "SKIP",
        "rsi_divergence":        "SKIP",
        "rsi_extreme":           "FIRE",  # short only (live: short WR=62% +5.77R; long WR=33% -2.22R) — see DIRECTION_BLOCK
        "vol_breakout":          "FIRE",
        "supply_demand":         "SKIP",  # removed entirely — 17% WR across all regimes
        "liquidity_grab":        "FIRE",
        "volume_spike":          "SKIP",  # high-vol already captures spike energy via vol_breakout
        "session_open_breakout": "FIRE",  # high-vol opens can produce strong clean breakouts
    },
}

# Per-direction blocks applied AFTER REGIME_STRATEGY_MAP says FIRE.
# Format: {regime: {strategy: set_of_blocked_directions}}
# Updated 2026-05-14: live evidence (n=48-51) overrides backtest — all three were backwards.
# Updated 2026-05-19: vol_breakout high-vol short blocked — 0/3 live (0% WR) vs 41.8% BT (42pp gap).
# Updated 2026-05-26: supply_demand removed from choppy entirely (moved to trending-only).
#                     rsi_divergence added to trending-down, long blocked (bearish-div short only).
# Updated 2026-05-31: rsi_divergence choppy changed to SKIP in map; DIRECTION_BLOCK entry removed.
DIRECTION_BLOCK: dict[str, dict[str, set]] = {
    "trending-down": {
        "rsi_divergence": {"long"},  # only bearish divergence shorts; bullish divergence long = counter-trend bounce in downtrend
    },
    "high-volatility": {
        "rsi_extreme": {"long"},      # live: short WR=57% +4.77R | long WR=33% -2.22R
        "vol_breakout": {"short"},    # live: short WR=0% n=3 | BT WR=41.8% — 42pp divergence
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
