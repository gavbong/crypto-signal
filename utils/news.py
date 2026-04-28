"""
utils/news.py — Fetch recent crypto and macro news headlines.

Pulls from CoinTelegraph and CoinDesk RSS feeds (no API key required).
Falls back gracefully on any network error so the engine never blocks on news.
"""
import time
import xml.etree.ElementTree as ET
import requests
from loguru import logger

_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]
_TIMEOUT = 8
_CACHE_TTL = 900  # 15 min — avoid hammering feeds every signal scan

_cache: dict = {"ts": 0.0, "headlines": []}


def fetch_headlines(limit: int = 8) -> list[str]:
    """
    Return up to `limit` recent crypto/macro news headlines.
    Cached for 15 minutes. Returns [] on any error.
    """
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["headlines"]:
        return _cache["headlines"][:limit]

    headlines: list[str] = []
    for url in _FEEDS:
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    headlines.append(title_el.text.strip())
        except Exception as e:
            logger.warning(f"News feed {url} failed: {e}")

    if headlines:
        _cache["ts"] = now
        _cache["headlines"] = headlines
        logger.debug(f"News: fetched {len(headlines)} headlines from RSS feeds")

    return headlines[:limit]
