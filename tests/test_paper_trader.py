"""
Tests for paper_trader.py — 22 cases covering all core paths.
Uses an in-memory SQLite DB so no real signals.db is touched.
"""
import json
import math
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import paper_trader as pt

TEST_PAIR  = "ZEC/USDT:USDT"
OTHER_PAIR = "BTC/USDT:USDT"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    """In-memory SQLite connection with paper tables + signals table initialized."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Create the signals table so poll_new_signals can query it
    c.executescript("""
        CREATE TABLE signals (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            pair                  TEXT NOT NULL,
            direction             TEXT NOT NULL,
            strategy              TEXT NOT NULL,
            regime                TEXT NOT NULL,
            regime_confidence     REAL,
            entry_price           REAL NOT NULL,
            suggested_stop_loss   REAL,
            suggested_take_profit REAL,
            timeframe             TEXT,
            fired_at              TIMESTAMP,
            shadow_mode           INTEGER DEFAULT 0,
            llm_commentary        TEXT,
            commentary_status     TEXT
        );
    """)
    pt.init_paper_db(c)
    yield c
    c.close()


def _signal(conn, direction="long", entry=100.0, stop=95.0, tp=110.0,
            pair=TEST_PAIR) -> dict:
    """Insert a fake signal and return it as a dict."""
    cur = conn.execute(
        """INSERT INTO signals
           (pair, direction, strategy, regime, entry_price,
            suggested_stop_loss, suggested_take_profit, timeframe, fired_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pair, direction, "rsi_extreme", "trending_up", entry, stop, tp,
         "15m", "2026-01-01T00:00:00"),
    )
    conn.commit()
    return {
        "id": cur.lastrowid, "pair": pair, "direction": direction,
        "strategy": "rsi_extreme", "regime": "trending_up",
        "entry_price": entry, "suggested_stop_loss": stop,
        "suggested_take_profit": tp,
    }


def _open_long(conn, entry=100.0, stop=95.0, tp=110.0):
    sig = _signal(conn, "long", entry, stop, tp)
    return pt.open_position(conn, sig, entry)


# ── init_paper_db ─────────────────────────────────────────────────────────────

