"""
Tests for copy_trader.py pure functions and SQL edge cases.
No network calls, no scheduler — all DB tests use SQLite in-memory.
"""
import sqlite3
from math import log1p

import pytest

from copy_trader import _composite_score, _pair_to_coin


# ── _composite_score ──────────────────────────────────────────────────────────

class TestCompositeScore:
    def test_all_positive_returns_positive(self):
        score = _composite_score(10_000, 50_000, 20, 0.05)
        assert score > 0.0

    def test_all_zeros_returns_zero(self):
        assert _composite_score(0.0, 0.0, 0, 0.0) == 0.0

    def test_negative_pnl_clamped_to_zero(self):
        score_negative = _composite_score(-50_000, -100_000, 10, 0.02)
        score_zero = _composite_score(0.0, 0.0, 10, 0.02)
        assert score_negative == score_zero

    def test_zero_trade_count_no_division_error(self):
        score = _composite_score(5_000, 20_000, 0, 0.01)
        assert score > 0.0

    def test_roi_percentage_normalised(self):
        """roi_7d=5.0 (percentage form) should equal roi_7d=0.05 (decimal form)."""
        score_pct = _composite_score(10_000, 50_000, 20, 5.0)
        score_dec = _composite_score(10_000, 50_000, 20, 0.05)
        assert score_pct == score_dec

    def test_roi_150_pct_clamped_not_multiplied(self):
        """roi_7d=1.5 (above decimal threshold) must be divided by 100, not kept as-is."""
        score_clamped = _composite_score(0, 0, 0, 1.5)
        # 1.5 / 100 = 0.015 → 0.015*100 = 1.5 for log1p term
        expected = round(0.15 * log1p(1.5), 4)
        assert score_clamped == expected

    def test_roi_exactly_1_treated_as_decimal(self):
        """roi_7d=1.0 is the boundary — not > 1.0, so treated as decimal (100% ROI)."""
        score = _composite_score(0, 0, 0, 1.0)
        expected = round(0.15 * log1p(100.0), 4)
        assert score == expected

    def test_higher_inputs_yield_higher_score(self):
        low = _composite_score(1_000, 5_000, 2, 0.01)
        high = _composite_score(50_000, 200_000, 100, 0.50)
        assert high > low

    def test_score_is_rounded_to_4_decimals(self):
        score = _composite_score(12_345, 67_890, 33, 0.07)
        assert score == round(score, 4)


# ── _pair_to_coin ─────────────────────────────────────────────────────────────

class TestPairToCoin:
    def test_standard_usdt_perp(self):
        assert _pair_to_coin("BTC/USDT:USDT") == "BTC"

    def test_usdc_perp(self):
        assert _pair_to_coin("ETH/USDC:USDC") == "ETH"

    def test_spot(self):
        assert _pair_to_coin("SOL/USDT") == "SOL"

    def test_three_letter_asset(self):
        assert _pair_to_coin("XAU/USDT:USDT") == "XAU"


# ── Correlation SQL edge case (INSTR guard) ───────────────────────────────────

_SCHEMA_MINIMAL = """
CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY,
    pair      TEXT NOT NULL,
    direction TEXT NOT NULL,
    fired_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS copy_positions (
    id             INTEGER PRIMARY KEY,
    trader_wallet  TEXT NOT NULL,
    pair           TEXT NOT NULL,
    direction      TEXT NOT NULL,
    opened_at      TIMESTAMP NOT NULL,
    closed_at      TIMESTAMP
);
"""

_CORRELATION_QUERY = """
SELECT cp.id
FROM copy_positions cp
JOIN signals s
  ON SUBSTR(cp.pair, 1, INSTR(cp.pair, '/') - 1) = SUBSTR(s.pair, 1, INSTR(s.pair, '/') - 1)
 AND cp.direction = s.direction
 AND s.fired_at >= datetime(cp.opened_at, '-4 hours')
 AND s.fired_at <= datetime(cp.opened_at, '+4 hours')
WHERE cp.closed_at IS NULL
  AND INSTR(cp.pair, '/') > 0
"""


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_MINIMAL)
    return conn


class TestCorrelationSQL:
    def test_matching_pair_returns_row(self, mem_db):
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'BTC/USDT:USDT','long','2024-01-01 12:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','BTC/USDT:USDT','long','2024-01-01 11:30:00',NULL)"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 1

    def test_different_direction_no_match(self, mem_db):
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'BTC/USDT:USDT','short','2024-01-01 12:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','BTC/USDT:USDT','long','2024-01-01 11:30:00',NULL)"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 0

    def test_signal_outside_4h_window_no_match(self, mem_db):
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'BTC/USDT:USDT','long','2024-01-01 06:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','BTC/USDT:USDT','long','2024-01-01 12:00:00',NULL)"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 0

    def test_malformed_pair_no_slash_filtered_out(self, mem_db):
        """Pair without '/' → INSTR returns 0 → AND guard removes it, no crash."""
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'BTC/USDT:USDT','long','2024-01-01 12:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','BTC','long','2024-01-01 11:30:00',NULL)"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 0

    def test_closed_position_excluded(self, mem_db):
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'SOL/USDT:USDT','long','2024-01-01 12:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','SOL/USDT:USDT','long','2024-01-01 11:30:00','2024-01-01 13:00:00')"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 0

    def test_cross_asset_no_false_match(self, mem_db):
        """BTC signal must not match ETH position."""
        mem_db.execute(
            "INSERT INTO signals VALUES (1,'BTC/USDT:USDT','long','2024-01-01 12:00:00')"
        )
        mem_db.execute(
            "INSERT INTO copy_positions VALUES (1,'0xabc','ETH/USDT:USDT','long','2024-01-01 11:30:00',NULL)"
        )
        rows = mem_db.execute(_CORRELATION_QUERY).fetchall()
        assert len(rows) == 0
