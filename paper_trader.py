"""
paper_trader.py — Paper trading simulator for all configured futures pairs.

Polls the signals DB for new signals across all pairs in config, opens/closes
virtual positions using live market prices, and tracks PnL indefinitely.

State is persisted to signals.db (paper_* tables) — crash-safe and restartable.
"""
import sys
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, db_path, get as cfg
from utils.ccxt_wrapper import _make_exchange, fetch_ticker_safe
from db.schema import get_conn

# ── Constants ────────────────────────────────────────────────────────────────

INITIAL_BALANCE       = 1_000.0
LEVERAGE              = 10       # 10x: liquidation requires ~10% adverse move, stops fire first
RISK_PCT              = 0.01     # 1% per trade; 5 pairs × 1% = 5% max simultaneous exposure
MIN_REGIME_CONFIDENCE = 0.20     # skip signals where regime classification is very uncertain

# MEXC futures minimum lot sizes per pair
MIN_CONTRACTS: dict[str, float] = {
    "BTC/USDT:USDT": 0.001,
    "ETH/USDT:USDT": 0.01,
    "SOL/USDT:USDT": 0.1,
    "BNB/USDT:USDT": 0.01,
    "ZEC/USDT:USDT": 0.1,
}
DEFAULT_MIN_CONTRACT = 0.01

LOG_DIR = Path("logs/paper_trade")

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   INTEGER NOT NULL,
    pair        TEXT    NOT NULL,
    direction   TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    regime      TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    contracts   REAL    NOT NULL,
    margin_usdt REAL    NOT NULL,
    stop_loss   REAL    NOT NULL,
    take_profit REAL    NOT NULL,
    opened_at   TIMESTAMP NOT NULL,
    closed_at   TIMESTAMP,
    exit_price  REAL,
    exit_reason TEXT,
    pnl_usdt    REAL
);

CREATE TABLE IF NOT EXISTS paper_daily_pnl (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    day_number      INTEGER NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    balance_usdt    REAL    NOT NULL,
    equity_usdt     REAL    NOT NULL,
    realized_pnl    REAL    NOT NULL,
    unrealized_pnl  REAL    NOT NULL,
    open_positions  INTEGER NOT NULL,
    total_trades    INTEGER NOT NULL,
    wins            INTEGER NOT NULL,
    losses          INTEGER NOT NULL,
    win_rate        REAL
);

CREATE TABLE IF NOT EXISTS paper_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_paper_db(conn) -> None:
    conn.executescript(_SCHEMA)
    for key, default in [("last_signal_id", "0"), ("day_number", "0")]:
        conn.execute(
            "INSERT OR IGNORE INTO paper_state (key, value) VALUES (?, ?)",
            (key, default),
        )
    conn.commit()


# ── Balance helpers ───────────────────────────────────────────────────────────

def get_free_balance(conn) -> float:
    """Free balance = initial + sum of closed PnL - sum of open margin."""
    closed = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_positions WHERE exit_price IS NOT NULL"
    ).fetchone()[0]
    locked = conn.execute(
        "SELECT COALESCE(SUM(margin_usdt), 0) FROM paper_positions WHERE exit_price IS NULL"
    ).fetchone()[0]
    return INITIAL_BALANCE + closed - locked


def _fetch_tickers(exchange, pairs: set[str]) -> dict[str, float]:
    """Fetch live price for each unique pair. Returns {pair: price}."""
    prices = {}
    for pair in pairs:
        ticker = fetch_ticker_safe(exchange, pair)
        if ticker and ticker.get("last"):
            prices[pair] = float(ticker["last"])
    return prices


def get_unrealized_pnl(conn, exchange) -> float:
    """Sum unrealized PnL across all open positions using live prices."""
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE exit_price IS NULL"
    ).fetchall()
    if not rows:
        return 0.0

    prices = _fetch_tickers(exchange, {pos["pair"] for pos in rows})

    total = 0.0
    for pos in rows:
        live = prices.get(pos["pair"])
        if live is None:
            continue
        if pos["direction"] == "long":
            total += (live - pos["entry_price"]) * pos["contracts"]
        else:
            total += (pos["entry_price"] - live) * pos["contracts"]
    return total


