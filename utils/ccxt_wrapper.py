import os
import time
import ccxt
from loguru import logger
from typing import Optional


_EXCHANGE_CLASSES = {
    "mexc":        ("mexc",       {"defaultType": "swap"}),
    "binance":     ("binance",    {"defaultType": "future"}),
    "okx":         ("okx",        {"defaultType": "swap"}),
    "hyperliquid": ("hyperliquid", {}),
}


def make_exchange(exchange_id: str) -> ccxt.Exchange:
    """Create a CCXT exchange instance for public market data (OHLCV, ticker).
    No credentials attached — avoids permissions issues for read-only data."""
    entry = _EXCHANGE_CLASSES.get(exchange_id)
    if entry is None:
        raise ValueError(f"Unknown exchange: {exchange_id}")
    cls_name, extra_opts = entry
    cls = getattr(ccxt, cls_name)
    opts: dict = {"enableRateLimit": True}
    if extra_opts:
        opts["options"] = extra_opts
    return cls(opts)


def _make_exchange(api_key: str, secret: str) -> ccxt.mexc:
    return make_exchange("mexc")


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
            logger.warning(f"Network error on {pair}: {str(e)[:200]}, waiting {wait}s")
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