def test_init_creates_tables(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "paper_positions" in tables
    assert "paper_daily_pnl" in tables
    assert "paper_state" in tables


def test_init_is_idempotent(conn):
    pt.init_paper_db(conn)  # second call must not raise
    assert pt._get_state(conn, "last_signal_id") == "0"


# ── get_free_balance ──────────────────────────────────────────────────────────

def test_free_balance_starts_at_initial(conn):
    assert pt.get_free_balance(conn) == pt.INITIAL_BALANCE


def test_free_balance_deducts_open_margin(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    free = pt.get_free_balance(conn)
    # margin should be deducted
    assert free < pt.INITIAL_BALANCE


def test_free_balance_adds_closed_pnl(conn):
    pos = _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    pt.close_position(conn, pos, 110.0, "take_profit")
    free = pt.get_free_balance(conn)
    # closed pnl added back; no open margin; balance should be > initial (win)
    assert free > pt.INITIAL_BALANCE


# ── open_position ─────────────────────────────────────────────────────────────

def test_open_position_inserts_row(conn):
    sig = _signal(conn, "long", 100.0, 95.0, 110.0)
    pos = pt.open_position(conn, sig, 100.0)
    assert pos is not None
    row = conn.execute(
        "SELECT * FROM paper_positions WHERE id=?", (pos["id"],)
    ).fetchone()
    assert row["direction"] == "long"
    assert row["entry_price"] == 100.0
    min_c = pt.MIN_CONTRACTS.get(TEST_PAIR, pt.DEFAULT_MIN_CONTRACT)
    assert row["contracts"] >= min_c


def test_open_position_skips_duplicate_pair(conn):
    """Second position on the same pair is blocked (one-per-pair rule)."""
    _open_long(conn)
    sig2 = _signal(conn, "long")
    result = pt.open_position(conn, sig2, 100.0)
    assert result is None


def test_open_position_skips_opposite_direction_same_pair(conn):
    """Short on same pair as open long is also blocked (one-per-pair)."""
    _open_long(conn)
    sig_short = _signal(conn, "short", 100.0, 105.0, 90.0, pair=TEST_PAIR)
    result = pt.open_position(conn, sig_short, 100.0)
    assert result is None


def test_open_position_allows_different_pair(conn):
    """Long ZEC open → short BTC on a different pair is allowed."""
    _open_long(conn)
    sig_btc = _signal(conn, "short", 60000.0, 61000.0, 58000.0, pair=OTHER_PAIR)
    result = pt.open_position(conn, sig_btc, 60000.0)
    assert result is not None


def test_open_position_skips_missing_stop(conn):
    sig = _signal(conn)
    sig["suggested_stop_loss"] = None
    result = pt.open_position(conn, sig, 100.0)
    assert result is None


def test_open_position_contracts_floored_to_lot(conn):
    sig = _signal(conn, "long", 100.0, 99.99, 100.01)  # tiny risk per contract
    pos = pt.open_position(conn, sig, 100.0)
    if pos is not None:
        # contracts must be an integer multiple of the pair's min lot size
        min_c = pt.MIN_CONTRACTS.get(TEST_PAIR, pt.DEFAULT_MIN_CONTRACT)
        ratio = pos["contracts"] / min_c
        assert abs(ratio - round(ratio)) < 1e-6


# ── close_position ────────────────────────────────────────────────────────────

def test_close_long_win(conn):
    pos = _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    pnl = pt.close_position(conn, pos, 110.0, "take_profit")
    assert pnl > 0


def test_close_long_loss(conn):
    pos = _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    pnl = pt.close_position(conn, pos, 95.0, "stop_loss")
    assert pnl < 0


def test_close_short_win(conn):
    sig = _signal(conn, "short", 100.0, 105.0, 90.0)
    pos = pt.open_position(conn, sig, 100.0)
    assert pos is not None
    pnl = pt.close_position(conn, pos, 90.0, "take_profit")
    assert pnl > 0


def test_close_short_loss(conn):
    sig = _signal(conn, "short", 100.0, 105.0, 90.0)
    pos = pt.open_position(conn, sig, 100.0)
    pnl = pt.close_position(conn, pos, 105.0, "stop_loss")
    assert pnl < 0


# ── check_positions ───────────────────────────────────────────────────────────

def test_check_positions_closes_long_at_tp(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 111.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 1


def test_check_positions_closes_long_at_sl(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 94.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 1


def test_check_positions_no_close_mid_range(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 102.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 0


def test_check_positions_no_open_positions(conn):
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 100.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 0


# ── poll_new_signals ──────────────────────────────────────────────────────────

def test_poll_new_signals_returns_new(conn):
    _signal(conn)
    signals = pt.poll_new_signals(conn, [TEST_PAIR])
    assert len(signals) == 1
    assert signals[0]["pair"] == TEST_PAIR


def test_poll_new_signals_advances_cursor(conn):
    _signal(conn)
    pt.poll_new_signals(conn, [TEST_PAIR])
    _signal(conn)
    second = pt.poll_new_signals(conn, [TEST_PAIR])
    assert len(second) == 1


def test_poll_new_signals_filters_other_pairs(conn):
    """Signals for pairs not in the watch list are excluded."""
    conn.execute(
        """INSERT INTO signals (pair, direction, strategy, regime, entry_price,
           suggested_stop_loss, suggested_take_profit, timeframe, fired_at)
           VALUES ('XRP/USDT:USDT', 'long', 'rsi_extreme', 'trending_up',
                   0.5, 0.45, 0.55, '15m', '2026-01-01T00:00:00')"""
    )
    conn.commit()
    signals = pt.poll_new_signals(conn, [TEST_PAIR])
    assert signals == []


def test_poll_new_signals_includes_all_configured_pairs(conn):
    """Signals for multiple configured pairs are all returned."""
    _signal(conn, pair=TEST_PAIR)
    _signal(conn, pair=OTHER_PAIR)
    signals = pt.poll_new_signals(conn, [TEST_PAIR, OTHER_PAIR])
    assert len(signals) == 2


# ── snapshot_day ──────────────────────────────────────────────────────────────

def test_snapshot_day_writes_json(conn, tmp_path):
    with patch.object(pt, "LOG_DIR", tmp_path):
        with patch("paper_trader.fetch_ticker_safe", return_value={"last": 100.0}):
            snap = pt.snapshot_day(conn, MagicMock())

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["day"] == 1
    assert data["balance_usdt"] == pt.INITIAL_BALANCE


def test_snapshot_day_increments_day_number(conn, tmp_path):
    with patch.object(pt, "LOG_DIR", tmp_path):
        with patch("paper_trader.fetch_ticker_safe", return_value={"last": 100.0}):
            pt.snapshot_day(conn, MagicMock())
            pt.snapshot_day(conn, MagicMock())
    assert int(pt._get_state(conn, "day_number")) == 2


def test_snapshot_day_win_rate_computed_with_trades(conn, tmp_path):
    pos = _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    pt.close_position(conn, pos, 110.0, "take_profit")
    with patch.object(pt, "LOG_DIR", tmp_path):
        with patch("paper_trader.fetch_ticker_safe", return_value={"last": 110.0}):
            snap = pt.snapshot_day(conn, MagicMock())
    assert snap["wins"] == 1
    assert snap["losses"] == 0
    assert snap["win_rate"] == 1.0


# ── get_unrealized_pnl ────────────────────────────────────────────────────────

def test_get_unrealized_pnl_no_open_positions(conn):
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 100.0}):
        result = pt.get_unrealized_pnl(conn, MagicMock())
    assert result == 0.0


def test_get_unrealized_pnl_ticker_fail(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value=None):
        result = pt.get_unrealized_pnl(conn, MagicMock())
    assert result == 0.0


def test_get_unrealized_pnl_long_position(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 105.0}):
        result = pt.get_unrealized_pnl(conn, MagicMock())
    assert result > 0


def test_get_unrealized_pnl_short_position(conn):
    sig = _signal(conn, "short", 100.0, 105.0, 90.0)
    pt.open_position(conn, sig, 100.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 95.0}):
        result = pt.get_unrealized_pnl(conn, MagicMock())
    assert result > 0


# ── open_position edge cases ──────────────────────────────────────────────────

def test_open_position_skips_zero_risk(conn):
    sig = _signal(conn, "long", 100.0, 100.0, 110.0)  # stop == entry = zero risk
    result = pt.open_position(conn, sig, 100.0)
    assert result is None


def test_open_position_skips_no_free_balance(conn):
    # Exhaust the balance by locking all margin via many open positions
    # Instead, monkey-patch get_free_balance to return 0
    sig = _signal(conn, "long", 100.0, 95.0, 110.0)
    with patch("paper_trader.get_free_balance", return_value=0.0):
        result = pt.open_position(conn, sig, 100.0)
    assert result is None


# ── check_positions short paths ───────────────────────────────────────────────

def _open_short(conn, entry=100.0, stop=105.0, tp=90.0):
    sig = _signal(conn, "short", entry, stop, tp)
    return pt.open_position(conn, sig, entry)


def test_check_positions_closes_short_at_tp(conn):
    _open_short(conn, entry=100.0, stop=105.0, tp=90.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 89.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 1


def test_check_positions_closes_short_at_sl(conn):
    _open_short(conn, entry=100.0, stop=105.0, tp=90.0)
    with patch("paper_trader.fetch_ticker_safe", return_value={"last": 106.0}):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 1


def test_check_positions_ticker_fail_returns_zero(conn):
    _open_long(conn, entry=100.0, stop=95.0, tp=110.0)
    with patch("paper_trader.fetch_ticker_safe", return_value=None):
        closed = pt.check_positions(conn, MagicMock())
    assert closed == 0
