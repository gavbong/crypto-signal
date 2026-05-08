"""
copy_trader.py — Shadow copy-trader following top Hyperliquid leaderboard traders.

Weekly: refreshes top N traders by 30d PnL from HL leaderboard.
Every 15 min: polls their open positions, shadow-copies opens/closes/reversals
into copy_positions table for comparison against the paper trader.

Always shadow mode — no real execution regardless of global config flag.
Runs as 4th systemd service: mexc-copy-trader (starts at :07/:22/:37/:52).
"""
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.config import get as cfg
from db.schema import get_conn

# ── API endpoints ─────────────────────────────────────────────────────────────

_HL_INFO   = "https://api.hyperliquid.xyz/info"
_HL_LEADER = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

# ── DB schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS copy_traders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet          TEXT NOT NULL UNIQUE,
    alias           TEXT,
    pnl_30d         REAL,
    tracked_since   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_refreshed  TIMESTAMP,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS copy_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trader_wallet   TEXT NOT NULL,
    pair            TEXT NOT NULL,
    direction       TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    last_price      REAL,
    contracts       REAL,
    margin_usdt     REAL,
    pnl_usdt        REAL,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    exit_reason     TEXT
);

CREATE TABLE IF NOT EXISTS copy_state (
    trader_wallet   TEXT NOT NULL,
    coin            TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            REAL NOT NULL,
    entry_px        REAL NOT NULL,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trader_wallet, coin)
);

CREATE TABLE IF NOT EXISTS copy_daily_pnl (
    date     TEXT NOT NULL PRIMARY KEY,
    pnl_usdt REAL NOT NULL DEFAULT 0
);
"""


def init_copy_db(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


# ── HL API helpers ─────────────────────────────────────────────────────────────

def fetch_leaderboard(min_pnl: float, top_n: int) -> list[dict]:
    """
    Returns up to top_n traders with 30d PnL >= min_pnl, sorted descending.
    Each entry: {wallet, pnl_30d, alias}. Returns [] on error.
    """
    try:
        resp = requests.get(_HL_LEADER, timeout=20)
        resp.raise_for_status()
        rows = resp.json().get("leaderboardRows", [])
    except Exception as e:
        logger.error(f"Leaderboard fetch failed: {e}")
        return []

    result = []
    for row in rows:
        wallet = row.get("ethAddress")
        if not wallet:
            continue
        pnl_30d = None
        for window, stats in row.get("windowPerformances", []):
            if window == "month":
                pnl_30d = float(stats["pnl"])
                break
        if pnl_30d is None or pnl_30d < min_pnl:
            continue
        result.append({"wallet": wallet, "pnl_30d": pnl_30d, "alias": row.get("displayName")})

    result.sort(key=lambda r: r["pnl_30d"], reverse=True)
    return result[:top_n]


def fetch_hl_positions(wallet: str) -> dict | None:
    """
    Returns {coin: {side, size, entryPx}} for all open positions.
    Returns None on request error (caller skips this trader for the cycle).
    Returns {} if trader has no open positions.
    """
    try:
        resp = requests.post(
            _HL_INFO,
            json={"type": "clearinghouseState", "user": wallet},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"clearinghouseState failed for {wallet[:12]}…: {e}")
        return None

    result = {}
    for asset_pos in data.get("assetPositions", []):
        pos = asset_pos.get("position", {})
        coin = pos.get("coin")
        szi = pos.get("szi")
        entry_px = pos.get("entryPx")
        if not coin or szi is None:
            continue
        szi_float = float(szi)
        if szi_float == 0.0:
            continue
        result[coin] = {
            "side": "long" if szi_float > 0 else "short",
            "size": abs(szi_float),
            "entryPx": float(entry_px) if entry_px else 0.0,
        }
    return result


def fetch_all_mids() -> dict:
    """Returns {coin: float_price}. Returns {} on error."""
    try:
        resp = requests.post(_HL_INFO, json={"type": "allMids"}, timeout=10)
        resp.raise_for_status()
        return {coin: float(price) for coin, price in resp.json().items()}
    except Exception as e:
        logger.warning(f"allMids fetch failed: {e}")
        return {}


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _coin_to_pair(coin: str) -> str:
    return f"{coin}/USDC:USDC"


def load_copy_state(conn, wallet: str) -> dict:
    """Returns {coin: {side, size, entryPx}} from the last saved state."""
    rows = conn.execute(
        "SELECT coin, side, size, entry_px FROM copy_state WHERE trader_wallet=?",
        (wallet,),
    ).fetchall()
    return {r["coin"]: {"side": r["side"], "size": r["size"], "entryPx": r["entry_px"]}
            for r in rows}


def save_copy_state(conn, wallet: str, positions: dict) -> None:
    """Replace copy_state for this wallet with the current positions snapshot."""
    conn.execute("DELETE FROM copy_state WHERE trader_wallet=?", (wallet,))
    now = datetime.now(timezone.utc).isoformat()
    for coin, pos in positions.items():
        conn.execute(
            """INSERT INTO copy_state (trader_wallet, coin, side, size, entry_px, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (wallet, coin, pos["side"], pos["size"], pos["entryPx"], now),
        )
    conn.commit()


def _copy_open(conn, wallet: str, coin: str, pos: dict, margin_usdt: float) -> None:
    entry = pos["entryPx"]
    contracts = (margin_usdt / entry) if entry > 0 else 0.0
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO copy_positions
           (trader_wallet, pair, direction, entry_price, last_price, contracts, margin_usdt, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (wallet, _coin_to_pair(coin), pos["side"], entry, entry,
         round(contracts, 8), margin_usdt, now),
    )
    conn.commit()
    logger.info(
        f"Copy OPEN  {wallet[:10]}… {coin} {pos['side'].upper()} "
        f"@ {entry} contracts={contracts:.6f}"
    )


