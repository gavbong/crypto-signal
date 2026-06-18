from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
import pandas_ta as ta
from loguru import logger

from regime.classifier import RegimeResult
from signals.selector import is_direction_allowed
from utils.config import get as cfg


def attach_precomputed(df: pd.DataFrame) -> None:
    """Stamp all indicator series onto df in-place so strategy calls can skip recomputation.

    Call once on the full OHLCV series before the per-candle scan loop. Sliced windows
    inherit these columns automatically, eliminating repeated O(window) TA calls.
    """
    c_sig = cfg()["signals"]
    c_reg = cfg()["regime"]
    atr_period: int = c_sig["atr_period"]
    rsi_period: int = c_sig["rsi_period"]
    vol_period: int = c_sig.get("volume_avg_period", 20)
    bb_period:  int = c_reg["bb_period"]
    bb_std:    float = c_reg["bb_std"]

    df["_atr"] = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
    df["_rsi"] = ta.rsi(df["close"], length=rsi_period)
    df["_ema200"] = ta.ema(df["close"], length=200)
    df["_vol_ma"] = df["volume"].rolling(vol_period).mean()

    bb = ta.bbands(df["close"], length=bb_period, std=bb_std)
    if bb is not None:
        upper_col = next((c for c in bb.columns if c.startswith("BBU_")), None)
        lower_col = next((c for c in bb.columns if c.startswith("BBL_")), None)
        if upper_col and lower_col:
            df["_bbu"] = bb[upper_col]
            df["_bbl"] = bb[lower_col]


def _volume_gate_passes(df: pd.DataFrame) -> bool:
    c = cfg()["signals"]
    avg_vol = (
        df["_vol_ma"].iloc[-1]
        if "_vol_ma" in df.columns
        else df["volume"].rolling(c["volume_avg_period"]).mean().iloc[-1]
    )
    if pd.isna(avg_vol) or avg_vol == 0:
        return False
    return df["volume"].iloc[-1] > avg_vol * c["volume_spike_multiplier"]


def _calc_stop_loss(df: pd.DataFrame, direction: str, regime_label: str = "") -> Optional[float]:
    c = cfg()["signals"]
    atr = (
        df["_atr"].iloc[-1]
        if "_atr" in df.columns
        else ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
    )
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


def _calc_take_profit(entry: float, stop: float, direction: str,
                      regime_label: str = "", strategy: str = "",
                      pair: str = "") -> float:
    risk = abs(entry - stop)
    c = cfg()["signals"]
    full_cfg = cfg()
    rr_map = {
        "choppy":          c.get("rr_ratio_choppy",   c["rr_ratio"]),
        "trending-up":     c.get("rr_ratio_trending",  c["rr_ratio"]),
        "trending-down":   c.get("rr_ratio_trending",  c["rr_ratio"]),
        "high-volatility": c.get("rr_ratio_high_vol",  c["rr_ratio"]),
    }
    rr = rr_map.get(regime_label, c["rr_ratio"])

    # Per-asset-class override: index/CFD instruments move slower than crypto —
    # TP at 2R is rarely reached in the 2-hour outcome window (60-day backtest:
    # only 1/239 TP hits). rr_ratio_index (default 1.2) is more achievable.
    # Checked after regime so the asset-class RR replaces the regime value.
    index_pairs = full_cfg.get("indices", {}).get("pairs", [])
    if pair in index_pairs:
        rr = c.get("rr_ratio_index", 1.2)

    # Per-strategy override (slippage calibration per strategy type).
    strategy_rr = c.get("rr_ratio_strategy", {})
    if strategy and strategy in strategy_rr:
        rr = strategy_rr[strategy]

    # Per-regime-per-strategy override — highest precision (e.g. liq_grab uses 2.5 globally
    # but only 1.5 in choppy where mean-reversion TP rarely reaches 2.5R).
    regime_strat_overrides = c.get("rr_ratio_regime_overrides", {})
    if regime_label and regime_label in regime_strat_overrides:
        if strategy and strategy in regime_strat_overrides[regime_label]:
            rr = regime_strat_overrides[regime_label][strategy]

    is_index = pair in index_pairs
    if c.get("slip_adjust_tp", False) and not is_index:
        # Extend TP so effective RR (after fill costs) equals the target rr.
        # Index CFDs use spread-only pricing at Trade Nation — no order-book gap
        # slippage — so slip_adjust_tp does not apply to index pairs.
        # Net gain at TP (long):  tp - entry*(1+slip) — limit exit, no exit slip
        # Effective loss at SL:   (entry+entry_slip*entry) - (stop-exit_slip*stop)
        #                       = risk + entry*entry_slip + stop*exit_slip
        # Solve: net_gain = rr * effective_loss
        pt = cfg().get("paper_trader", {})
        entry_slip = pt.get("entry_slippage_pct", 0.0005)
        exit_slip  = pt.get("slippage_pct", 0.0052)
        effective_risk = risk + entry * entry_slip + stop * exit_slip
        tp_offset = entry * entry_slip + rr * effective_risk
    else:
        tp_offset = risk * rr

    return round(entry + tp_offset, 8) if direction == "long" else round(entry - tp_offset, 8)


