"""
tests/test_telegram_format.py — Coverage for alerts/telegram._format_message().

Targets the two new branches introduced in this PR:
  Branch A: session_line truthy  → session line inserted between Regime and Entry
  Branch B: session_line falsy   → no session line; Entry follows Regime directly

Also smoke-tests the full message structure to guard against regressions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts.telegram import _format_message


def _base_signal(**overrides):
    """Minimal valid signal dict for _format_message."""
    sig = {
        "pair": "BTC/USDT:USDT",
        "direction": "long",
        "shadow_mode": True,
        "strategy": "ema_crossover",
        "regime": "trending-up",
        "regime_confidence": 0.82,
        "entry_price": 50000.0,
        "suggested_stop_loss": 49000.0,
        "suggested_take_profit": 52000.0,
        "llm_commentary": None,
    }
    sig.update(overrides)
    return sig


class TestFormatMessageSessionBranch:
    # --- Branch A: market_session present → session line rendered ---

    def test_session_line_appears_when_present(self):
        sig = _base_signal(market_session="London 🇬🇧")
        msg = _format_message(sig)
        assert "Session" in msg
        assert "London" in msg

    def test_session_line_between_regime_and_entry(self):
        sig = _base_signal(market_session="New York 🗽")
        lines = _format_message(sig).splitlines()
        regime_idx = next(i for i, l in enumerate(lines) if "Regime" in l)
        session_idx = next(i for i, l in enumerate(lines) if "Session" in l)
        entry_idx = next(i for i, l in enumerate(lines) if "Entry" in l)
        assert regime_idx < session_idx < entry_idx, (
            f"Expected Regime({regime_idx}) < Session({session_idx}) < Entry({entry_idx})"
        )

    def test_session_value_rendered_in_line(self):
        sig = _base_signal(market_session="Overlap (London/NY) 🌍")
        msg = _format_message(sig)
        assert "Overlap (London/NY)" in msg

    def test_all_five_session_labels_render(self):
        sessions = [
            "Asia 🌏",
            "London 🇬🇧",
            "Overlap (London/NY) 🌍",
            "New York 🗽",
            "Off-hours 🌙",
        ]
        for session in sessions:
            sig = _base_signal(market_session=session)
            msg = _format_message(sig)
            assert "Session" in msg, f"Session label missing for: {session}"

    # --- Branch B: market_session absent/empty → no session line ---

    def test_no_session_line_when_key_absent(self):
        sig = _base_signal()  # no market_session key
        msg = _format_message(sig)
        assert "Session" not in msg

    def test_no_session_line_when_empty_string(self):
        sig = _base_signal(market_session="")
        msg = _format_message(sig)
        assert "Session" not in msg

    def test_entry_follows_regime_when_no_session(self):
        sig = _base_signal()
        lines = [l for l in _format_message(sig).splitlines() if l.strip()]
        regime_idx = next(i for i, l in enumerate(lines) if "Regime" in l)
        entry_idx = next(i for i, l in enumerate(lines) if "Entry" in l)
        assert entry_idx == regime_idx + 1, (
            f"Without session, Entry should immediately follow Regime "
            f"(regime={regime_idx}, entry={entry_idx})"
        )


class TestFormatMessageStructure:
    """Smoke tests — verify the rest of the message is unaffected by the session changes."""

    def test_long_signal_uses_green_dot(self):
        msg = _format_message(_base_signal(direction="long"))
        assert "🟢" in msg

    def test_short_signal_uses_red_dot(self):
        msg = _format_message(_base_signal(direction="short"))
        assert "🔴" in msg

    def test_shadow_mode_label(self):
        msg = _format_message(_base_signal(shadow_mode=True))
        assert "[SHADOW]" in msg

    def test_live_mode_label(self):
        msg = _format_message(_base_signal(shadow_mode=False))
        assert "[LIVE]" in msg

    def test_stop_line_present_when_provided(self):
        msg = _format_message(_base_signal(suggested_stop_loss=49000.0))
        assert "Stop" in msg

    def test_target_line_present_when_provided(self):
        msg = _format_message(_base_signal(suggested_take_profit=52000.0))
        assert "Target" in msg

    def test_commentary_appended_when_present(self):
        sig = _base_signal(llm_commentary="Looking bullish above key support.")
        msg = _format_message(sig)
        assert "Looking bullish above key support." in msg

    def test_no_commentary_section_when_absent(self):
        sig = _base_signal(llm_commentary=None)
        msg = _format_message(sig)
        # Last meaningful line should be Target, not commentary
        lines = [l for l in msg.splitlines() if l.strip()]
        assert "Target" in lines[-1]

    def test_pair_in_header(self):
        msg = _format_message(_base_signal(pair="ETH/USDT:USDT"))
        assert "ETH/USDT:USDT" in msg

    def test_confidence_formatted_as_percent(self):
        msg = _format_message(_base_signal(regime_confidence=0.75))
        assert "75%" in msg