def _copy_close(conn, wallet: str, coin: str, exit_price: float, reason: str) -> None:
    pair = _coin_to_pair(coin)
    row = conn.execute(
        """SELECT id, direction, entry_price, contracts
           FROM copy_positions
           WHERE trader_wallet=? AND pair=? AND closed_at IS NULL
           ORDER BY opened_at DESC LIMIT 1""",
        (wallet, pair),
    ).fetchone()
    if row is None:
        return

    direction_sign = 1 if row["direction"] == "long" else -1
    pnl = (exit_price - row["entry_price"]) * (row["contracts"] or 0.0) * direction_sign
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """UPDATE copy_positions
           SET exit_price=?, last_price=?, pnl_usdt=?, closed_at=?, exit_reason=?
           WHERE id=?""",
        (exit_price, exit_price, round(pnl, 4), now, reason, row["id"]),
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO copy_daily_pnl (date, pnl_usdt) VALUES (?, ?)
           ON CONFLICT(date) DO UPDATE SET pnl_usdt = pnl_usdt + excluded.pnl_usdt""",
        (today, round(pnl, 4)),
    )
    conn.commit()
    outcome = "WIN" if pnl >= 0 else "LOSS"
    logger.info(
        f"Copy CLOSE {wallet[:10]}… {coin} {row['direction'].upper()} "
        f"exit={exit_price} reason={reason} pnl={pnl:+.2f} [{outcome}]"
    )


def _update_last_price(conn, wallet: str, coin: str, price: float) -> None:
    conn.execute(
        """UPDATE copy_positions SET last_price=?
           WHERE trader_wallet=? AND pair=? AND closed_at IS NULL""",
        (price, wallet, _coin_to_pair(coin)),
    )
    conn.commit()


# ── Scheduler jobs ─────────────────────────────────────────────────────────────

def refresh_leaderboard_job() -> None:
    c = cfg().get("copy_trader", {})
    top_n   = c.get("top_n", 5)
    min_pnl = float(c.get("min_pnl_30d", 10_000))

    traders = fetch_leaderboard(min_pnl, top_n)
    if not traders:
        logger.warning("Leaderboard refresh: no qualifying traders returned")
        return

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE copy_traders SET active=0")
        for t in traders:
            conn.execute(
                """INSERT INTO copy_traders (wallet, alias, pnl_30d, last_refreshed, active)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(wallet) DO UPDATE SET
                     alias=excluded.alias, pnl_30d=excluded.pnl_30d,
                     last_refreshed=excluded.last_refreshed, active=1""",
                (t["wallet"], t["alias"], t["pnl_30d"], now),
            )
        conn.commit()

    logger.info(
        f"Leaderboard refreshed | active={len(traders)} "
        f"top={traders[0]['wallet'][:12]}… "
        f"pnl=${traders[0]['pnl_30d']:,.0f}"
    )


def poll_positions_job() -> None:
    c = cfg().get("copy_trader", {})
    margin_usdt = float(c.get("margin_usdt", 50.0))

    mids = fetch_all_mids()
    if not mids:
        logger.warning("allMids empty — skipping poll cycle")
        return

    with get_conn() as conn:
        # Poll active traders + any inactive traders who still have open copy positions
        wallet_rows = conn.execute("""
            SELECT wallet FROM copy_traders WHERE active=1
            UNION
            SELECT DISTINCT trader_wallet FROM copy_positions WHERE closed_at IS NULL
        """).fetchall()
        wallets = [r["wallet"] for r in wallet_rows]

    if not wallets:
        logger.debug("No traders to poll")
        return

    for wallet in wallets:
        positions = fetch_hl_positions(wallet)
        if positions is None:
            continue  # API error — skip, retry next cycle

        with get_conn() as conn:
            previous = load_copy_state(conn, wallet)

            for coin, pos in positions.items():
                last_price = mids.get(coin, 0.0)
                if coin not in previous:
                    _copy_open(conn, wallet, coin, pos, margin_usdt)
                elif pos["side"] != previous[coin]["side"]:
                    _copy_close(conn, wallet, coin, last_price, "trader_reversed")
                    _copy_open(conn, wallet, coin, pos, margin_usdt)
                else:
                    _update_last_price(conn, wallet, coin, last_price)

            for coin in previous:
                if coin not in positions:
                    last_price = mids.get(coin, 0.0)
                    _copy_close(conn, wallet, coin, last_price, "trader_closed")

            save_copy_state(conn, wallet, positions)

    logger.debug(f"Copy poll complete | traders={len(wallets)}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="{time:HH:mm:ss} | {level:<7} | copy   | {message}")
    logger.add("logs/copy_trader.log", rotation="1 day", retention="30 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}")

    with get_conn() as conn:
        init_copy_db(conn)

    c = cfg().get("copy_trader", {})
    if not c.get("enabled", True):
        logger.info("Copy trader disabled in config — exiting")
        return

    logger.info(
        f"Copy trader starting | top_n={c.get('top_n', 5)} "
        f"margin={c.get('margin_usdt', 50)} USDT "
        f"min_30d_pnl=${float(c.get('min_pnl_30d', 10_000)):,.0f}"
    )

    refresh_leaderboard_job()

    scheduler = BlockingScheduler(timezone="UTC")

    # Staggered to :07 to avoid DB write contention with signal_engine (:00) and paper_trader (:01)
    scheduler.add_job(
        poll_positions_job,
        "cron",
        minute="7,22,37,52",
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        refresh_leaderboard_job,
        CronTrigger(day_of_week="sun", hour=0, minute=0, timezone="UTC"),
        misfire_grace_time=3600,
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Copy trader stopped by user")


if __name__ == "__main__":
    main()