def _signal(pair: str, direction: str, strategy: str, regime: RegimeResult,
            df: pd.DataFrame, timeframe: str) -> Optional[dict]:
    entry = df["close"].iloc[-1]
    stop = _calc_stop_loss(df, direction, regime.label)
    if stop is None:
        logger.warning(f"ATR is NaN for {pair} — skipping stop-loss")
        return None
    take_profit = _calc_take_profit(entry, stop, direction, regime.label, strategy, pair)
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
        if regime.label != "trending-down":  # no counter-trend longs in a downtrend
            return _signal(pair, "long", "ema_9_21_crossover", regime, df, timeframe)
    if prev_fast >= prev_slow and curr_fast < curr_slow and close < curr_fast:
        if regime.label != "trending-up":  # no counter-trend shorts in an uptrend
            return _signal(pair, "short", "ema_9_21_crossover", regime, df, timeframe)
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
    """Find supply/demand zones from impulse candles. Returns zones with mitigation status.

    Applies Doyle's Break-of-Structure (BoS) filter: a demand zone is only valid if its
    impulse candle closed above the prior 10-candle swing high (proving buyers broke
    structure, not just reacted inside a range). Supply zones require the close to be
    below the prior 10-candle swing low. Zones that form during consolidation/ranges are
    excluded — they fail without a structural break behind them.
    """
    c = cfg()["signals"]
    bos_lookback = c.get("sd_bos_lookback", 10)
    atr_series = (
        df["_atr"]
        if "_atr" in df.columns
        else ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"])
    )

    if atr_series is None or pd.isna(atr_series.iloc[-1]):
        return []

    # Pull numpy arrays once to avoid repeated .iloc overhead in inner loops
    import numpy as np
    atr_arr   = atr_series.values
    close_arr = df["close"].values
    open_arr  = df["open"].values
    high_arr  = df["high"].values
    low_arr   = df["low"].values
    impulse_mult = c["sd_impulse_atr_mult"]
    n = len(df) - 1  # last candle is current; scan [0, n-1]

    zones = []
    for i in range(n):
        atr_val = atr_arr[i]
        if atr_val != atr_val or atr_val == 0:  # fast isnan check
            continue
        body = abs(close_arr[i] - open_arr[i])
        if body <= impulse_mult * atr_val:
            continue

        top    = max(open_arr[i], close_arr[i])
        bottom = min(open_arr[i], close_arr[i])
        zone_type = "demand" if close_arr[i] > open_arr[i] else "supply"

        # Break-of-Structure filter
        if i >= bos_lookback:
            lo = max(0, i - bos_lookback)
            if zone_type == "demand":
                if close_arr[i] <= high_arr[lo:i].max():
                    continue
            else:
                if close_arr[i] >= low_arr[lo:i].min():
                    continue

        # Mitigation: vectorized — any future close through the zone boundary
        future_closes = close_arr[i + 1:n]
        if zone_type == "demand":
            mitigated = bool(np.any(future_closes < bottom))
        else:
            mitigated = bool(np.any(future_closes > top))

        zones.append({"zone_type": zone_type, "top": top, "bottom": bottom, "mitigated": mitigated})

    return zones


def _ema200_clears_zone(zone_df: pd.DataFrame, zone: dict) -> bool:
    """Doyle's 200 EMA filter: demand zone must have 200 EMA below it; supply above it.
    Returns True if the zone passes (EMA position is correct or data insufficient)."""
    try:
        if "_ema200" in zone_df.columns:
            ema_val_raw = zone_df["_ema200"].iloc[-1]
            if pd.isna(ema_val_raw):
                return True
            ema_val = ema_val_raw
        else:
            ema_200 = ta.ema(zone_df["close"], length=200)
            if ema_200 is None or pd.isna(ema_200.iloc[-1]):
                return True  # insufficient data — don't filter
            ema_val = ema_200.iloc[-1]
        if zone["zone_type"] == "demand":
            return ema_val <= zone["bottom"]  # EMA must be below zone
        else:
            return ema_val >= zone["top"]     # EMA must be above zone
    except Exception:
        return True


