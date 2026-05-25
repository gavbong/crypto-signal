"""
utils/market_hours.py — Market hours and bank holiday calendar for index pairs.

Shared by signal_engine (skips closed pairs) and index_reader (suppresses
false-positive stale alerts on bank holidays and after-hours).
"""
from __future__ import annotations
from datetime import date, datetime
from zoneinfo import ZoneInfo

from utils.config import get as cfg


# Bank holiday calendars (exchange-closed dates, not just national holidays).
# Add entries for each new year as needed.
_BANK_HOLIDAYS: dict[str, set[date]] = {
    "uk": {  # LSE (FTSE100/USD)
        date(2026, 1, 1),
        date(2026, 4, 3),   # Good Friday
        date(2026, 4, 6),   # Easter Monday
        date(2026, 5, 4),   # Early May Bank Holiday
        date(2026, 5, 25),  # Spring Bank Holiday
        date(2026, 8, 31),  # Summer Bank Holiday
        date(2026, 12, 25),
        date(2026, 12, 28), # Boxing Day (observed, Mon)
        date(2027, 1, 1),
    },
    "us": {  # NYSE (DJ30/USD)
        date(2026, 1, 1),
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 7, 3),   # Independence Day (observed, Fri)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25),
        date(2027, 1, 1),
    },
    "de": {  # XETRA (DAX/USD)
        date(2026, 1, 1),
        date(2026, 4, 3),   # Good Friday
        date(2026, 4, 6),   # Easter Monday
        date(2026, 5, 1),   # Labour Day
        date(2026, 5, 14),  # Ascension Day
        date(2026, 5, 25),  # Whit Monday
        date(2026, 10, 3),  # German Unity Day
        date(2026, 12, 25),
        date(2026, 12, 26), # Boxing Day
        date(2027, 1, 1),
    },
}

# Maps each index pair to its exchange holiday calendar
_PAIR_EXCHANGE: dict[str, str] = {
    "DJ30/USD":    "us",
    "FTSE100/USD": "uk",
    "DAX/USD":     "de",
    "XAU/USD":     "us",   # COMEX gold follows US bank holidays
}


def is_index_market_open(pair: str) -> bool:
    """Return True if pair is tradeable right now.

    Returns True for crypto/unconfigured pairs (24/7).
    Returns False for index pairs outside session hours, on weekends, or
    on exchange bank holidays.
    """
    session_hours = cfg().get("indices", {}).get("session_hours", {})
    spec = session_hours.get(pair)
    if not spec:
        return True  # crypto or unconfigured pair — 24/7

    hours, tz_str = spec.rsplit(" ", 1)
    start_str, end_str = hours.split("-")
    now = datetime.now(ZoneInfo(tz_str))

    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    exchange = _PAIR_EXCHANGE.get(pair)
    if exchange:
        holidays = _BANK_HOLIDAYS.get(exchange, set())
        if now.date() in holidays:
            return False

    start = now.replace(hour=int(start_str[:2]), minute=int(start_str[3:]), second=0, microsecond=0)
    end   = now.replace(hour=int(end_str[:2]),   minute=int(end_str[3:]),   second=0, microsecond=0)
    return start <= now <= end
