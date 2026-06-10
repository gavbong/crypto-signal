from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from loguru import logger
from typing import NamedTuple

from utils.config import get as cfg


class RegimeResult(NamedTuple):
    label: str            # trending-up | trending-down | choppy | high-volatility
    confidence: float     # 0.0-1.0
    age_candles: int      # consecutive candles holding this label
    stable: bool          # True if last N candles all agree
    flickering: bool = False  # True if regime changed >4 times in last 20 candles


_LABELS = ("trending-up", "trending-down", "choppy", "high-volatility")


def _thresholds_for_pair(pair: str | None) -> tuple[float, float, float]:
    """Return (adx_thresh, slope_thresh, hv_mult) for a pair, using asset_class_profiles overrides."""
    c = cfg()["regime"]
    defaults = (c["adx_trend_threshold"], c["ema_slope_threshold"], c["high_vol_bb_multiplier"])
    if pair is None:
        return defaults
    profiles = cfg().get("asset_class_profiles", {})
    for profile in profiles.values():
        if pair in profile.get("pairs", []):
            return (
                profile.get("adx_trend_threshold", defaults[0]),
                profile.get("ema_slope_threshold", defaults[1]),
                profile.get("high_vol_bb_multiplier", defaults[2]),
            )
    return defaults

_FLICKER_WINDOW = 20   # candles to inspect for regime changes
_FLICKER_MAX    = 4    # max label transitions allowed before flagging as flickering


def _is_flickering(labels: list[str], window: int = _FLICKER_WINDOW,
                   max_transitions: int = _FLICKER_MAX) -> bool:
    """Return True if the label sequence has too many regime changes in the window."""
    recent = [l for l in labels[-window:] if l]
    if len(recent) < 3:
        return False
    transitions = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i - 1])
    return transitions > max_transitions


def _to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts")
    return df.astype(float)


def classify_single(df: pd.DataFrame, pair: str | None = None) -> tuple[str, float]:
    """
    Classify market regime for the most recent candle in df.
    Returns (label, confidence).
    Requires at least 55 rows (EMA50 + warmup).
    Pass pair to use asset_class_profiles thresholds (lower ADX/slope for indices).
    """
    c = cfg()["regime"]

    if len(df) < c["ema_slow"] + 5:
        raise ValueError(f"Insufficient candles: {len(df)} (need {c['ema_slow'] + 5})")

    adx_df = ta.adx(df["high"], df["low"], df["close"], length=c["adx_period"])
    ema_fast = ta.ema(df["close"], length=c["ema_fast"])
    ema_slow = ta.ema(df["close"], length=c["ema_slow"])
    bb = ta.bbands(df["close"], length=c["bb_period"], std=c["bb_std"])

    adx_col = f"ADX_{c['adx_period']}"
    # pandas-ta column names vary by version (e.g. BBB_20_2.0 vs BBB_20_2.0_2.0)
    bb_width_col = next(col for col in bb.columns if col.startswith("BBB_"))

    adx_val = adx_df[adx_col].iloc[-1]
    ema_fast_val = ema_fast.iloc[-1]
    ema_slow_val = ema_slow.iloc[-1]
    bb_width = bb[bb_width_col].iloc[-1]
    bb_width_avg = bb[bb_width_col].rolling(20).mean().iloc[-1]

    # Guard NaN — can happen with very short history
    if pd.isna(adx_val) or pd.isna(ema_fast_val) or pd.isna(ema_slow_val):
        raise ValueError("NaN in indicator values — insufficient history or data gap")

    # 3-candle EMA slope (% change)
    ema_slope = (ema_fast.iloc[-1] - ema_fast.iloc[-4]) / ema_fast.iloc[-4]

    adx_thresh, slope_thresh, hv_mult = _thresholds_for_pair(pair)

    bb_valid = not pd.isna(bb_width) and not pd.isna(bb_width_avg) and bb_width_avg > 0

    # High-volatility has priority — composite: BB excess + EMA divergence
    if bb_valid and bb_width > bb_width_avg * hv_mult:
        # 0 at detection threshold, 1 when BB width doubles the threshold
        bb_score = min((bb_width / bb_width_avg - hv_mult) / hv_mult, 1.0)
        # EMA spread confirms vol is directional, not just noise
        ema_sep = abs(ema_fast_val - ema_slow_val) / ema_slow_val
        ema_score = min(ema_sep / 0.02, 1.0)  # 2% EMA spread = full score
        confidence = 0.7 * bb_score + 0.3 * ema_score
        return "high-volatility", round(confidence, 3)

    # Trending — all three must contribute; barely-trending ADX alone scores low
    if adx_val > adx_thresh:
        # ADX: 0 at threshold, 1 at 2× threshold (50 with default config)
        adx_score = min(adx_val / (2.0 * adx_thresh), 1.0)
        # EMA separation: how committed the spread is relative to price
        ema_sep = abs(ema_fast_val - ema_slow_val) / ema_slow_val
        ema_sep_score = min(ema_sep / 0.03, 1.0)  # 3% spread = full score
        # Slope magnitude: how steep the current momentum is
        slope_score = min(abs(ema_slope) / (slope_thresh * 10), 1.0)

        if ema_slope > slope_thresh and ema_fast_val > ema_slow_val:
            confidence = 0.4 * adx_score + 0.35 * ema_sep_score + 0.25 * slope_score
            return "trending-up", round(confidence, 3)
        if ema_slope < -slope_thresh and ema_fast_val < ema_slow_val:
            confidence = 0.4 * adx_score + 0.35 * ema_sep_score + 0.25 * slope_score
            return "trending-down", round(confidence, 3)

    # Choppy (default) — all three indicators must be sleepy
    adx_score = max(1.0 - adx_val / adx_thresh, 0.0)
    # Tight BB: low volatility supports range-bound
    bb_tight_score = max(1.0 - bb_width / (bb_width_avg * 1.2), 0.0) if bb_valid else 0.5
    # Flat slope: EMA not trending anywhere
    slope_flat_score = max(1.0 - abs(ema_slope) / (slope_thresh * 3), 0.0)
    confidence = 0.5 * adx_score + 0.3 * bb_tight_score + 0.2 * slope_flat_score
    return "choppy", round(confidence, 3)


