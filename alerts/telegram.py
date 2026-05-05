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
    direction = signal["direction"].upper()
    colour = "🟢" if direction == "LONG" else "🔴"
    mode = "SHADOW" if signal.get("shadow_mode") else "LIVE"
    pair = signal["pair"].replace("/", "/")  # keep as-is, just explicit
    strategy = signal["strategy"]
    regime = signal["regime"]
    confidence = signal.get("regime_confidence", 0)
    entry = signal["entry_price"]
    stop = signal.get("suggested_stop_loss")
    take_profit = signal.get("suggested_take_profit")

    stop_pct = ""
    if stop is not None and entry:
        pct = abs(stop - entry) / entry * 100
        stop_pct = f"  <i>(-{pct:.1f}%)</i>" if direction == "LONG" else f"  <i>(+{pct:.1f}%)</i>"

    tp_pct = ""
    if take_profit is not None and entry:
        pct = abs(take_profit - entry) / entry * 100
        tp_pct = f"  <i>(+{pct:.1f}%)</i>" if direction == "LONG" else f"  <i>(-{pct:.1f}%)</i>"

    session = signal.get("market_session", "")
    session_line = f"<b>Session </b>  {session}" if session else ""

    lines = [
        f"{colour} <b>{direction}</b>  {pair}  <code>[{mode}]</code>",
        f"",
        f"<b>Strategy</b>  {strategy}",
        f"<b>Regime  </b>  {regime}  <i>(conf {confidence:.0%})</i>",
    ]
    if session_line:
        lines.append(session_line)
    lines.append(f"<b>Entry   </b>  <code>{entry:,.4f}</code>")
    if stop is not None:
        lines.append(f"<b>Stop    </b>  <code>{stop:,.4f}</code>{stop_pct}")
    if take_profit is not None:
        lines.append(f"<b>Target  </b>  <code>{take_profit:,.4f}</code>{tp_pct}")

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
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=_TIMEOUT,
        )
        if resp.ok:
            logger.debug(f"Telegram alert sent for {signal['pair']} {signal['direction']}")
            return True
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        new_id = body.get("parameters", {}).get("migrate_to_chat_id")
        if new_id:
            logger.error(
                f"Telegram: group upgraded to supergroup — update TELEGRAM_CHAT_ID to {new_id} in .env"
            )
        else:
            logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        logger.warning(f"Telegram request failed: {e}")
    return False