def supply_demand(pair: str, df: pd.DataFrame, regime: RegimeResult,
                  timeframe: str, df_1h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """
    Fires when 15m price is APPROACHING (not inside) a supply/demand zone.
    Uses 1H zones when available — structurally more significant, wider, and price
    respects them longer. Falls back to 15m zones if df_1h is absent.
    Entry triggers when price is within 1.5× ATR of the zone boundary and the last
    3 candles confirm price is moving toward it.

    Doyle filters applied:
    - Break-of-Structure: zones must have formed by breaking prior structure (in _find_sd_zones)
    - 200 EMA position: 200 EMA must be below demand zones / above supply zones
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

    # 200 EMA filter: demand zones need EMA below them; supply zones need EMA above them.
    demand_zones = [z for z in demand_zones if _ema200_clears_zone(zone_df, z)]
    supply_zones = [z for z in supply_zones if _ema200_clears_zone(zone_df, z)]
    if not demand_zones and not supply_zones:
        return None

    # Only trade with the trend in directional regimes
    allow_long  = regime.label != "trending-down"
    allow_short = regime.label != "trending-up"

    curr_low   = df["low"].iloc[-1]
    curr_high  = df["high"].iloc[-1]

    # Zone rejection trigger (Doyle's entry criterion): the current candle wicked into
    # the zone but closed back OUTSIDE it. No candles closing inside the zone is the
    # confirmation that the zone is holding. This replaces the earlier "approach"
    # trigger which fired before the zone was even tested.
    # - Demand: wick dipped into/below zone top, but close printed above zone top.
    # - Supply: wick rose into/above zone bottom, but close printed below zone bottom.
    if allow_long:
        for zone in demand_zones:
            if curr_low <= zone["top"] and close_now >= zone["top"]:
                return _signal(pair, "long", "supply_demand", regime, df, timeframe)

    if allow_short:
        for zone in supply_zones:
            if curr_high >= zone["bottom"] and close_now <= zone["bottom"]:
                return _signal(pair, "short", "supply_demand", regime, df, timeframe)

    return None


def _in_lq_session_window(df: pd.DataFrame, pair: str) -> bool:
    """For index pairs, liquidity grabs are most reliable in the first N hours of the
    session open — the London→NY reversal window Doyle trades. Returns True for crypto
    (no session structure). Returns True on any error (fail-safe)."""
    c = cfg()
    session_hours = c.get("indices", {}).get("session_hours", {})
    spec = session_hours.get(pair)
    if not spec:
        return True  # crypto pair — no session gate

    window_hours = c.get("signals", {}).get("lq_session_window_hours", 4)
    try:
        from zoneinfo import ZoneInfo
        hours_part, tz_str = spec.rsplit(" ", 1)
        start_str = hours_part.split("-")[0]
        ts = df.index[-1]
        tz = ZoneInfo(tz_str)
        if hasattr(ts, "tz_convert"):
            ts_local = ts.tz_convert(tz)
        elif hasattr(ts, "tz_localize") and ts.tzinfo is None:
            ts_local = ts.tz_localize("UTC").tz_convert(tz)
        else:
            ts_local = ts
        session_open = ts_local.replace(
            hour=int(start_str[:2]), minute=int(start_str[3:]),
            second=0, microsecond=0,
        )
        minutes_since_open = (ts_local - session_open).total_seconds() / 60
        return 0 <= minutes_since_open <= window_hours * 60
    except Exception:
        return True


def _lq_zone_confluence(sweep_level: float, sweep_type: str,
                        zone_df: pd.DataFrame, atr: float) -> bool:
    """True when the liquidity sweep level falls at or within an unmitigated S&D zone
    of the matching type. A sweep that undercuts a demand zone (for a long) means the
    same zone that printed the structural move is also the liquidity pool — Doyle's
    highest-conviction combo setup."""
    zones = _find_sd_zones(zone_df)
    if sweep_type == "long":
        target = [z for z in zones if z["zone_type"] == "demand" and not z["mitigated"]]
        return any(z["bottom"] - 2 * atr <= sweep_level <= z["top"] + atr for z in target)
    else:
        target = [z for z in zones if z["zone_type"] == "supply" and not z["mitigated"]]
        return any(z["bottom"] - atr <= sweep_level <= z["top"] + 2 * atr for z in target)


def liquidity_grab(pair: str, df: pd.DataFrame, regime: RegimeResult,
                   timeframe: str, df_1h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """Standard liquidity grab + two Doyle enhancements:
    - Session window: for index pairs, only fire during the first N hours after session
      open (the London→NY reversal period). Config: lq_session_window_hours (default 4).
    - Zone confluence: checks whether the sweep level hit an S&D zone. Result is stored
      in signal["sd_zone_confluence"] for analysis; does not block the signal.
    """
    # Confidence gates — derived from backtest (n=1496 choppy, n=878 high-vol):
    # choppy <0.30: WR=40.8%, avg_r=-0.078 → skip
    # high-vol ≥0.50: WR=43.7%, avg_r=-0.245 → trending move, not reversal → skip
    if regime.label == "choppy" and regime.confidence < 0.30:
        return None
    if regime.label == "high-volatility" and regime.confidence >= 0.50:
        return None

    # Session window gate (indices only)
    if not _in_lq_session_window(df, pair):
        return None

    c = cfg()["signals"]
    if "_atr" in df.columns:
        atr = df["_atr"].iloc[-1]
    else:
        _atr_s = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"])
        atr = _atr_s.iloc[-1] if _atr_s is not None else float("nan")
    if atr is None or pd.isna(atr):
        return None

    prior = df.iloc[:-1]
    if len(prior) < 8:
        return None

    # 30 prior candles (was 20) — captures 7.5h of meaningful liquidity levels at 15min
    swing_window = prior.iloc[-30:]
    swing_low = swing_window["low"].min()
    swing_high = swing_window["high"].max()

    curr = df.iloc[-1]
    zone_df = df_1h if (df_1h is not None and len(df_1h) >= 30) else df

    # Reversal threshold raised from 0.2 → 0.25 ATR — filters weak rejections
    if curr["low"] < swing_low - 0.3 * atr and curr["close"] > swing_low + 0.25 * atr:
        sig = _signal(pair, "long", "liquidity_grab", regime, df, timeframe)
        if sig:
            sig["sd_zone_confluence"] = _lq_zone_confluence(curr["low"], "long", zone_df, atr)
        return sig
    if curr["high"] > swing_high + 0.3 * atr and curr["close"] < swing_high - 0.25 * atr:
        sig = _signal(pair, "short", "liquidity_grab", regime, df, timeframe)
        if sig:
            sig["sd_zone_confluence"] = _lq_zone_confluence(curr["high"], "short", zone_df, atr)
        return sig

    return None


def vol_breakout(pair: str, df: pd.DataFrame, regime: RegimeResult,
                 timeframe: str) -> Optional[dict]:
    if "_bbu" in df.columns and "_bbl" in df.columns:
        upper_s = df["_bbu"]
        lower_s = df["_bbl"]
    else:
        c_regime = cfg()["regime"]
        bb = ta.bbands(df["close"], length=c_regime["bb_period"], std=c_regime["bb_std"])
        upper_col = next((c for c in bb.columns if c.startswith("BBU_")), None)
        lower_col = next((c for c in bb.columns if c.startswith("BBL_")), None)
        if upper_col is None or lower_col is None:
            return None
        upper_s = bb[upper_col]
        lower_s = bb[lower_col]

    upper = upper_s.iloc[-1]
    lower = lower_s.iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return None

    if not _volume_gate_passes(df):
        return None

    # Consolidation precondition: ≥5 of 8 prior candles inside bands
    lookback = 8
    if len(df) < lookback + 1:
        return None

    prior_closes = df["close"].iloc[-lookback - 1:-1]
    prior_upper = upper_s.iloc[-lookback - 1:-1]
    prior_lower = lower_s.iloc[-lookback - 1:-1]

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
    rsi = df["_rsi"] if "_rsi" in df.columns else ta.rsi(df["close"], length=c["rsi_period"])

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

    avg_vol = (
        df["_vol_ma"].iloc[-2]   # iloc[-2] = prev candle avg (same as iloc[-(window+1):-1].mean())
        if "_vol_ma" in df.columns
        else df["volume"].iloc[-(window + 1):-1].mean()
    )
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


def session_open_breakout(pair: str, df: pd.DataFrame, regime: RegimeResult,
                          timeframe: str) -> Optional[dict]:
    """Opening Range Breakout (ORB): first 2 candles (30 min) after session open define
    the range. Fires on candles 3-6 (30-90 min after open) when close breaks the range
    with volume confirmation. SL placed at the far end of the opening range ± 0.5 ATR.

    Applies to equity index pairs with a defined session open (US500, NAS100).
    Pairs trading 24h (XAU/USD, XTI/USD) are excluded — no structural open exists.
    """
    from zoneinfo import ZoneInfo

    _24H_PAIRS = {"XAU/USD", "XTI/USD", "BRENT/USD", "XAUT/USDT:USDT"}
    if timeframe != "15m" or pair in _24H_PAIRS:
        return None

    full_cfg = cfg()
    session_hours = full_cfg.get("indices", {}).get("session_hours", {})
    spec = session_hours.get(pair)
    if not spec:
        return None

    try:
        hours_part, tz_str = spec.rsplit(" ", 1)
        open_str = hours_part.split("-")[0]
        open_hour = int(open_str[:2])
        open_minute = int(open_str[3:])
        tz = ZoneInfo(tz_str)
    except Exception:
        return None

    if df.index.tzinfo is not None:
        idx_local = df.index.tz_convert(tz)
    else:
        idx_local = df.index.tz_localize("UTC").tz_convert(tz)

    last_local = idx_local[-1]
    session_open = last_local.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
    range_end = session_open + pd.Timedelta(minutes=30)
    breakout_end = session_open + pd.Timedelta(minutes=90)

    if not (range_end <= last_local < breakout_end):
        return None

    range_mask = (idx_local >= session_open) & (idx_local < range_end)
    range_df = df[range_mask]
    if len(range_df) < 2:
        return None

    range_high = range_df["high"].max()
    range_low = range_df["low"].min()

    c = cfg()["signals"]
    window = c.get("volume_avg_period", 20)
    avg_vol = df["volume"].iloc[-(window + 1):-1].mean()
    if pd.isna(avg_vol) or avg_vol == 0:
        return None
    if df["volume"].iloc[-1] < avg_vol * c.get("orb_volume_multiplier", 1.5):
        return None

    atr = (
        df["_atr"].iloc[-1]
        if "_atr" in df.columns
        else ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
    )
    if atr is None or pd.isna(atr):
        return None

    close_now = df["close"].iloc[-1]

    if close_now > range_high:
        sig = _signal(pair, "long", "session_open_breakout", regime, df, timeframe)
        if sig:
            sig["suggested_stop_loss"] = round(range_low - 0.5 * atr, 8)
            sig["suggested_take_profit"] = _calc_take_profit(
                sig["entry_price"], sig["suggested_stop_loss"],
                "long", regime.label, "session_open_breakout", pair,
            )
        return sig

    if close_now < range_low:
        sig = _signal(pair, "short", "session_open_breakout", regime, df, timeframe)
        if sig:
            sig["suggested_stop_loss"] = round(range_high + 0.5 * atr, 8)
            sig["suggested_take_profit"] = _calc_take_profit(
                sig["entry_price"], sig["suggested_stop_loss"],
                "short", regime.label, "session_open_breakout", pair,
            )
        return sig

    return None


def _ict_get_session_bounds(df: pd.DataFrame) -> Optional[dict]:
    """Compute combined Asia (20:00–03:00 ET) and London (03:00–09:00 ET) session H/L."""
    from zoneinfo import ZoneInfo
    try:
        tz_et = ZoneInfo("America/New_York")
        idx_et = (
            df.index.tz_convert(tz_et)
            if df.index.tzinfo is not None
            else df.index.tz_localize("UTC").tz_convert(tz_et)
        )
        last_et = idx_et[-1]
        today = last_et.normalize()
        yesterday = today - pd.Timedelta(days=1)

        asia_start = yesterday + pd.Timedelta(hours=20)
        london_start = today + pd.Timedelta(hours=3)
        london_end = today + pd.Timedelta(hours=9)

        asia_df = df[(idx_et >= asia_start) & (idx_et < london_start)]
        london_df = df[(idx_et >= london_start) & (idx_et < london_end)]

        if len(asia_df) == 0 or len(london_df) == 0:
            return None
        return {
            "combined_high": float(max(asia_df["high"].max(), london_df["high"].max())),
            "combined_low":  float(min(asia_df["low"].min(),  london_df["low"].min())),
        }
    except Exception:
        return None


def _ict_in_killzone(df: pd.DataFrame, pair: str) -> bool:
    """Return True if the current candle is inside the ICT NY killzone for this pair."""
    from zoneinfo import ZoneInfo
    ict_cfg = cfg().get("signals", {}).get("ict_session_sweep", {})
    spec = ict_cfg.get("killzone_hours", {}).get(pair) or \
           ict_cfg.get("killzone_hours", {}).get("default", "09:00-11:00 America/New_York")
    try:
        hours_part, tz_str = spec.rsplit(" ", 1)
        start_str, end_str = hours_part.split("-")
        start_h, start_m = int(start_str[:2]), int(start_str[3:])
        end_h, end_m = int(end_str[:2]), int(end_str[3:])
        tz = ZoneInfo(tz_str)
        idx_local = (
            df.index.tz_convert(tz)
            if df.index.tzinfo is not None
            else df.index.tz_localize("UTC").tz_convert(tz)
        )
        last_local = idx_local[-1]
        kz_start = last_local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        kz_end   = last_local.replace(hour=end_h,   minute=end_m,   second=0, microsecond=0)
        return kz_start <= last_local < kz_end
    except Exception:
        return False


def _ict_find_sweep(df: pd.DataFrame, session_bounds: dict, atr: float) -> Optional[dict]:
    """Scan the last N candles for a wick through the combined session H/L that closes back inside."""
    ict_cfg = cfg().get("signals", {}).get("ict_session_sweep", {})
    body_mult = ict_cfg.get("sweep_body_atr_mult", 1.0)
    lookback  = ict_cfg.get("sweep_lookback_candles", 6)
    combined_high = session_bounds["combined_high"]
    combined_low  = session_bounds["combined_low"]

    for i in range(len(df) - 1, max(len(df) - 1 - lookback, -1), -1):
        row  = df.iloc[i]
        body = abs(float(row["close"]) - float(row["open"]))
        if float(row["high"]) > combined_high and float(row["close"]) < combined_high and body < body_mult * atr:
            return {"direction": "short", "sweep_price": float(row["high"]), "sweep_idx": i}
        if float(row["low"]) < combined_low and float(row["close"]) > combined_low and body < body_mult * atr:
            return {"direction": "long",  "sweep_price": float(row["low"]),  "sweep_idx": i}
    return None


def _ict_find_fvg(df: pd.DataFrame, sweep_idx: int, direction: str) -> Optional[dict]:
    """Find the most recent 3-candle Fair Value Gap at or after sweep_idx where the current close is inside.

    Four ICT quality filters beyond the basic gap check:
    - CHoCH: the FVG's impulse candle (c1) must break the local swing H/L from the N candles
      immediately before the sweep — confirming algorithmic displacement, not just noise.
    - Body confirmation: current candle open must be on the entry side of the gap, ensuring
      price is retracing INTO the FVG (not bubbling up through the bottom on a long, etc.).
    - BISI/SIBI: the impulse candle must close in the direction of the trade (up-close for
      longs = Buy Side Imbalance; down-close for shorts = Sell Side Imbalance).
    - CE half-split: for BISI (long) only fills in the upper half [CE, fvg_top] are accepted;
      for SIBI (short) only fills in the lower half [fvg_bottom, CE]. An upper-half fill on a
      BISI means the lower half is a breakaway gap — algorithmic signature of explosive expansion.

    Returns dict with fvg_top, fvg_bottom, and fvg_ce (Consequent Encroachment = midpoint).
    """
    ict_cfg   = cfg().get("signals", {}).get("ict_session_sweep", {})
    lookback  = ict_cfg.get("fvg_lookback_candles", 8)
    choch_lb  = ict_cfg.get("choch_lookback_candles", 10)
    close_now = float(df["close"].iloc[-1])
    open_now  = float(df["open"].iloc[-1])
    fvg_found = None

    # Local swing reference for CHoCH: H/L in the N candles immediately before the sweep.
    pre_start  = max(0, sweep_idx - choch_lb)
    pre_highs  = df["high"].iloc[pre_start:sweep_idx]
    pre_lows   = df["low"].iloc[pre_start:sweep_idx]
    pre_swing_high = float(pre_highs.max()) if len(pre_highs) > 0 else None
    pre_swing_low  = float(pre_lows.min())  if len(pre_lows)  > 0 else None

    for i in range(sweep_idx, min(len(df) - 2, sweep_idx + lookback)):
        if i + 2 >= len(df):
            break
        c0_h = float(df["high"].iloc[i])
        c0_l = float(df["low"].iloc[i])
        c2_h = float(df["high"].iloc[i + 2])
        c2_l = float(df["low"].iloc[i + 2])
        c1_h     = float(df["high"].iloc[i + 1])
        c1_l     = float(df["low"].iloc[i + 1])
        c1_open  = float(df["open"].iloc[i + 1])
        c1_close = float(df["close"].iloc[i + 1])

        if direction == "long" and c0_h < c2_l and (c0_h + c2_l) / 2 <= close_now <= c2_l:
            # CHoCH: impulse must break above the pre-sweep local swing high.
            if pre_swing_high is not None and c1_h <= pre_swing_high:
                continue
            # Body confirmation: open must be at or above FVG bottom (approaching from above).
            if open_now < c0_h:
                continue
            # BISI: impulse candle must be up-close (Buy Side Imbalance, Sell Side Inefficiency).
            if c1_close <= c1_open:
                continue
            fvg_found = {"fvg_top": c2_l, "fvg_bottom": c0_h,
                         "fvg_ce": round((c2_l + c0_h) / 2, 8)}
        elif direction == "short" and c0_l > c2_h and c2_h <= close_now <= (c2_h + c0_l) / 2:
            # CHoCH: impulse must break below the pre-sweep local swing low.
            if pre_swing_low is not None and c1_l >= pre_swing_low:
                continue
            # Body confirmation: open must be at or below FVG top (approaching from below).
            if open_now > c0_l:
                continue
            # SIBI: impulse candle must be down-close (Sell Side Imbalance, Buy Side Inefficiency).
            if c1_close >= c1_open:
                continue
            fvg_found = {"fvg_top": c0_l, "fvg_bottom": c2_h,
                         "fvg_ce": round((c0_l + c2_h) / 2, 8)}

    return fvg_found


def _ict_find_ndog(df: pd.DataFrame, direction: str, entry: float, risk: float,
                   min_rr: float, max_rr: float) -> Optional[float]:
    """Nearest NDOG or NWOG level in the trade direction within valid RR range.

    NDOG: last-candle-before-5PM-ET close vs first-candle-at-6PM-ET open, Mon–Thu.
          Life cycle: 5 trading days.
    NWOG: Friday 5PM ET close vs Sunday 6PM ET open.  Life cycle: 5 weeks.
    Only called for index pairs; caller is responsible for filtering.
    Returns the nearest level (high, low, or CE midpoint) as a TP price, or None.
    """
    from zoneinfo import ZoneInfo
    try:
        tz_et = ZoneInfo("America/New_York")
        idx_et = (
            df.index.tz_convert(tz_et)
            if df.index.tzinfo is not None
            else df.index.tz_localize("UTC").tz_convert(tz_et)
        )
        last_et = idx_et[-1]
        levels: list[float] = []

        def _gap_levels(a: float, b: float) -> list[float]:
            hi, lo = max(a, b), min(a, b)
            return [hi, (hi + lo) / 2, lo]

        def _pos_before(cutoff) -> Optional[int]:
            arr = idx_et < cutoff
            idxs = arr.nonzero()[0] if hasattr(arr, "nonzero") else arr.values.nonzero()[0]
            return int(idxs[-1]) if len(idxs) else None

        def _pos_at_or_after(cutoff, window_h: float = 1.0) -> Optional[int]:
            arr = (idx_et >= cutoff) & (idx_et < cutoff + pd.Timedelta(hours=window_h))
            idxs = arr.nonzero()[0] if hasattr(arr, "nonzero") else arr.values.nonzero()[0]
            return int(idxs[0]) if len(idxs) else None

        # ── NDOG: last 5 trading days ────────────────────────────────────
        trading_days = 0
        for offset in range(14):
            d = (last_et - pd.Timedelta(days=offset)).normalize()
            if d.dayofweek >= 5:
                continue
            trading_days += 1
            if trading_days > 5:
                break
            pre  = _pos_before(d + pd.Timedelta(hours=17))
            post = _pos_at_or_after(d + pd.Timedelta(hours=18))
            if pre is None or post is None:
                continue
            levels.extend(_gap_levels(
                float(df["close"].iloc[pre]),
                float(df["open"].iloc[post]),
            ))

        # ── NWOG: last 5 Fridays ─────────────────────────────────────────
        fridays = 0
        for offset in range(35):
            d = (last_et - pd.Timedelta(days=offset)).normalize()
            if d.dayofweek != 4:
                continue
            fridays += 1
            if fridays > 5:
                break
            fri_pre  = _pos_before(d + pd.Timedelta(hours=17))
            sun_post = _pos_at_or_after(d + pd.Timedelta(days=2, hours=18))
            if fri_pre is None or sun_post is None:
                continue
            levels.extend(_gap_levels(
                float(df["close"].iloc[fri_pre]),
                float(df["open"].iloc[sun_post]),
            ))

        # ── pick nearest valid TP ────────────────────────────────────────
        valid: list[float] = []
        for lvl in levels:
            if direction == "long" and lvl > entry:
                rr = (lvl - entry) / risk
                if min_rr <= rr <= max_rr:
                    valid.append(lvl)
            elif direction == "short" and lvl < entry:
                rr = (entry - lvl) / risk
                if min_rr <= rr <= max_rr:
                    valid.append(lvl)
        if not valid:
            return None
        return round(min(valid, key=lambda x: abs(x - entry)), 8)
    except Exception:
        return None


def ict_session_sweep(pair: str, df: pd.DataFrame, regime: RegimeResult,
                      timeframe: str) -> Optional[dict]:
    """ICT NY Killzone: Asia/London session liquidity sweep with FVG reversal entry.

    1. TIME GATE  — current candle inside pair-specific NY killzone.
    2. SESSION H/L — Asia (20:00–03:00 ET) and London (03:00–09:00 ET) combined bounds.
    3. SWEEP      — last 6 candles show a wick through the combined H/L that closed back inside.
    4. FVG        — 3-candle Fair Value Gap after the sweep with current close inside the gap.
    5. STOP       — beyond the sweep wick + ATR buffer.
    6. TARGET     — opposing session liquidity; ATR fallback if outside [min_rr, max_rr].
    7. REGIME     — fires in any regime except high-volatility.
    """
    if timeframe != "15m":
        return None
    if regime.label == "high-volatility":
        return None
    if len(df) < 50:
        return None

    c = cfg()["signals"]
    atr = (
        df["_atr"].iloc[-1]
        if "_atr" in df.columns
        else ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
    )
    if atr is None or pd.isna(atr):
        return None

    if not _ict_in_killzone(df, pair):
        return None

    session_bounds = _ict_get_session_bounds(df)
    if session_bounds is None:
        return None

    sweep = _ict_find_sweep(df, session_bounds, atr)
    if sweep is None:
        return None

    fvg = _ict_find_fvg(df, sweep["sweep_idx"], sweep["direction"])
    if fvg is None:
        return None

    direction = sweep["direction"]
    entry     = float(df["close"].iloc[-1])

    ict_cfg    = cfg().get("signals", {}).get("ict_session_sweep", {})
    buf        = ict_cfg.get("stop_atr_buffer", 0.1) * atr
    stop       = round(
        sweep["sweep_price"] - buf if direction == "long" else sweep["sweep_price"] + buf, 8
    )

    if (direction == "long"  and stop >= entry) or \
       (direction == "short" and stop <= entry):
        return None

    risk = abs(entry - stop)
    if risk == 0:
        return None

    sig = _signal(pair, direction, "ict_session_sweep", regime, df, timeframe)
    if sig is None:
        return None

    sig["suggested_stop_loss"] = stop
    sig["fvg_ce"] = fvg["fvg_ce"]

    min_rr = ict_cfg.get("min_rr", 0.5)
    max_rr = ict_cfg.get("max_rr", 4.0)

    # TP priority: NDOG/NWOG > session level > CE > ATR
    full_cfg   = cfg()
    index_pairs = full_cfg.get("indices", {}).get("pairs", [])
    tp_set = False

    # 1. NDOG/NWOG — equity opening gaps act as primary price draws (index pairs only)
    if pair in index_pairs:
        ndog_tp = _ict_find_ndog(df, direction, entry, risk, min_rr, max_rr)
        if ndog_tp is not None:
            sig["suggested_take_profit"] = ndog_tp
            sig["ndog_tp"] = ndog_tp
            tp_set = True

    # 2. Session level (opposing Asia/London H or L)
    if not tp_set:
        if direction == "long":
            target       = session_bounds["combined_high"]
            rr_to_target = (target - entry) / risk
        else:
            target       = session_bounds["combined_low"]
            rr_to_target = (entry - target) / risk
        if min_rr <= rr_to_target <= max_rr:
            sig["suggested_take_profit"] = round(target, 8)
            tp_set = True

    # 3. CE (Consequent Encroachment) — FVG midpoint when session level is out of range
    if not tp_set:
        ce = fvg["fvg_ce"]
        ce_rr = (ce - entry) / risk if direction == "long" else (entry - ce) / risk
        if min_rr <= ce_rr and (
            (direction == "long"  and ce > entry) or
            (direction == "short" and ce < entry)
        ):
            sig["suggested_take_profit"] = ce
            tp_set = True

    # 4. ATR fallback
    if not tp_set:
        sig["suggested_take_profit"] = _calc_take_profit(
            entry, stop, direction, regime.label, "ict_session_sweep", pair
        )

    return sig


def bb_reversion(pair: str, df: pd.DataFrame, regime: RegimeResult,
                 timeframe: str) -> Optional[dict]:
    """Mean-reversion signal: price closed outside a Bollinger Band on the prior
    candle and re-enters on the current candle. RSI confirms the extreme.

    Designed for choppy/ranging markets on index and crypto pairs where price
    overextends then snaps back to value. BB params come from regime config
    (bb_period / bb_std) — same bands already used for regime classification.
    """
    if "_bbu" not in df.columns or "_bbl" not in df.columns or "_rsi" not in df.columns:
        return None
    if len(df) < 3:
        return None

    c = cfg()["signals"]
    prev = df.iloc[-2]
    curr = df.iloc[-1]

    bbu_prev = prev["_bbu"]
    bbl_prev = prev["_bbl"]
    bbu_curr = curr["_bbu"]
    bbl_curr = curr["_bbl"]
    rsi = curr["_rsi"]

    if pd.isna(bbu_prev) or pd.isna(bbl_prev) or pd.isna(bbu_curr) or pd.isna(bbl_curr) or pd.isna(rsi):
        return None

    min_rsi_long  = c.get("bb_reversion_min_rsi_long",  45)
    max_rsi_short = c.get("bb_reversion_max_rsi_short", 55)

    # Bullish reversion: prev close was below lower band, current close back inside
    if prev["close"] < bbl_prev and curr["close"] >= bbl_curr and rsi <= min_rsi_long:
        return _signal(pair, "long", "bb_reversion", regime, df, timeframe)

    # Bearish reversion: prev close was above upper band, current close back inside
    if prev["close"] > bbu_prev and curr["close"] <= bbu_curr and rsi >= max_rsi_short:
        return _signal(pair, "short", "bb_reversion", regime, df, timeframe)

    return None


def momentum_breakout_1h(pair: str, df: pd.DataFrame, regime: RegimeResult,
                         timeframe: str,
                         df_1h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """1H momentum breakout for BTC: fires when the last completed 1H candle closes
    above the N-bar range high (long) or below the N-bar range low (short) with
    volume confirmation. Uses df_1h which is already fetched for regime classification.
    """
    if df_1h is None or len(df_1h) < 5:
        return None

    c = cfg()["signals"]
    lookback = c.get("momentum_breakout_1h_lookback", 20)

    if len(df_1h) < lookback + 2:
        return None

    # df_1h[-1] = most recently closed 1H bar; df_1h[-2] is the one before that.
    # Use [-2] as the breakout trigger bar so we only fire on a completed candle.
    breakout_bar = df_1h.iloc[-2]
    prior = df_1h.iloc[-(lookback + 2):-2]

    range_high = prior["high"].max()
    range_low  = prior["low"].min()
    vol_avg = df_1h["volume"].iloc[-(lookback + 2):-2].mean()

    if pd.isna(range_high) or pd.isna(range_low) or pd.isna(vol_avg) or vol_avg == 0:
        return None

    breakout_vol = breakout_bar["volume"]
    if pd.isna(breakout_vol) or breakout_vol < vol_avg:
        return None

    if breakout_bar["close"] > range_high:
        return _signal(pair, "long", "momentum_breakout_1h", regime, df, timeframe)
    if breakout_bar["close"] < range_low:
        return _signal(pair, "short", "momentum_breakout_1h", regime, df, timeframe)

    return None


def trend_following_4h(pair: str, df: pd.DataFrame, regime: RegimeResult,
                       timeframe: str,
                       df_4h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """4H EMA crossover trend-following for gold (XAU/USD) and oil (XTI/USD).
    EMA9 crossing above EMA21 on the 4H chart = bullish trend entry (long).
    EMA9 crossing below EMA21 = bearish trend entry (short).
    ADX filter ensures there is actual trend momentum before firing.
    """
    if df_4h is None or len(df_4h) < 30:
        return None

    c = cfg()["signals"]
    fast = c.get("trend_4h_ema_fast", 9)
    slow = c.get("trend_4h_ema_slow", 21)
    adx_threshold = c.get("trend_4h_adx_threshold", 20)

    try:
        ema_fast = ta.ema(df_4h["close"], length=fast)
        ema_slow = ta.ema(df_4h["close"], length=slow)
        adx_df   = ta.adx(df_4h["high"], df_4h["low"], df_4h["close"], length=14)
    except Exception:
        return None

    if ema_fast is None or ema_slow is None or adx_df is None:
        return None

    if (pd.isna(ema_fast.iloc[-1]) or pd.isna(ema_fast.iloc[-2]) or
            pd.isna(ema_slow.iloc[-1]) or pd.isna(ema_slow.iloc[-2])):
        return None

    adx_col = next((c for c in adx_df.columns if c.startswith("ADX_")), None)
    if adx_col is None or pd.isna(adx_df[adx_col].iloc[-1]):
        return None
    if adx_df[adx_col].iloc[-1] < adx_threshold:
        return None

    # Crossover detection: prev EMA9 < EMA21 → current EMA9 > EMA21 (golden cross)
    prev_fast, prev_slow = ema_fast.iloc[-2], ema_slow.iloc[-2]
    curr_fast, curr_slow = ema_fast.iloc[-1], ema_slow.iloc[-1]

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return _signal(pair, "long", "trend_following_4h", regime, df, timeframe)
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return _signal(pair, "short", "trend_following_4h", regime, df, timeframe)

    return None


GENERATORS = {
    "ema_9_21_crossover":    ema_9_21_crossover,
    "rsi_divergence":        rsi_divergence,
    "vol_breakout":          vol_breakout,
    "rsi_extreme":           rsi_extreme,
    "supply_demand":         supply_demand,
    "liquidity_grab":        liquidity_grab,
    "volume_spike":          volume_spike,
    "session_open_breakout": session_open_breakout,
    "ict_session_sweep":     ict_session_sweep,
    "bb_reversion":          bb_reversion,
    "momentum_breakout_1h":  momentum_breakout_1h,
    "trend_following_4h":    trend_following_4h,
}


def run_strategy(strategy: str, pair: str, df: pd.DataFrame,
                 regime: RegimeResult, timeframe: str,
                 df_1h: Optional[pd.DataFrame] = None,
                 df_4h: Optional[pd.DataFrame] = None) -> Optional[dict]:
    gen = GENERATORS.get(strategy)
    if gen is None:
        logger.warning(f"Unknown strategy: {strategy}")
        return None
    # Per-pair strategy skip list (config: signals.skip_strategies_for_pairs).
    # Supports both flat lists (all regimes) and regime-keyed dicts:
    #   flat:   pair: [strategy, ...]
    #   regime: pair: {regime_label: [strategy, ...]}
    skip_map = cfg().get("signals", {}).get("skip_strategies_for_pairs", {})
    pair_skip = skip_map.get(pair, [])
    if isinstance(pair_skip, dict):
        if strategy in pair_skip.get(regime.label, []):
            return None
    elif strategy in pair_skip:
        return None
    if strategy in ("supply_demand", "liquidity_grab", "momentum_breakout_1h"):
        signal = gen(pair, df, regime, timeframe, df_1h=df_1h)
    elif strategy == "trend_following_4h":
        signal = gen(pair, df, regime, timeframe, df_4h=df_4h)
    else:
        signal = gen(pair, df, regime, timeframe)
    if signal is not None and not is_direction_allowed(regime.label, strategy, signal["direction"]):
        return None
    return signal