def classify_series(full_df: pd.DataFrame, pair: str | None = None) -> list[RegimeResult | None]:
    """
    Vectorized regime classification across a full candle DataFrame.
    Computes all indicators once — O(n) instead of O(n²) per-window recalc.
    Returns one RegimeResult (or None if not enough history) per candle.
    Used by backtest to avoid re-running indicator math on every sliding window.
    Pass pair to use asset_class_profiles thresholds (lower ADX/slope for indices).
    """
    c = cfg()["regime"]
    adx_period = c["adx_period"]
    adx_thresh, slope_thresh, hv_mult = _thresholds_for_pair(pair)
    stability_n = c["stability_candles"]
    stability_min = c["stability_min_match"]
    min_idx = c["ema_slow"] + 5

    adx_df = ta.adx(full_df["high"], full_df["low"], full_df["close"], length=adx_period)
    ema_fast_s = ta.ema(full_df["close"], length=c["ema_fast"])
    ema_slow_s = ta.ema(full_df["close"], length=c["ema_slow"])
    bb = ta.bbands(full_df["close"], length=c["bb_period"], std=c["bb_std"])
    adx_col = f"ADX_{adx_period}"
    bb_width_col = next(col for col in bb.columns if col.startswith("BBB_"))
    bb_width_s = bb[bb_width_col]
    bb_width_avg_s = bb_width_s.rolling(20).mean()
    ema_slope_s = (ema_fast_s - ema_fast_s.shift(3)) / ema_fast_s.shift(3)

    n = len(full_df)
    labels: list[str | None] = []
    confs: list[float] = []

    for i in range(n):
        if i < min_idx:
            labels.append(None)
            confs.append(0.0)
            continue
        adx_val = adx_df[adx_col].iloc[i]
        efv = ema_fast_s.iloc[i]
        esv = ema_slow_s.iloc[i]
        bw = bb_width_s.iloc[i]
        bwa = bb_width_avg_s.iloc[i]
        slope = ema_slope_s.iloc[i]
        if pd.isna(adx_val) or pd.isna(efv) or pd.isna(esv):
            labels.append(None)
            confs.append(0.0)
            continue
        bb_valid = not pd.isna(bw) and not pd.isna(bwa) and bwa > 0
        if bb_valid and bw > bwa * hv_mult:
            bb_score = min((bw / bwa - hv_mult) / hv_mult, 1.0)
            ema_sep = abs(efv - esv) / esv
            labels.append("high-volatility")
            confs.append(round(0.7 * bb_score + 0.3 * min(ema_sep / 0.02, 1.0), 3))
        elif adx_val > adx_thresh:
            adx_score = min(adx_val / (2.0 * adx_thresh), 1.0)
            ema_sep = abs(efv - esv) / esv
            ema_sep_score = min(ema_sep / 0.03, 1.0)
            slope_score = min(abs(slope) / (slope_thresh * 10), 1.0)
            if slope > slope_thresh and efv > esv:
                labels.append("trending-up")
                confs.append(round(0.4 * adx_score + 0.35 * ema_sep_score + 0.25 * slope_score, 3))
            elif slope < -slope_thresh and efv < esv:
                labels.append("trending-down")
                confs.append(round(0.4 * adx_score + 0.35 * ema_sep_score + 0.25 * slope_score, 3))
            else:
                adx_s2 = max(1.0 - adx_val / adx_thresh, 0.0)
                bb_tight = max(1.0 - bw / (bwa * 1.2), 0.0) if bb_valid else 0.5
                slope_flat = max(1.0 - abs(slope) / (slope_thresh * 3), 0.0)
                labels.append("choppy")
                confs.append(round(0.5 * adx_s2 + 0.3 * bb_tight + 0.2 * slope_flat, 3))
        else:
            adx_score = max(1.0 - adx_val / adx_thresh, 0.0)
            bb_tight = max(1.0 - bw / (bwa * 1.2), 0.0) if bb_valid else 0.5
            slope_flat = max(1.0 - abs(slope) / (slope_thresh * 3), 0.0)
            labels.append("choppy")
            confs.append(round(0.5 * adx_score + 0.3 * bb_tight + 0.2 * slope_flat, 3))

    # Forward pass for age (O(n) instead of O(n²) per-candle scan-back)
    ages: list[int] = []
    cur_age = 0
    for i in range(n):
        if labels[i] is None or (i > 0 and labels[i] != labels[i - 1]):
            cur_age = 0 if labels[i] is None else 1
        else:
            cur_age += 1
        ages.append(cur_age)

    results: list[RegimeResult | None] = []
    for i in range(n):
        lbl = labels[i]
        if lbl is None:
            results.append(None)
            continue
        recent = [l for l in labels[max(0, i - stability_n + 1):i + 1] if l is not None]
        stable = recent.count(lbl) >= stability_min
        flickering = _is_flickering(labels[:i + 1])
        if flickering:
            stable = False
        results.append(RegimeResult(
            label=lbl, confidence=confs[i], age_candles=ages[i],
            stable=stable, flickering=flickering,
        ))

    return results