def _get_state(conn, key: str) -> str:
    row = conn.execute(
        "SELECT value FROM paper_state WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else "0"


def _set_state(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO paper_state (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


# ── Position management ───────────────────────────────────────────────────────

def open_position(conn, signal: dict, live_price: float) -> dict | None:
    """
    Attempt to open a paper position for a signal.
    Same-direction duplicate on the same pair is skipped.
    Opposite-direction signal closes the existing position and flips.
    Returns the position row dict on success, None if skipped.
    """
    pair      = signal["pair"]
    direction = signal["direction"]

    # Regime confidence gate
    conf = signal.get("regime_confidence")
    if conf is not None and conf < MIN_REGIME_CONFIDENCE:
        logger.debug(
            f"Paper: signal {signal.get('id')} regime_confidence={conf:.3f} "
            f"below {MIN_REGIME_CONFIDENCE} — skipping"
        )
        return None

    existing = conn.execute(
        "SELECT * FROM paper_positions WHERE pair=? AND exit_price IS NULL",
        (pair,),
    ).fetchone()
    if existing:
        if existing["direction"] != direction:
            # Opposite signal — close existing and flip to new direction
            logger.info(
                f"Paper: FLIP {pair} {existing['direction'].upper()}→{direction.upper()} "
                f"signal {signal.get('id')} @ {live_price:.4f}"
            )
            close_position(conn, dict(existing), live_price, "signal_flip")
        else:
            # Same direction — already positioned correctly
            logger.debug(
                f"Paper: already {direction} on {pair} — skipping signal {signal.get('id')}"
            )
            return None

    stop = signal.get("suggested_stop_loss")
    tp   = signal.get("suggested_take_profit")
    if not stop or not tp:
        logger.debug(f"Paper: signal {signal['id']} missing stop/tp — skipping")
        return None

    risk_per_contract = abs(live_price - stop)
    if risk_per_contract <= 0:
        logger.warning(f"Paper: zero risk_per_contract for signal {signal['id']}")
        return None

    free = get_free_balance(conn)
    if free <= 0:
        logger.warning("Paper: no free balance — skipping")
        return None

    min_contract = MIN_CONTRACTS.get(pair, DEFAULT_MIN_CONTRACT)

    risk_usdt     = free * RISK_PCT
    raw_contracts = risk_usdt / risk_per_contract
    max_contracts = (free * LEVERAGE) / live_price
    contracts     = max(min_contract, min(raw_contracts, max_contracts))
    contracts     = math.floor(contracts / min_contract) * min_contract  # round to lot
    if contracts < min_contract:
        logger.warning(f"Paper: contracts {contracts} below minimum for {pair} — skipping")
        return None

    margin = (contracts * live_price) / LEVERAGE

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO paper_positions
           (signal_id, pair, direction, strategy, regime,
            entry_price, contracts, margin_usdt, stop_loss, take_profit, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (signal["id"], pair, direction, signal["strategy"], signal["regime"],
         live_price, contracts, margin, stop, tp, now),
    )
    conn.commit()
    pos_id = cur.lastrowid

    logger.info(
        f"Paper OPEN  [{pos_id}] {direction.upper()} {pair} "
        f"entry={live_price:.4f} contracts={contracts} "
        f"stop={stop:.4f} tp={tp:.4f} margin={margin:.2f}"
    )
    return {
        "id": pos_id, "pair": pair, "direction": direction,
        "entry_price": live_price, "contracts": contracts,
        "stop_loss": stop, "take_profit": tp,
    }


def close_position(conn, pos, exit_price: float, reason: str) -> float:
    """Close a position and return PnL in USDT."""
    if pos["direction"] == "long":
        pnl = (exit_price - pos["entry_price"]) * pos["contracts"]
    else:
        pnl = (pos["entry_price"] - exit_price) * pos["contracts"]

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE paper_positions
           SET closed_at=?, exit_price=?, exit_reason=?, pnl_usdt=?
           WHERE id=?""",
        (now, exit_price, reason, pnl, pos["id"]),
    )
    conn.commit()

    outcome = "WIN" if pnl >= 0 else "LOSS"
    logger.info(
        f"Paper CLOSE [{pos['id']}] {pos['direction'].upper()} {pos['pair']} "
        f"exit={exit_price:.4f} reason={reason} pnl={pnl:+.2f} USDT [{outcome}]"
    )
    return pnl


# ── Poll cycle ────────────────────────────────────────────────────────────────

def check_positions(conn, exchange) -> int:
    """Check open positions against live prices; close on SL/TP hit. Returns closed count."""
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE exit_price IS NULL"
    ).fetchall()
    if not rows:
        return 0

    prices = _fetch_tickers(exchange, {pos["pair"] for pos in rows})

    closed = 0
    for pos in rows:
        live = prices.get(pos["pair"])
        if live is None:
            logger.warning(f"Paper: no ticker for {pos['pair']} — skipping position check")
            continue

        if pos["direction"] == "long":
            if live <= pos["stop_loss"]:
                close_position(conn, pos, live, "stop_loss")
                closed += 1
            elif live >= pos["take_profit"]:
                close_position(conn, pos, live, "take_profit")
                closed += 1
        else:  # short
            if live >= pos["stop_loss"]:
                close_position(conn, pos, live, "stop_loss")
                closed += 1
            elif live <= pos["take_profit"]:
                close_position(conn, pos, live, "take_profit")
                closed += 1
    return closed


def poll_new_signals(conn, pairs: list[str]) -> list[dict]:
    """Fetch new signals from the signals table for all configured pairs since last seen id."""
    last_id = int(_get_state(conn, "last_signal_id"))
    placeholders = ",".join("?" * len(pairs))
    rows = conn.execute(
        f"SELECT * FROM signals WHERE pair IN ({placeholders}) AND id > ? ORDER BY id",
        (*pairs, last_id),
    ).fetchall()
    if not rows:
        return []
    _set_state(conn, "last_signal_id", str(rows[-1]["id"]))
    return [dict(row) for row in rows]


# ── Daily snapshot ────────────────────────────────────────────────────────────

def snapshot_day(conn, exchange) -> dict:
    """Capture end-of-day PnL snapshot and write JSON log."""
    day_number = int(_get_state(conn, "day_number")) + 1

    free       = get_free_balance(conn)
    unrealized = get_unrealized_pnl(conn, exchange)
    equity     = free + unrealized

    realized_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_positions WHERE exit_price IS NOT NULL"
    ).fetchone()[0]
    open_count = conn.execute(
        "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NULL"
    ).fetchone()[0]
    total_trades = conn.execute(
        "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL"
    ).fetchone()[0]
    wins = conn.execute(
        "SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL AND pnl_usdt >= 0"
    ).fetchone()[0]
    losses   = total_trades - wins
    win_rate = wins / total_trades if total_trades > 0 else None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO paper_daily_pnl
           (day_number, snapshot_date, balance_usdt, equity_usdt, realized_pnl,
            unrealized_pnl, open_positions, total_trades, wins, losses, win_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (day_number, today, free, equity, realized_pnl, unrealized,
         open_count, total_trades, wins, losses, win_rate),
    )
    conn.commit()
    _set_state(conn, "day_number", str(day_number))

    snapshot = {
        "day": day_number,
        "date": today,
        "balance_usdt": round(free, 2),
        "equity_usdt": round(equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "open_positions": open_count,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{today}.json"
    with open(log_file, "w") as f:
        json.dump(snapshot, f, indent=2)

    logger.info(
        f"Paper SNAPSHOT day={day_number} date={today} "
        f"balance={free:.2f} equity={equity:.2f} "
        f"realized={realized_pnl:+.2f} trades={total_trades} "
        f"win_rate={f'{win_rate:.1%}' if win_rate is not None else 'N/A'}"
    )
    return snapshot


# ── Scheduler jobs ────────────────────────────────────────────────────────────

def poll_job(exchange, pairs: list[str]) -> None:
    with get_conn() as conn:
        closed = check_positions(conn, exchange)
        if closed:
            logger.info(f"Paper: closed {closed} position(s) this tick")

        signals = poll_new_signals(conn, pairs)
        for sig in signals:
            ticker = fetch_ticker_safe(exchange, sig["pair"])
            if not ticker or not ticker.get("last"):
                logger.warning(f"Paper: no live price for {sig['pair']} signal {sig['id']} — skipping")
                continue
            live_price = float(ticker["last"])
            open_position(conn, sig, live_price)


def snapshot_job(exchange) -> None:
    with get_conn() as conn:
        snapshot_day(conn, exchange)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="{time:HH:mm:ss} | {level:<7} | paper  | {message}")
    logger.add("logs/paper_trader.log", rotation="1 day", retention="30 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}")

    pairs = cfg()["pairs"]

    with get_conn() as conn:
        init_paper_db(conn)

    exchange = _make_exchange(env("MEXC_API_KEY"), env("MEXC_SECRET"))

    free = 0.0
    with get_conn() as conn:
        free = get_free_balance(conn)

    logger.info(
        f"Paper trader starting | pairs={pairs} balance={free:.2f} USDT "
        f"leverage={LEVERAGE}x risk={RISK_PCT:.0%}"
    )

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        poll_job,
        "interval",
        minutes=15,
        args=[exchange, pairs],
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        snapshot_job,
        "cron",
        hour=0,
        minute=0,
        args=[exchange],
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Paper trader stopped by user")


if __name__ == "__main__":
    main()
