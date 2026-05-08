from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
import pandas_ta as ta
from loguru import logger

from regime.classifier import RegimeResult
from utils.config import get as cfg


def _volume_gate_passes(df: pd.DataFrame) -> bool:
    c = cfg()["signals"]
    avg_vol = df["volume"].rolling(c["volume_avg_period"]).mean().iloc[-1]
    if pd.isna(avg_vol) or avg_vol == 0:
        return False
    return df["volume"].iloc[-1] > avg_vol * c["volume_spike_multiplier"]


def _calc_stop_loss(df: pd.DataFrame, direction: str, regime_label: str = "") -> Optional[float]:
    c = cfg()["signals"]
    atr = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
    if pd.isna(atr):
        return None
    entry = df["close"].iloc[-1]
    if regime_label == "high-volatility":
        mult = c["atr_stop_multiplier_high_vol"]
    elif regime_label == "choppy":
        mult = c["atr_stop_multiplier_choppy"]
    else:
        mult = c["atr_stop_multiplier"]
    return round(entry - atr * mult, 8) if direction == "long" else round(entry + atr * mult, 8)


def _calc_take_profit(entry: float, stop: float, direction: str, regime_label: str = "") -> float:
    risk = abs(entry - stop)
    c = cfg()["signals"]
    rr_map = {
        "choppy":       c.get("rr_ratio_choppy",   c["rr_ratio"]),
        "trending-up":  c.get("rr_ratio_trending",  c["rr_ratio"]),
        "trending-down": c.get("rr_ratio_trending", c["rr_ratio"]),
        "high-volatility": c.get("rr_ratio_high_vol", c["rr_ratio"]),
    }
    rr = rr_map.get(regime_label, c["rr_ratio"])
    return round(entry + risk * rr, 8) if direction == "long" else round(entry - risk * rr, 8)


def _signal(pair: str, direction: str, strategy: str, regime: RegimeResult,
            df: pd.DataFrame, timeframe: str) -> Optional[dict]:
    entry = df["close"].iloc[-1]
    stop = _calc_stop_loss(df, direction, regime.label)
    if stop is None:
        logger.warning(f"ATR is NaN for {pair} — skipping stop-loss")
        return None
    take_profit = _calc_take_profit(entry, stop, direction, regime.label)
    return {
        "pair": pair,
        "direction": direction,
        "strategy": strategy,
        "regime": regime.label,
        "regime_confidence": regime.confidence,
        "regime_age_candles": regime.age_candles,
        "entry_price": round(entry, 8),
        "suggested_stop_loss": stop,
        "suggested_take_profit": take_profit,
        "timeframe": timeframe,
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "shadow_mode": True,
    }


def ema_9_21_crossover(pair: str, df: pd.DataFrame, regime: RegimeResult,
                       timeframe: str) -> Optional[dict]:
    c = cfg()["signals"]
    ema_fast = ta.ema(df["close"], length=c["ema_signal_fast"])
    ema_slow = ta.ema(df["close"], length=c["ema_signal_slow"])

    if ema_fast is None or ema_slow is None or len(ema_fast) < 2 or pd.isna(ema_fast.iloc[-2]) or pd.isna(ema_slow.iloc[-2]):
        return None

    prev_fast, curr_fast = ema_fast.iloc[-2], ema_fast.iloc[-1]
    prev_slow, curr_slow = ema_slow.iloc[-2], ema_slow.iloc[-1]

    if any(pd.isna(v) for v in [prev_fast, curr_fast, prev_slow, curr_slow]):
        return None

    close = df["close"].iloc[-1]

    if prev_fast <= prev_slow and curr_fast > curr_slow and close > curr_fast:
        return _signal(pair, "long", "ema_9_21_crossover", regime, df, timeframe)
    if prev_fast >= prev_slow and curr_fast < curr_slow and close < curr_fast:
        return _signal(pair, "short", "ema_9_21_crossover", regime, df, timeframe)
    return None


