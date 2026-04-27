import sys
import os
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

# Add project root to sys.path so imports work from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"

# Ensure fixture files exist before tests run
def _require_fixture(name: str) -> Path:
    p = FIXTURES / name
    if not p.exists():
        pytest.skip(f"Fixture not found: {name}. Run: python tests/fixtures/generate_fixtures.py")
    return p


def _load_fixture(name: str) -> list:
    """Load a CSV fixture and convert to CCXT-style OHLCV list."""
    p = _require_fixture(name)
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index)
    result = []
    for ts, row in df.iterrows():
        ts_ms = int(ts.timestamp() * 1000)
        result.append([ts_ms, row["open"], row["high"], row["low"], row["close"], row["volume"]])
    return result


@pytest.fixture
def trending_up_ohlcv():
    return _load_fixture("trending_up_scenario.csv")


@pytest.fixture
def trending_down_ohlcv():
    return _load_fixture("trending_down_scenario.csv")


@pytest.fixture
def choppy_ohlcv():
    return _load_fixture("choppy_scenario.csv")


@pytest.fixture
def high_vol_ohlcv():
    return _load_fixture("high_vol_scenario.csv")


@pytest.fixture
def insufficient_ohlcv():
    return _load_fixture("insufficient_candles.csv")


@pytest.fixture
def tmp_db(tmp_path):
    """Return a fresh SQLite DB path for each test."""
    db = tmp_path / "test_signals.db"
    # patch config to use this db path
    import utils.config as config_module
    original = config_module.db_path
    config_module.db_path = lambda: db
    from db.schema import init_db
    init_db(db)
    yield db
    config_module.db_path = original
