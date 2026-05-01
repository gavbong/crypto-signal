"""
tests/test_market_session.py — Coverage for signal_engine._market_session().

Five branches:
  Asia      [0, 8)
  London    [8, 13)
  Overlap   [13, 17)
  New York  [17, 22)
  Off-hours [22, 24) and hypothetical edge
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from signal_engine import _market_session


class TestMarketSessionBranches:
    # --- Asia branch: [0, 8) ---
    def test_hour_0_is_asia(self):
        assert _market_session(0) == "Asia 🌏"

    def test_hour_7_is_asia(self):
        assert _market_session(7) == "Asia 🌏"

    def test_hour_4_midpoint_asia(self):
        assert _market_session(4) == "Asia 🌏"

    # --- London branch: [8, 13) ---
    def test_hour_8_is_london(self):
        assert _market_session(8) == "London 🇬🇧"

    def test_hour_12_is_london(self):
        assert _market_session(12) == "London 🇬🇧"

    # --- Overlap branch: [13, 17) ---
    def test_hour_13_is_overlap(self):
        assert _market_session(13) == "Overlap (London/NY) 🌍"

    def test_hour_16_is_overlap(self):
        assert _market_session(16) == "Overlap (London/NY) 🌍"

    # --- New York branch: [17, 22) ---
    def test_hour_17_is_new_york(self):
        assert _market_session(17) == "New York 🗽"

    def test_hour_21_is_new_york(self):
        assert _market_session(21) == "New York 🗽"

    # --- Off-hours branch: [22, 24) ---
    def test_hour_22_is_off_hours(self):
        assert _market_session(22) == "Off-hours 🌙"

    def test_hour_23_is_off_hours(self):
        assert _market_session(23) == "Off-hours 🌙"

    # --- Return type sanity ---
    def test_all_hours_return_str(self):
        for hour in range(24):
            result = _market_session(hour)
            assert isinstance(result, str), f"hour {hour} returned non-str"
            assert len(result) > 0, f"hour {hour} returned empty string"

    def test_all_hours_covered_by_one_of_five_labels(self):
        expected_labels = {
            "Asia 🌏",
            "London 🇬🇧",
            "Overlap (London/NY) 🌍",
            "New York 🗽",
            "Off-hours 🌙",
        }
        for hour in range(24):
            assert _market_session(hour) in expected_labels, \
                f"hour {hour} returned unexpected label: {_market_session(hour)!r}"
