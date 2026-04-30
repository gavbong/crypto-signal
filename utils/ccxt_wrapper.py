import time
import ccxt
from loguru import logger
from typing import Optional


def _make_exchange(api_key: str, secret: str) -> ccxt.mexc:
    # Signal engine only reads public market data (candles, ticker) — no credentials needed.
    # Attaching credentials triggers private endpoint calls that fail if the key lacks
    # futures permissions, breaking even public data fetches.
    return ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True})


def fetch_ohlcv_safe(
    exchange: ccxt.mexc,
    pair: str,
    timeframe: str,
    limit: int,
    since: Optional[int] = None,
    retries: int = 3,
) -> Optional[list]:
    """Fetch OHLCV with exponential backoff. Returns None on persistent failure."""
    for attempt in range(retries):
        try:
            return exchange.fetch_ohlcv(pair, timeframe, since=since, limit=limit)
        except ccxt.RateLimitExceeded:
            wait = 2 ** attempt
            logger.warning(f"Rate limit on {pair}, waiting {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
        except ccxt.NetworkError as e:
            wait = 2 ** attempt
            logger.warning(f"Network error on {pair}: {e}, waiting {wait}s")
            time.sleep(wait)
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error on {pair}: {e}")
            return None
    logger.error(f"fetch_ohlcv failed after {retries} attempts for {pair}")
    return None


def fetch_ticker_safe(
    exchange: ccxt.mexc,
    pair: str,
    retries: int = 3,
) -> Optional[dict]:
    for attempt in range(retries):
        try:
            return exchange.fetch_ticker(pair)
        except ccxt.RateLimitExceeded:
            time.sleep(2 ** attempt)
        except ccxt.NetworkError:
            time.sleep(2 ** attempt)
        except ccxt.ExchangeError as e:
            logger.error(f"Ticker error on {pair}: {e}")
            return None
    return None