def classify(ohlcv: list, pair: str | None = None) -> RegimeResult:
    """
    Full classification with stability check and age count.
    ohlcv: list of [ts_ms, open, high, low, close, volume]
    Pass pair to use asset_class_profiles thresholds (lower ADX/slope for indices).
    """
    c = cfg()["regime"]
    df = _to_df(ohlcv)

    if len(df) < c["ema_slow"] + 5:
        raise ValueError(f"Need at least {c['ema_slow'] + 5} candles, got {len(df)}")

    # Classify each of the last (stability_candles + extra) rows
    stability_n = c["stability_candles"]
    stability_min = c["stability_min_match"]
    lookback = max(stability_n + 5, 20)

    labels: list[str] = []
    for i in range(max(len(df) - lookback, c["ema_slow"] + 5), len(df)):
        try:
            label, _ = classify_single(df.iloc[: i + 1], pair)
            labels.append(label)
        except ValueError:
            labels.append("unknown")

    if not labels:
        raise ValueError("Could not compute any regime labels")

    current_label, current_conf = classify_single(df, pair)

    # Stability: do the last stability_min candles all agree?
    recent = labels[-stability_n:]
    stable = recent.count(current_label) >= stability_min

    # Age: count trailing streak of current_label
    age = 0
    for lbl in reversed(labels):
        if lbl == current_label:
            age += 1
        else:
            break

    flickering = _is_flickering(labels)
    # Flickering overrides stability — regime can't be trusted when it's thrashing
    if flickering:
        stable = False

    logger.debug(
        f"Regime={current_label} conf={current_conf} age={age} stable={stable} "
        f"flickering={flickering} recent={recent}"
    )
    return RegimeResult(
        label=current_label,
        confidence=current_conf,
        age_candles=age,
        stable=stable,
        flickering=flickering,
    )
