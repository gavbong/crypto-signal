"""
Run once to generate synthetic OHLCV fixture data for tests.
Usage: python tests/fixtures/generate_fixtures.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

FIXTURES = Path(__file__).parent
RNG = np.random.default_rng(42)
N = 110  # enough for EMA50 + warmup


def _save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(FIXTURES / name, index=True)
    print(f"Saved {name} ({len(df)} rows)")


def _base_ts():
    return pd.date_range("2025-01-01", periods=N, freq="1h")


def trending_up():
    ts = _base_ts()
    close = 50000.0 + np.cumsum(RNG.normal(50, 20, N))
    close = np.maximum(close, 1000)
    spread = close * 0.002
    df = pd.DataFrame({
        "ts": ts,
        "open": close - RNG.uniform(0, spread),
        "high": close + RNG.uniform(spread * 0.5, spread),
        "low": close - RNG.uniform(spread * 0.5, spread),
        "close": close,
        "volume": RNG.uniform(1000, 3000, N),
    })
    df = df.set_index("ts")
    _save(df, "trending_up_scenario.csv")


def trending_down():
    ts = _base_ts()
    close = 50000.0 - np.cumsum(RNG.normal(50, 20, N))
    close = np.maximum(close, 1000)
    spread = close * 0.002
    df = pd.DataFrame({
        "ts": ts,
        "open": close + RNG.uniform(0, spread),
        "high": close + RNG.uniform(spread * 0.5, spread),
        "low": close - RNG.uniform(spread * 0.5, spread),
        "close": close,
        "volume": RNG.uniform(1000, 3000, N),
    })
    df = df.set_index("ts")
    _save(df, "trending_down_scenario.csv")


def choppy():
    ts = _base_ts()
    # Mean-reverting around 50000 with small noise
    close = 50000 + np.cumsum(RNG.normal(0, 15, N))
    spread = close * 0.001
    df = pd.DataFrame({
        "ts": ts,
        "open": close - RNG.uniform(-spread, spread),
        "high": close + RNG.uniform(0, spread),
        "low": close - RNG.uniform(0, spread),
        "close": close,
        "volume": RNG.uniform(800, 1500, N),
    })
    df = df.set_index("ts")
    _save(df, "choppy_scenario.csv")


def high_volatility():
    ts = _base_ts()
    rng = np.random.default_rng(99)
    close = 50000.0 + np.cumsum(rng.normal(0, 500, N))
    close = np.maximum(close, 1000)
    # Force a clear BB-width expansion in the final 15 candles via a large shock
    shock = rng.choice([-1, 1]) * rng.uniform(3000, 5000, 15).cumsum()
    close[-15:] = close[-15] + shock
    close = np.maximum(close, 1000)
    spread = np.abs(close) * 0.04  # 4% spread — very wide
    df = pd.DataFrame({
        "ts": ts,
        "open": close - rng.uniform(-spread, spread),
        "high": close + rng.uniform(spread * 0.8, spread * 2),
        "low": close - rng.uniform(spread * 0.8, spread * 2),
        "close": close,
        "volume": rng.uniform(5000, 15000, N),
    })
    df = df.set_index("ts")
    _save(df, "high_vol_scenario.csv")


def insufficient_candles():
    ts = pd.date_range("2025-01-01", periods=10, freq="1h")
    close = np.full(10, 50000.0)
    df = pd.DataFrame({
        "ts": ts,
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": np.ones(10) * 1000,
    })
    df = df.set_index("ts")
    _save(df, "insufficient_candles.csv")


def nan_scenario():
    ts = _base_ts()
    close = 50000.0 + np.cumsum(RNG.normal(10, 20, N))
    close = np.maximum(close, 1000)
    spread = close * 0.002
    df = pd.DataFrame({
        "ts": ts,
        "open": close - RNG.uniform(0, spread),
        "high": close + RNG.uniform(0, spread),
        "low": close - RNG.uniform(0, spread),
        "close": close,
        "volume": RNG.uniform(1000, 3000, N),
    })
    # Inject NaN values at rows 40-45
    df.loc[df.index[40:46], ["close", "high", "low"]] = float("nan")
    df = df.set_index("ts") if "ts" in df.columns else df
    _save(df, "nan_scenario.csv")


if __name__ == "__main__":
    trending_up()
    trending_down()
    choppy()
    high_volatility()
    insufficient_candles()
    nan_scenario()
    print("All fixtures generated.")
