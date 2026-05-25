"""Tests for is_index_market_open() in utils/market_hours.py."""
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

_MOCK_CFG = {
    "indices": {
        "session_hours": {
            "DJ30/USD":    "09:30-16:00 America/New_York",
            "FTSE100/USD": "08:00-16:30 Europe/London",
            "DAX/USD":     "09:00-17:30 Europe/Berlin",
            "XAU/USD":     "00:01-23:59 UTC",
        }
    }
}


def _call(pair: str, dt: datetime) -> bool:
    from utils.market_hours import is_index_market_open
    with patch("utils.market_hours.cfg", return_value=_MOCK_CFG):
        with patch("utils.market_hours.datetime") as mock_dt:
            mock_dt.now.side_effect = lambda tz: dt.astimezone(tz)
            return is_index_market_open(pair)


# ── Non-index pairs ──────────────────────────────────────────────────────────

def test_crypto_pair_always_open():
    from utils.market_hours import is_index_market_open
    with patch("utils.market_hours.cfg", return_value=_MOCK_CFG):
        assert is_index_market_open("BTC/USDT:USDT") is True


def test_unconfigured_pair_always_open():
    from utils.market_hours import is_index_market_open
    with patch("utils.market_hours.cfg", return_value=_MOCK_CFG):
        assert is_index_market_open("UNKNOWN/USD") is True


# ── Weekend blocking ─────────────────────────────────────────────────────────

def test_saturday_is_closed():
    # 2026-05-23 is a Saturday
    dt = datetime(2026, 5, 23, 12, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is False


def test_sunday_is_closed():
    dt = datetime(2026, 5, 24, 14, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is False


# ── Bank holiday blocking ────────────────────────────────────────────────────

def test_us_memorial_day_closed():
    # 2026-05-25 Memorial Day — DJ30 should be closed even during session hours
    dt = datetime(2026, 5, 25, 12, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is False


def test_uk_spring_bank_holiday_closed():
    # 2026-05-25 Spring Bank Holiday — FTSE100 closed
    dt = datetime(2026, 5, 25, 10, 0, 0, tzinfo=ZoneInfo("Europe/London"))
    assert _call("FTSE100/USD", dt) is False


def test_de_whit_monday_closed():
    # 2026-05-25 Whit Monday — DAX closed
    dt = datetime(2026, 5, 25, 11, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert _call("DAX/USD", dt) is False


def test_xau_open_on_bank_holiday():
    # XAU/USD has no holiday calendar — trades 24/7 except weekends
    dt = datetime(2026, 5, 25, 12, 0, 0, tzinfo=ZoneInfo("UTC"))  # Monday
    assert _call("XAU/USD", dt) is True


# ── DJ30 (09:30–16:00 New York) ──────────────────────────────────────────────

def test_dj30_open_at_1000_ny():
    dt = datetime(2026, 5, 27, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))  # Wednesday
    assert _call("DJ30/USD", dt) is True


def test_dj30_open_at_open_time():
    dt = datetime(2026, 5, 27, 9, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is True


def test_dj30_closed_before_open():
    dt = datetime(2026, 5, 27, 9, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is False


def test_dj30_closed_after_close():
    dt = datetime(2026, 5, 27, 16, 1, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _call("DJ30/USD", dt) is False


# ── XAU (00:01–23:59 UTC) — open all weekday hours ──────────────────────────

def test_xau_open_midnight_utc():
    dt = datetime(2026, 5, 27, 0, 5, 0, tzinfo=ZoneInfo("UTC"))  # Wednesday
    assert _call("XAU/USD", dt) is True


def test_xau_open_noon_utc():
    dt = datetime(2026, 5, 27, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert _call("XAU/USD", dt) is True


def test_xau_closed_saturday():
    dt = datetime(2026, 5, 23, 12, 0, 0, tzinfo=ZoneInfo("UTC"))  # Saturday
    assert _call("XAU/USD", dt) is False
