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


_LABELS = ("trending-up", "trending-down", "choppy", "high-volatility")


def _to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts")
    return df.astype(float)


def classify_single(df: pd.DataFrame) -> tuple[str, float]:
    """
    Classify market regime for the most recent candle in df.
    Returns (label, confidence).
    Requires at least 55 rows (EMA50 + warmup).
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

    slope_thresh = c["ema_slope_threshold"]
    adx_thresh = c["adx_trend_threshold"]
    hv_mult = c["high_vol_bb_multiplier"]

    # High-volatility has priority
    if not pd.isna(bb_width) and not pd.isna(bb_width_avg) and bb_width_avg > 0:
        if bb_width > bb_width_avg * hv_mult:
            confidence = min(bb_width / (bb_width_avg * hv_mult), 2.0) / 2.0
            return "high-volatility", round(confidence, 3)

    # Trending
    if adx_val > adx_thresh:
        if ema_slope > slope_thresh and ema_fast_val > ema_slow_val:
            confidence = min(adx_val / 50.0, 1.0)
            return "trending-up", round(confidence, 3)
        if ema_slope < -slope_thresh and ema_fast_val < ema_slow_val:
            confidence = min(adx_val / 50.0, 1.0)
            return "trending-down", round(confidence, 3)

    # Choppy (default)
    confidence = 1.0 - min(adx_val / adx_thresh, 1.0)
    return "choppy", round(confidence, 3)


def classify(ohlcv: list) -> RegimeResult:
    """
    Full classification with stability check and age count.
    ohlcv: list of [ts_ms, open, high, low, close, volume]
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
            label, _ = classify_single(df.iloc[: i + 1])
            labels.append(label)
        except ValueError:
            labels.append("unknown")

    if not labels:
        raise ValueError("Could not compute any regime labels")

    current_label, current_conf = classify_single(df)

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

    logger.debug(
        f"Regime={current_label} conf={current_conf} age={age} stable={stable} "
        f"recent={recent}"
    )
    return RegimeResult(
        label=current_label,
        confidence=current_conf,
        age_candles=age,
        stable=stable,
    )
