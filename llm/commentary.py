from __future__ import annotations
import json
from typing import Optional
import anthropic
from loguru import logger

from utils.config import env, get as cfg
from utils.news import fetch_headlines


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    return _client


_SYSTEM_PROMPT = """\
You are a futures and index signal analyst. A signal has fired on a trading pair.
Your job is to write 2-3 sentences of clear, specific commentary for a trader who is
deciding whether to act on this signal.

Rules:
- Name the regime and how long it has held. Be specific: "trending-up for 5 candles (5h)"
- State why the signal fired in concrete terms (what crossed what, where RSI diverged, etc.)
- If recent news headlines are provided, assess in one phrase whether they support, oppose,
  or are neutral to this signal. Start that phrase with "News:" e.g. "News: adverse — tariff
  fears may extend the selloff" or "News: supportive — ETF inflow headlines align with long bias"
- Name ONE technical risk factor the trader should watch
- Do NOT add disclaimers, legal language, or generic advice
- Do NOT recommend leverage or position size
- Write as a signal analyst, not a financial advisor"""


def generate_commentary(signal: dict, regime_context: dict) -> Optional[str]:
    """
    Generate LLM commentary for a fired signal.
    regime_context: {pair: {label, confidence, age_candles}} for all tracked pairs
    Returns commentary string or None on failure.
    """
    c = cfg()["llm"]
    client = _get_client()

    headlines = fetch_headlines(limit=8)

    context_block = {
        "signal": {
            "pair": signal["pair"],
            "exchange": signal.get("exchange", "unknown"),
            "direction": signal["direction"],
            "strategy": signal["strategy"],
            "regime": signal["regime"],
            "regime_confidence": signal["regime_confidence"],
            "regime_age_candles": signal["regime_age_candles"],
            "entry_price": signal["entry_price"],
            "suggested_stop_loss": signal["suggested_stop_loss"],
            "timeframe": signal["timeframe"],
        },
        "current_regimes": regime_context,
        "recent_news_headlines": headlines,
    }

    try:
        response = client.messages.create(
            model=c["commentary_model"],
            max_tokens=c["max_tokens"],
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Signal fired:\n{json.dumps(context_block, indent=2)}",
                }
            ],
        )
        text = response.content[0].text.strip()
        logger.debug(f"LLM commentary for {signal['pair']}: {text[:80]}...")
        return text
    except anthropic.RateLimitError as e:
        logger.warning(f"Anthropic rate limit: {e}")
        return None
    except anthropic.APIConnectionError as e:
        logger.warning(f"Anthropic connection error: {e}")
        return None
    except anthropic.APIStatusError as e:
        logger.error(f"Anthropic API error {e.status_code}: {e.message}")
        return None
    except Exception as e:
        logger.error(f"Unexpected LLM error: {e}")
        return None