def macd_crossover(pair: str, df: pd.DataFrame, regime: RegimeResult,
                   timeframe: str) -> Optional[dict]:
    macd_df = ta.macd(df["close"])
    if macd_df is None or len(macd_df) < 2:
        return None

    macd_col = next((c for c in macd_df.columns if c.startswith("MACD_")), None)
    signal_col = next((c for c in macd_df.columns if c.startswith("MACDs_")), None)
    hist_col = next((c for c in macd_df.columns if c.startswith("MACDh_")), None)

    if macd_col is None or signal_col is None or hist_col is None:
        return None

    prev_macd, curr_macd = macd_df[macd_col].iloc[-2], macd_df[macd_col].iloc[-1]
    prev_sig, curr_sig = macd_df[signal_col].iloc[-2], macd_df[signal_col].iloc[-1]
    hist = macd_df[hist_col].iloc[-1]

    if any(pd.isna(v) for v in [prev_macd, curr_macd, prev_sig, curr_sig, hist]):
        return None

    if prev_macd <= prev_sig and curr_macd > curr_sig and hist > 0:
        return _signal(pair, "long", "macd_crossover", regime, df, timeframe)
    if prev_macd >= prev_sig and curr_macd < curr_sig and hist < 0:
        return _signal(pair, "short", "macd_crossover", regime, df, timeframe)
    return None


def rsi_divergence(pair: str, df: pd.DataFrame, regime: RegimeResult,
                   timeframe: str) -> Optional[dict]:
    c = cfg()["signals"]
    rsi = ta.rsi(df["close"], length=c["rsi_period"])
    lookback = c["rsi_divergence_lookback"]

    if len(rsi) < lookback or rsi.iloc[-lookback:].isna().any():
        return None

    closes = df["close"].iloc[-lookback:]
    rsi_vals = rsi.iloc[-lookback:]
    rsi_now = rsi_vals.iloc[-1]

    if closes.iloc[-1] <= closes.min() * 1.001:
        prior_low_rsi = rsi_vals.iloc[:-2].min() if len(rsi_vals) > 2 else None
        if (prior_low_rsi is not None
                and rsi_now > prior_low_rsi + c["rsi_divergence_min_diff"]
                and rsi_now < c["rsi_oversold"]):
            return _signal(pair, "long", "rsi_divergence", regime, df, timeframe)

    if closes.iloc[-1] >= closes.max() * 0.999:
        prior_high_rsi = rsi_vals.iloc[:-2].max() if len(rsi_vals) > 2 else None
        if (prior_high_rsi is not None
                and rsi_now < prior_high_rsi - c["rsi_divergence_min_diff"]
                and rsi_now > c["rsi_overbought"]):
            return _signal(pair, "short", "rsi_divergence", regime, df, timeframe)

    return None


def _find_sd_zones(df: pd.DataFrame) -> list[dict]:
    """Find supply/demand zones from impulse candles. Returns zones with mitigation status."""
    c = cfg()["signals"]
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"])

    if atr_series is None or pd.isna(atr_series.iloc[-1]):
        return []

    zones = []
    for i in range(len(df) - 1):
        atr_val = atr_series.iloc[i]
        if pd.isna(atr_val) or atr_val == 0:
            continue
        row = df.iloc[i]
        body = abs(row["close"] - row["open"])
        if body <= c["sd_impulse_atr_mult"] * atr_val:
            continue

        top = max(row["open"], row["close"])
        bottom = min(row["open"], row["close"])
        zone_type = "demand" if row["close"] > row["open"] else "supply"

        # Zone is mitigated if any subsequent prior candle closes through it
        mitigated = False
        for j in range(i + 1, len(df) - 1):
            close_j = df["close"].iloc[j]
            if zone_type == "demand" and close_j < bottom:
                mitigated = True
                break
            if zone_type == "supply" and close_j > top:
                mitigated = True
                break

        zones.append({"zone_type": zone_type, "top": top, "bottom": bottom, "mitigated": mitigated})

    return zones


