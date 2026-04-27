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


def _calc_stop_loss(df: pd.DataFrame, direction: str) -> Optional[float]:
    c = cfg()["signals"]
    atr = ta.atr(df["high"], df["low"], df["close"], length=c["atr_period"]).iloc[-1]
    if pd.isna(atr):
        return None
    entry = df["close"].iloc[-1]
    mult = c["atr_stop_multiplier"]
    return round(entry - atr * mult, 8) if direction == "long" else round(entry + atr * mult, 8)


def _signal(pair: str, direction: str, strategy: str, regime: RegimeResult,
            df: pd.DataFrame, timeframe: str) -> Optional[dict]:
    entry = df["close"].iloc[-1]
    stop = _calc_stop_loss(df, direction)
    if stop is None:
        logger.warning(f"ATR is NaN for {pair} — skipping stop-loss")
        return None
    return {
        "pair": pair,
        "direction": direction,
        "strategy": strategy,
        "regime": regime.label,
        "regime_confidence": regime.confidence,
        "regime_age_candles": regime.age_candles,
        "entry_price": round(entry, 8),
        "suggested_stop_loss": stop,
        "timeframe": timeframe,
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "shadow_mode": True,
    }


def ema_crossover(pair: str, df: pd.DataFrame, regime: RegimeResult,
                  timeframe: str) -> Optional[dict]:
    c = cfg()["signals"]
    ema_fast = ta.ema(df["close"], length=cfg()["regime"]["ema_fast"])
    ema_slow = ta.ema(df["close"], length=cfg()["regime"]["ema_slow"])

    if len(ema_fast) < 2 or pd.isna(ema_fast.iloc[-2]):
        return None

    prev_fast, curr_fast = ema_fast.iloc[-2], ema_fast.iloc[-1]
    prev_slow, curr_slow = ema_slow.iloc[-2], ema_slow.iloc[-1]

    if any(pd.isna(v) for v in [prev_fast, curr_fast, prev_slow, curr_slow]):
        return None

    if not _volume_gate_passes(df):
        return None

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return _signal(pair, "long", "ema_crossover", regime, df, timeframe)
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return _signal(pair, "short", "ema_crossover", regime, df, timeframe)
    return None


def rsi_divergence(pair: str, df: pd.DataFrame, regime: RegimeResult,
                   timeframe: str) -> Optional[dict]:
    c = cfg()["signals"]
    rsi = ta.rsi(df["close"], length=c["rsi_period"])
    lookback = c["rsi_divergence_lookback"]

    if len(rsi) < lookback or rsi.iloc[-lookback:].isna().any():
        return None

    if not _volume_gate_passes(df):
        return None

    closes = df["close"].iloc[-lookback:]
    rsi_vals = rsi.iloc[-lookback:]

    price_low_idx = closes.idxmin()
    price_high_idx = closes.idxmax()

    # Bullish divergence: price new low but RSI higher low vs prior local low
    if closes.iloc[-1] <= closes.min() * 1.002:  # price at/near recent low
        prior_low_rsi = rsi_vals.iloc[: -2].min() if len(rsi_vals) > 2 else None
        if prior_low_rsi is not None and rsi_vals.iloc[-1] > prior_low_rsi * 1.02:
            return _signal(pair, "long", "rsi_divergence", regime, df, timeframe)

    # Bearish divergence: price new high but RSI lower high vs prior local high
    if closes.iloc[-1] >= closes.max() * 0.998:  # price at/near recent high
        prior_high_rsi = rsi_vals.iloc[: -2].max() if len(rsi_vals) > 2 else None
        if prior_high_rsi is not None and rsi_vals.iloc[-1] < prior_high_rsi * 0.98:
            return _signal(pair, "short", "rsi_divergence", regime, df, timeframe)

    return None


def vol_breakout(pair: str, df: pd.DataFrame, regime: RegimeResult,
                 timeframe: str) -> Optional[dict]:
    c = cfg()["regime"]
    bb = ta.bbands(df["close"], length=c["bb_period"], std=c["bb_std"])
    upper_col = next((col for col in bb.columns if col.startswith("BBU_")), None)
    lower_col = next((col for col in bb.columns if col.startswith("BBL_")), None)

    if bb is None or upper_col is None or pd.isna(bb[upper_col].iloc[-1]):
        return None

    if not _volume_gate_passes(df):
        return None

    close = df["close"].iloc[-1]
    if close > bb[upper_col].iloc[-1]:
        return _signal(pair, "long", "vol_breakout", regime, df, timeframe)
    if close < bb[lower_col].iloc[-1]:
        return _signal(pair, "short", "vol_breakout", regime, df, timeframe)
    return None


GENERATORS = {
    "ema_crossover": ema_crossover,
    "rsi_divergence": rsi_divergence,
    "vol_breakout": vol_breakout,
}


def run_strategy(strategy: str, pair: str, df: pd.DataFrame,
                 regime: RegimeResult, timeframe: str) -> Optional[dict]:
    gen = GENERATORS.get(strategy)
    if gen is None:
        logger.warning(f"Unknown strategy: {strategy}")
        return None
    return gen(pair, df, regime, timeframe)
