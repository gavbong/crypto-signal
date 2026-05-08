"""
alerts/telegram.py — Telegram alert sender for signals and copy trader.

Signal alerts:  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
Copy alerts:    COPY_TELEGRAM_BOT_TOKEN + COPY_TELEGRAM_CHAT_ID (separate bot)

Silently skips if credentials are missing or still placeholders — the engine
and copy trader keep running without Telegram configured.
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


def _copy_credentials() -> tuple[str, str] | None:
    token = os.environ.get("COPY_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("COPY_TELEGRAM_CHAT_ID", "")
    if _is_placeholder(token) or _is_placeholder(chat_id):
        return None
    return token, chat_id


def _copy_extra_chat_ids() -> list[str]:
    """Returns additional chat IDs to broadcast copy alerts to (e.g. COPY_TELEGRAM_CHAT_ID_2)."""
    ids = []
    for i in range(2, 10):
        val = os.environ.get(f"COPY_TELEGRAM_CHAT_ID_{i}", "")
        if _is_placeholder(val):
            break
        ids.append(val)
    return ids


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

    exchange = signal.get("exchange", "mexc").upper()

    lines = [
        f"{colour} <b>{direction}</b>  {pair}  <code>[{exchange}]</code>  <code>[{mode}]</code>",
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


def send_telegram(text: str) -> bool:
    """Send a plain-text message to Telegram. Never raises."""
    creds = _credentials()
    if creds is None:
        logger.debug("Telegram not configured — skipping alert")
        return False
    token, chat_id = creds
    try:
        resp = requests.post(
            _SEND_URL.format(token=token),
            json={"chat_id": chat_id, "text": text},
            timeout=_TIMEOUT,
        )
        if resp.ok:
            return True
        logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        logger.warning(f"Telegram request failed: {e}")
    return False


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


# ── Copy trader alerts (separate bot) ─────────────────────────────────────────

def _send_copy(text: str) -> bool:
    """Send a copy trader alert to all configured copy channels. Never raises."""
    creds = _copy_credentials()
    if creds is None:
        logger.debug("Copy Telegram not configured — skipping copy alert")
        return False
    token, primary_chat_id = creds
    all_chat_ids = [primary_chat_id] + _copy_extra_chat_ids()
    success = False
    for chat_id in all_chat_ids:
        try:
            resp = requests.post(
                _SEND_URL.format(token=token),
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=_TIMEOUT,
            )
            if resp.ok:
                success = True
            else:
                logger.warning(f"Copy Telegram API error {resp.status_code} (chat {chat_id[:6]}…): {resp.text[:200]}")
        except requests.RequestException as e:
            logger.warning(f"Copy Telegram request failed (chat {chat_id[:6]}…): {e}")
    return success


def send_copy_open_alert(
    wallet: str, coin: str, direction: str,
    margin_usdt: float, entry_price: float,
    balance_after: float,
) -> bool:
    colour = "🟢" if direction == "long" else "🔴"
    short_wallet = wallet[:6] + "…" + wallet[-4:]
    text = (
        f"{colour} <b>COPY {direction.upper()}</b>  <code>{coin}</code>\n"
        f"\n"
        f"<b>Trader  </b>  <code>{short_wallet}</code>\n"
        f"<b>Entry   </b>  <code>{entry_price:,.4f}</code>\n"
        f"<b>Margin  </b>  <code>${margin_usdt:,.2f}</code>\n"
        f"<b>Balance </b>  <code>${balance_after:,.2f}</code> remaining\n"
        f"\n"
        f"<i>shadow · Hyperliquid copy</i>"
    )
    return _send_copy(text)


# ── Polymarket alerts (same bot as copy trader) ────────────────────────────────

def send_poly_open_alert(
    wallet: str, market_title: str, outcome: str,
    shares: float, entry_price: float, cost_basis: float,
    balance_after: float, category: str, convergent: dict | None,
) -> bool:
    colour = "🟢" if outcome == "YES" else "🔴"
    short_wallet = wallet[:6] + "…" + wallet[-4:]
    title_display = (market_title[:60] + "…") if len(market_title) > 60 else market_title
    text = (
        f"{colour} <b>POLY {outcome}</b>  [{title_display}]\n"
        f"\n"
        f"<b>Trader  </b>  <code>{short_wallet}</code>\n"
        f"<b>Entry   </b>  <code>${entry_price:.2f}</code>\n"
        f"<b>Shares  </b>  <code>{shares:.0f}</code>\n"
        f"<b>Cost    </b>  <code>${cost_basis:.2f}</code>\n"
        f"<b>Balance </b>  <code>${balance_after:,.2f}</code> remaining\n"
    )
    if convergent:
        pair = convergent.get("pair", "")
        direction = convergent.get("direction", "").upper()
        strategy = convergent.get("strategy", "")
        text += f"\n⚡ <i>Convergent signal: {direction} {pair} [{strategy}]</i>\n"
    text += f"\n<i>shadow · Polymarket [{category}]</i>"
    return _send_copy(text)


def send_poly_close_alert(
    wallet: str, market_title: str, outcome: str,
    entry_price: float, exit_price: float, pnl: float,
    cost_basis: float, reason: str, balance_after: float, category: str,
) -> bool:
    if reason == "resolved_win":
        icon, label = "✅", "RESOLVED WIN"
    elif reason == "resolved_loss":
        icon, label = "❌", "RESOLVED LOSS"
    elif reason == "voided":
        icon, label = "⚫", "VOIDED"
    else:
        icon, label = "🛑", "CLOSED"

    pnl_pct  = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0
    pnl_sign = "+" if pnl >= 0 else ""
    short_wallet  = wallet[:6] + "…" + wallet[-4:]
    title_display = (market_title[:60] + "…") if len(market_title) > 60 else market_title

    text = (
        f"{icon} <b>POLY {label}</b>  [{title_display}]\n"
        f"\n"
        f"<b>Trader  </b>  <code>{short_wallet}</code>\n"
        f"<b>Side    </b>  {outcome}\n"
        f"<b>Entry   </b>  <code>${entry_price:.2f}</code> → <code>${exit_price:.2f}</code>\n"
        f"<b>PnL     </b>  <code>{pnl_sign}${abs(pnl):,.2f}</code>  "
        f"<i>({pnl_sign}{pnl_pct:.0f}%)</i>\n"
        f"<b>Balance </b>  <code>${balance_after:,.2f}</code>\n"
        f"\n"
        f"<i>shadow · Polymarket [{category}]</i>"
    )
    return _send_copy(text)


def send_copy_close_alert(
    wallet: str, coin: str, direction: str,
    entry_price: float, exit_price: float,
    pnl: float, margin_usdt: float, reason: str,
    balance_after: float,
) -> bool:
    if reason == "stop_loss":
        icon = "🛑"
        reason_label = "Stop-loss"
    elif pnl >= 0:
        icon = "✅"
        reason_label = reason.replace("_", " ").title()
    else:
        icon = "❌"
        reason_label = reason.replace("_", " ").title()

    pnl_pct = (pnl / margin_usdt * 100) if margin_usdt > 0 else 0.0
    pnl_sign = "+" if pnl >= 0 else ""
    short_wallet = wallet[:6] + "…" + wallet[-4:]

    text = (
        f"{icon} <b>COPY CLOSE</b>  <code>{coin}</code>  {direction.upper()}\n"
        f"\n"
        f"<b>Trader  </b>  <code>{short_wallet}</code>\n"
        f"<b>Entry   </b>  <code>{entry_price:,.4f}</code>\n"
        f"<b>Exit    </b>  <code>{exit_price:,.4f}</code>\n"
        f"<b>PnL     </b>  <code>{pnl_sign}${pnl:,.2f}</code>  "
        f"<i>({pnl_sign}{pnl_pct:.1f}%)</i>\n"
        f"<b>Reason  </b>  {reason_label}\n"
        f"<b>Balance </b>  <code>${balance_after:,.2f}</code>\n"
        f"\n"
        f"<i>shadow · Hyperliquid copy</i>"
    )
    return _send_copy(text)
