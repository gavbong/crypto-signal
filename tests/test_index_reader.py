"""Tests for exchanges/index_reader.py"""
import sqlite3
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from exchanges.index_reader import IndexReader, _STALE_SECONDS


# ── Helpers ──────────────────────────────────────────────────────────────────

@contextmanager
def _fake_get_conn(conn):
    """Context manager that yields the provided connection."""
    yield conn


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE index_candles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pair        TEXT NOT NULL,
            timeframe   TEXT NOT NULL,
            ts          INTEGER NOT NULL,
            open        REAL NOT NULL,
            high        REAL NOT NULL,
            low         REAL NOT NULL,
            close       REAL NOT NULL,
            volume      REAL NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pair, timeframe, ts)
        );
    """)
    return conn


def _insert(conn, pair="DJ30/USD", age_seconds=60):
    # DB stores timestamps in milliseconds (post ISSUE-003 migration)
    ts = (int(time.time()) - age_seconds) * 1000
    conn.execute(
        "INSERT OR REPLACE INTO index_candles (pair,timeframe,ts,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (pair, "15m", ts, 34500.0, 34560.0, 34480.0, 34510.0, 1000.0),
    )
    conn.commit()
    return ts


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_fresh_candle_returns_ohlcv():
    conn = _make_db()
    _insert(conn, age_seconds=60)
    reader = IndexReader()
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)):
        result = reader.fetch_ohlcv("DJ30/USD", "15m", limit=10)
    assert result is not None
    assert len(result) == 1
    ts_ms, o, h, l, c, v = result[0]
    assert c == 34510.0
    assert ts_ms > 0


def test_stale_candle_returns_none():
    conn = _make_db()
    _insert(conn, age_seconds=_STALE_SECONDS + 120)
    reader = IndexReader()
    alerts = []
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)), \
         patch("exchanges.index_reader._send_stale_alert", side_effect=lambda p, a: alerts.append(p)):
        result = reader.fetch_ohlcv("DJ30/USD", "15m", limit=10)
    assert result is None
    assert "DJ30/USD" in alerts


def test_missing_pair_returns_none():
    conn = _make_db()
    reader = IndexReader()
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)):
        result = reader.fetch_ohlcv("DAX/USD", "15m", limit=10)
    assert result is None


def test_sqlite_error_returns_none():
    reader = IndexReader()

    @contextmanager
    def bad_conn():
        raise sqlite3.Error("disk I/O error")
        yield  # noqa: unreachable

    with patch("exchanges.index_reader.get_conn", return_value=bad_conn()):
        result = reader.fetch_ohlcv("DJ30/USD", "15m", limit=10)
    assert result is None


def test_fetch_ticker_returns_last_close():
    conn = _make_db()
    _insert(conn, age_seconds=60)
    reader = IndexReader()
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)):
        ticker = reader.fetch_ticker("DJ30/USD")
    assert ticker is not None
    assert ticker["last"] == 34510.0
    assert ticker["high"] == 34560.0
    assert ticker["low"]  == 34480.0
    assert ticker["symbol"] == "DJ30/USD"


def test_fetch_ticker_stale_returns_none():
    conn = _make_db()
    _insert(conn, age_seconds=_STALE_SECONDS + 120)
    reader = IndexReader()
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)), \
         patch("exchanges.index_reader._send_stale_alert"):
        result = reader.fetch_ticker("DJ30/USD")
    assert result is None


def test_since_filters_candles():
    conn = _make_db()
    now = int(time.time())
    # Insert three candles at t-300, t-200, t-100 (ts in ms, post ISSUE-003)
    for age in (300, 200, 100):
        ts = (now - age) * 1000
        conn.execute(
            "INSERT OR REPLACE INTO index_candles (pair,timeframe,ts,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("DJ30/USD", "15m", ts, 100.0, 105.0, 98.0, float(age), 1.0),
        )
    conn.commit()

    reader = IndexReader()
    since_ms = (now - 250) * 1000  # only candles at t-200 and t-100
    with patch("exchanges.index_reader.get_conn", return_value=_fake_get_conn(conn)):
        result = reader.fetch_ohlcv("DJ30/USD", "15m", limit=10, since=since_ms)
    assert result is not None
    assert len(result) == 2
    closes = [r[4] for r in result]
    assert 200.0 in closes
    assert 100.0 in closes
