"""
alerts/telegram.py — Telegram signal alert sender.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
Silently skips (logs warning) if either is missing or still a placeholder,
so the engine keeps running without Telegram configured.
"""
import os
import requests
from loguru import logger


_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10


def _is_placeholder(val: str) -> bool:
    return not val or val.startswith("your_")


def _credentials() -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if _is_placeholder(token) or _is_placeholder(chat_id):
        return None
    return token, chat_id


def _format_message(signal: dict) -> str:
    mode = "[SHADOW] " if signal.get("shadow_mode") else "[LIVE] "
    direction = signal["direction"].upper()
    pair = signal["pair"]
    strategy = signal["strategy"]
    regime = signal["regime"]
    confidence = signal.get("regime_confidence", 0)
    entry = signal["entry_price"]
    stop = signal.get("suggested_stop_loss")

    stop_pct = ""
    if stop is not None and entry:
        pct = abs(stop - entry) / entry * 100
        stop_pct = f" (-{pct:.1f}%)" if direction == "LONG" else f" (+{pct:.1f}%)"

    lines = [
        f"{mode}SIGNAL",
        f"{pair}  |  {direction}",
        f"",
        f"Strategy : {strategy}",
        f"Regime   : {regime} (conf {confidence:.0%})",
        f"Entry    : {entry:,.4f}",
    ]
    if stop is not None:
        lines.append(f"Stop     : {stop:,.4f}{stop_pct}")

    commentary = signal.get("llm_commentary")
    if commentary:
        lines += ["", commentary]

    return "\n".join(lines)


def send_signal_alert(signal: dict) -> bool:
    """
    Send a signal alert to Telegram. Returns True on success, False on skip/error.
    Never raises — engine must not crash due to a failed alert.
    """
    creds = _credentials()
    if creds is None:
        logger.debug("Telegram not configured — skipping alert")
        return False

    token, chat_id = creds
    text = _format_message(signal)

    try:
        resp = requests.post(
            _SEND_URL.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": ""},
            timeout=_TIMEOUT,
        )
        if resp.ok:
            logger.debug(f"Telegram alert sent for {signal['pair']} {signal['direction']}")
            return True
        logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        logger.warning(f"Telegram request failed: {e}")
    return False
