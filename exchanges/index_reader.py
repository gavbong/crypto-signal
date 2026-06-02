"""
exchanges/index_reader.py — Server-side index data reader.

Duck-typed CCXT interface so signal_engine can treat this like any other
exchange object. Reads from the index_candles table populated by mt4_feeder.py.
"""
from __future__ import annotations
import sqlite3
import time
from loguru import logger

from db.schema import get_conn

_STALE_SECONDS = 30 * 60  # 30 minutes — if feeder hasn't sent candles, skip

_stale_alert_cache: dict[str, float] = {}  # pair → last_alert_ts

# Only 15m is stored natively; multiply limit when fetching for resampling
_RESAMPLE_FACTORS: dict[str, int] = {"1h": 4, "4h": 16, "1d": 96}


def _resample_ohlcv(data: list[list], target_tf: str, limit: int) -> list[list]:
    """Resample [[ts_ms, o, h, l, c, v], ...] from 15m to a coarser timeframe."""
    if not data:
        return []
    import pandas as pd
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    rule = {"1h": "1h", "4h": "4h", "1d": "1D"}.get(target_tf, target_tf)
    resampled = df.resample(rule, closed="left", label="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    result = [
        [int(idx.timestamp()) * 1000, row["open"], row["high"], row["low"], row["close"], row["volume"]]
        for idx, row in resampled.iterrows()
    ]
    return result[-limit:] if len(result) > limit else result


class IndexReader:
    """Pseudo-exchange that reads MT4-fed candles from index_candles table.

    Returns None for any fetch when the most recent candle for a pair is older
    than _STALE_SECONDS, preventing stale-data signals when the PC feeder is
    offline. Crypto signals continue unaffected when this returns None.
    """

    id = "tradenation"

    def fetch_ohlcv(
        self,
        pair: str,
        timeframe: str = "15m",
        limit: int = 100,
        since: int | None = None,
    ) -> list[list] | None:
        """Return OHLCV as [[ts_ms, o, h, l, c, v], ...] or None on stale/error.

        Only 15m candles are stored natively. Coarser timeframes (1h, 4h, 1d)
        are produced by resampling the underlying 15m rows on the fly.
        """
        try:
            with get_conn() as conn:
                if not self._is_fresh(conn, pair):
                    return None

                need_resample = timeframe != "15m"
                stored_tf = "15m"
                fetch_limit = limit * _RESAMPLE_FACTORS.get(timeframe, 1) if need_resample else limit

                if since is not None:
                    rows = conn.execute(
                        """SELECT ts, open, high, low, close, volume
                           FROM index_candles
                           WHERE pair=? AND timeframe=? AND ts >= ?
                           ORDER BY ts ASC LIMIT ?""",
                        (pair, stored_tf, since, fetch_limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT ts, open, high, low, close, volume
                           FROM index_candles
                           WHERE pair=? AND timeframe=?
                           ORDER BY ts DESC LIMIT ?""",
                        (pair, stored_tf, fetch_limit),
                    ).fetchall()
                    rows = list(reversed(rows))

                data = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]

                if need_resample:
                    data = _resample_ohlcv(data, timeframe, limit)

                return data
        except sqlite3.Error as exc:
            logger.warning(f"IndexReader.fetch_ohlcv({pair}): DB error — {exc}")
            return None

    def fetch_ticker(self, pair: str) -> dict | None:
        """Return pseudo-ticker with 'last' set to the most recent close, or None."""
        try:
            with get_conn() as conn:
                if not self._is_fresh(conn, pair):
                    return None

                row = conn.execute(
                    """SELECT close, high, low FROM index_candles
                       WHERE pair=?
                       ORDER BY ts DESC LIMIT 1""",
                    (pair,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "last": float(row[0]),
                    "high": float(row[1]),
                    "low":  float(row[2]),
                    "symbol": pair,
                }
        except sqlite3.Error as exc:
            logger.warning(f"IndexReader.fetch_ticker({pair}): DB error — {exc}")
            return None

    def _is_fresh(self, conn: sqlite3.Connection, pair: str) -> bool:
        """Return False if most recent candle is >30min old (feeder offline)."""
        row = conn.execute(
            "SELECT MAX(ts) FROM index_candles WHERE pair=?", (pair,)
        ).fetchone()
        if row is None or row[0] is None:
            logger.debug(f"IndexReader: no candles yet for {pair}")
            return False
        age = time.time() - float(row[0]) / 1000  # DB stores ms; time.time() is seconds
        if age > _STALE_SECONDS:
            logger.warning(
                f"IndexReader: {pair} last candle {age / 60:.0f}min old — feeder offline?"
            )
            _send_stale_alert(pair, age)
            return False
        return True


def _send_stale_alert(pair: str, age_seconds: float) -> None:
    """Send Telegram alert once per pair per staleness window (throttled).

    Suppressed when the market is legitimately closed (weekends, bank holidays,
    after-hours) — stale candles are expected in those windows.
    """
    try:
        from utils.market_hours import is_index_market_open
        if not is_index_market_open(pair):
            logger.debug(f"IndexReader: {pair} stale but market is closed — suppressing alert")
            return
    except Exception:
        pass  # if import fails, fall through and send

    now = time.time()
    if now - _stale_alert_cache.get(pair, 0) < _STALE_SECONDS:
        return
    _stale_alert_cache[pair] = now

    try:
        from alerts.telegram import send_telegram
        send_telegram(
            f"⚠️ Index feeder stale: {pair} last candle "
            f"{age_seconds / 60:.0f}min ago. Check mt4_feeder.py on Windows PC."
        )
    except Exception as exc:
        logger.debug(f"Stale alert send failed: {exc}")