def supply_demand(pair: str, df: pd.DataFrame, regime: RegimeResult,
                  timeframe: str, df_1h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """
    Fires when 15m price is APPROACHING (not inside) a supply/demand zone.
    Uses 1H zones when available — structurally more significant, wider, and price
    respects them longer. Falls back to 15m zones if df_1h is absent.
    Entry triggers when price is within 1.5× ATR of the zone boundary and the last
    3 candles confirm price is moving toward it.
    """
    zone_df = df_1h if (df_1h is not None and len(df_1h) >= 30) else df
    zones = _find_sd_zones(zone_df)
    if not zones:
        return None

    demand_zones = [z for z in zones if z["zone_type"] == "demand" and not z["mitigated"]][-3:]
    supply_zones = [z for z in zones if z["zone_type"] == "supply" and not z["mitigated"]][-3:]
    if not demand_zones and not supply_zones:
        return None

    close_now = df["close"].iloc[-1]

    # Cross-check 1H zones against 15m price: if close_now has already breached a zone,
    # the approach logic below will exclude it (close_now > zone["top"] fails for demand),
    # but explicitly filter zones the 1H data missed due to intra-hour 15m moves.
    if zone_df is not df:
        for z in demand_zones:
            if df["close"].iloc[-20:].min() < z["bottom"]:
                z["mitigated"] = True
        for z in supply_zones:
            if df["close"].iloc[-20:].max() > z["top"]:
                z["mitigated"] = True
        demand_zones = [z for z in demand_zones if not z["mitigated"]]
        supply_zones = [z for z in supply_zones if not z["mitigated"]]
        if not demand_zones and not supply_zones:
            return None

    # ATR from zone_df so proximity window matches the scale of the zones.
    # Using 15m ATR against 1H zones made the window 3-5x too narrow.
    c = cfg()["signals"]
    atr_series = ta.atr(zone_df["high"], zone_df["low"], zone_df["close"], length=c["atr_period"])
    atr = atr_series.iloc[-1]
    if pd.isna(atr):
        return None
    proximity = 1.5 * atr

    # Approach direction: count how many of the last 3 closes are falling vs rising
    falling = rising = 0
    if len(df) >= 4:
        recent = df["close"].iloc[-4:-1]
        for i in range(1, len(recent)):
            if recent.iloc[i] < recent.iloc[i - 1]:
                falling += 1
            elif recent.iloc[i] > recent.iloc[i - 1]:
                rising += 1

    # Only trade with the trend in directional regimes
    allow_long  = regime.label != "trending-down"
    allow_short = regime.label != "trending-up"

    if allow_long:
        for zone in demand_zones:
            # Price above zone and falling toward it
            if (close_now > zone["top"]
                    and close_now <= zone["top"] + proximity
                    and falling >= 2):
                return _signal(pair, "long", "supply_demand", regime, df, timeframe)

    if allow_short:
        for zone in supply_zones:
            # Price below zone and rising toward it
            if (close_now < zone["bottom"]
                    and close_now >= zone["bottom"] - proximity
                    and rising >= 2):
                return _signal(pair, "short", "supply_demand", regime, df, timeframe)

    return None


def liquidity_grab(pair: str, df: pd.DataFrame, regime: RegimeResult,
                   timeframe: str) -> Optional[dict]:
    c = cfg()["signals"]
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"])
    if atr_series is None:
        return None
    atr = atr_series.iloc[-1]

    if pd.isna(atr):
        return None

    prior = df.iloc[:-1]
    if len(prior) < 8:
        return None

    # Use last 20 prior candles for swing detection
    swing_window = prior.iloc[-20:]
    swing_low = swing_window["low"].min()
    swing_high = swing_window["high"].max()

    curr = df.iloc[-1]

    if curr["low"] < swing_low - 0.3 * atr and curr["close"] > swing_low + 0.2 * atr:
        return _signal(pair, "long", "liquidity_grab", regime, df, timeframe)
    if curr["high"] > swing_high + 0.3 * atr and curr["close"] < swing_high - 0.2 * atr:
        return _signal(pair, "short", "liquidity_grab", regime, df, timeframe)

    return None


def vol_breakout(pair: str, df: pd.DataFrame, regime: RegimeResult,
                 timeframe: str) -> Optional[dict]:
    c_regime = cfg()["regime"]
    bb = ta.bbands(df["close"], length=c_regime["bb_period"], std=c_regime["bb_std"])
    upper_col = next((c for c in bb.columns if c.startswith("BBU_")), None)
    lower_col = next((c for c in bb.columns if c.startswith("BBL_")), None)

    if upper_col is None or lower_col is None:
        return None

    upper = bb[upper_col].iloc[-1]
    lower = bb[lower_col].iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return None

    if not _volume_gate_passes(df):
        return None

    # Consolidation precondition: ≥5 of 8 prior candles inside bands
    lookback = 8
    if len(df) < lookback + 1:
        return None

    prior_closes = df["close"].iloc[-lookback - 1:-1]
    prior_upper = bb[upper_col].iloc[-lookback - 1:-1]
    prior_lower = bb[lower_col].iloc[-lookback - 1:-1]

    inside_count = sum(
        1 for i in range(len(prior_closes))
        if (not pd.isna(prior_upper.iloc[i]) and not pd.isna(prior_lower.iloc[i])
            and prior_lower.iloc[i] <= prior_closes.iloc[i] <= prior_upper.iloc[i])
    )

    if inside_count < 5:
        return None

    close_now = df["close"].iloc[-1]

    if close_now > upper:
        return _signal(pair, "long", "vol_breakout", regime, df, timeframe)
    if close_now < lower:
        return _signal(pair, "short", "vol_breakout", regime, df, timeframe)
    return None


def rsi_extreme(pair: str, df: pd.DataFrame, regime: RegimeResult,
                timeframe: str) -> Optional[dict]:
    """Fire when RSI exits oversold/overbought territory. No volume gate."""
    c = cfg()["signals"]
    rsi = ta.rsi(df["close"], length=c["rsi_period"])

    if rsi is None or len(rsi) < 2 or pd.isna(rsi.iloc[-1]) or pd.isna(rsi.iloc[-2]):
        return None

    rsi_prev = rsi.iloc[-2]
    rsi_now = rsi.iloc[-1]

    if rsi_prev < c["rsi_extreme_oversold"] and rsi_now >= c["rsi_extreme_oversold"]:
        return _signal(pair, "long", "rsi_extreme", regime, df, timeframe)
    if rsi_prev > c["rsi_extreme_overbought"] and rsi_now <= c["rsi_extreme_overbought"]:
        return _signal(pair, "short", "rsi_extreme", regime, df, timeframe)

    return None


def volume_spike(pair: str, df: pd.DataFrame, regime: RegimeResult,
                 timeframe: str) -> Optional[dict]:
    """Fire when current candle volume is >= N× the rolling average, confirming trend direction.
    Only active in trending regimes — volume spikes in ranging/choppy are noise."""
    c = cfg()["signals"]
    window = c.get("volume_avg_period", 20)
    threshold = c.get("volume_spike_signal_multiplier", 2.0)

    if len(df) < window + 2:
        return None

    avg_vol = df["volume"].iloc[-(window + 1):-1].mean()
    if pd.isna(avg_vol) or avg_vol == 0:
        return None

    current_vol = df["volume"].iloc[-1]
    if current_vol < avg_vol * threshold:
        return None

    curr = df.iloc[-1]
    bullish = curr["close"] > curr["open"]
    bearish = curr["close"] < curr["open"]

    if regime.label == "trending-up" and bullish:
        return _signal(pair, "long", "volume_spike", regime, df, timeframe)
    if regime.label == "trending-down" and bearish:
        return _signal(pair, "short", "volume_spike", regime, df, timeframe)
    return None


GENERATORS = {
    "ema_9_21_crossover": ema_9_21_crossover,
    "macd_crossover":     macd_crossover,
    "rsi_divergence":     rsi_divergence,
    "vol_breakout":       vol_breakout,
    "rsi_extreme":        rsi_extreme,
    "supply_demand":      supply_demand,
    "liquidity_grab":     liquidity_grab,
    "volume_spike":       volume_spike,
}


def run_strategy(strategy: str, pair: str, df: pd.DataFrame,
                 regime: RegimeResult, timeframe: str,
                 df_1h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    gen = GENERATORS.get(strategy)
    if gen is None:
        logger.warning(f"Unknown strategy: {strategy}")
        return None
    if strategy == "supply_demand":
        return gen(pair, df, regime, timeframe, df_1h=df_1h)
    return gen(pair, df, regime, timeframe)
