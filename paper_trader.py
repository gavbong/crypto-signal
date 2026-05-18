"""
paper_trader.py — Paper trading simulator for all configured futures pairs.

Polls the signals DB for new signals across all pairs in config, opens/closes
virtual positions using live market prices, and tracks PnL indefinitely.

State is persisted to signals.db (paper_* tables) — crash-safe and restartable.
"""
import sys
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, db_path, get as cfg
from utils.ccxt_wrapper import make_exchange, fetch_ticker_safe
from db.schema import get_conn

# ── Constants ────────────────────────────────────────────────────────────────

INITIAL_BALANCE       = 1_000.0
LEVERAGE              = 20       # 20x: liquidation requires ~5% adverse move, stops fire first
RISK_PCT              = 0.01     # 1% per trade; 5 pairs × 1% = 5% max simultaneous exposure
MIN_REGIME_CONFIDENCE = 0.20     # skip signals where regime classification is very uncertain

# Per-exchange taker/maker fee rates; config overrides taker, maker comes from maker_fee_rates config
EXCHANGE_TAKER_RATES: dict[str, float] = {
    "mexc":        0.0006,    # 0.06%
    "binance":     0.0004,    # 0.04%
    "okx":         0.0005,    # 0.05%
    "hyperliquid": 0.00035,   # 0.035%
}
EXCHANGE_MAKER_RATES: dict[str, float] = {
    "mexc":        0.0000,    # free
    "binance":     0.0002,    # 0.02%
    "okx":         0.0002,    # 0.02%
    "hyperliquid": 0.0001,    # 0.01%
}

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
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       INTEGER NOT NULL,
    pair            TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    strategy        TEXT    NOT NULL,
    regime          TEXT    NOT NULL,
    entry_price     REAL    NOT NULL,
    contracts       REAL    NOT NULL,
    margin_usdt     REAL    NOT NULL,
    stop_loss       REAL    NOT NULL,
    take_profit     REAL    NOT NULL,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    exit_price      REAL,
    exit_reason     TEXT,
    gross_pnl_usdt  REAL,
    slippage_usdt   REAL    DEFAULT 0,
    fees_usdt       REAL    DEFAULT 0,
    funding_usdt    REAL    DEFAULT 0,
    pnl_usdt        REAL,
    last_price      REAL
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
    # Migrate: add last_price column to existing tables
    try:
        conn.execute("ALTER TABLE paper_positions ADD COLUMN last_price REAL")
        conn.commit()
    except Exception:
        pass  # column already exists
    for migration in [
        "ALTER TABLE paper_positions ADD COLUMN exchange TEXT NOT NULL DEFAULT 'mexc'",
        "ALTER TABLE paper_positions ADD COLUMN gross_pnl_usdt REAL",
        "ALTER TABLE paper_positions ADD COLUMN fees_usdt REAL DEFAULT 0",
        "ALTER TABLE paper_positions ADD COLUMN funding_usdt REAL DEFAULT 0",
        "ALTER TABLE paper_positions ADD COLUMN slippage_usdt REAL DEFAULT 0",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass  # column already exists
    for key, default in [
        ("last_signal_id", "0"), ("day_number", "0"),
        ("consecutive_losses", "0"), ("circuit_breaker_until", "0"),
    ]:
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


def _fetch_tickers(exchange_map: dict, positions: list) -> dict[tuple, float]:
    """Fetch live prices for positions, routing each to its originating exchange.
    Returns {(exchange_id, pair): price}."""
    by_exchange: dict[str, set] = {}
    for pos in positions:
        exc_id = pos["exchange"] if "exchange" in pos.keys() else "mexc"
        by_exchange.setdefault(exc_id, set()).add(pos["pair"])

    prices: dict[tuple, float] = {}
    for exc_id, pairs in by_exchange.items():
        exchange = exchange_map.get(exc_id) or next(iter(exchange_map.values()))
        for pair in pairs:
            ticker = fetch_ticker_safe(exchange, pair)
            if ticker and ticker.get("last"):
                prices[(exc_id, pair)] = float(ticker["last"])
    return prices


def get_unrealized_pnl(conn, exchange_map: dict) -> float:
    """Sum unrealized PnL across all open positions using live prices."""
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE exit_price IS NULL"
    ).fetchall()
    if not rows:
        return 0.0

    prices = _fetch_tickers(exchange_map, rows)

    total = 0.0
    for pos in rows:
        exc_id = pos["exchange"] if "exchange" in pos.keys() else "mexc"
        live = prices.get((exc_id, pos["pair"]))
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


# ── Live funding rate cache ───────────────────────────────────────────────────

_funding_cache: dict[str, tuple[float, float]] = {}  # pair → (rate_8h, fetched_ts)
_FUNDING_TTL = 8 * 3600  # rates are published every 8h
_mexc_swap: object = None  # lazy ccxt exchange for funding rate lookups


def _get_mexc_swap():
    global _mexc_swap
    if _mexc_swap is None:
        _mexc_swap = make_exchange("mexc")
    return _mexc_swap


def _live_funding_rate(pair: str) -> float:
    """Return MEXC 8h funding rate for pair, cached for 8h. Falls back to config on error."""
    pt = cfg().get("paper_trader", {})
    config_rate = pt.get("funding_rates_8h", {}).get(pair, pt.get("funding_rate_8h", 0.0001))

    now = time.time()
    cached = _funding_cache.get(pair)
    if cached and now - cached[1] < _FUNDING_TTL:
        return cached[0]

    try:
        ex = _get_mexc_swap()
        data = ex.fetch_funding_rate(pair)
        rate = float(data.get("fundingRate") or config_rate)
        _funding_cache[pair] = (rate, now)
        logger.debug(f"Funding rate {pair}: {rate:.6f} (live)")
        return rate
    except Exception as exc:
        logger.debug(f"Funding rate fetch failed for {pair}: {exc} — using config fallback")

    _funding_cache[pair] = (config_rate, now)
    return config_rate


# ── Trading cost helpers ──────────────────────────────────────────────────────

def _taker_rate(exchange_id: str) -> float:
    """Taker fee rate — config taker_fee_pct overrides the per-exchange default."""
    pt = cfg().get("paper_trader", {})
    if "taker_fee_pct" in pt:
        return pt["taker_fee_pct"]
    return EXCHANGE_TAKER_RATES.get(exchange_id, EXCHANGE_TAKER_RATES["mexc"])


def _maker_rate(exchange_id: str) -> float:
    """Maker fee rate — used for TP exits (limit order, rests on book)."""
    pt = cfg().get("paper_trader", {})
    cfg_makers = pt.get("maker_fee_rates", {})
    if exchange_id in cfg_makers:
        return cfg_makers[exchange_id]
    return EXCHANGE_MAKER_RATES.get(exchange_id, EXCHANGE_MAKER_RATES["mexc"])


def _calc_fees(entry_price: float, exit_price: float, contracts: float,
               exchange_id: str, exit_reason: str) -> float:
    """Round-trip fees: entry always taker; exit taker for SL/flip/timeout, maker for TP."""
    entry_fee = contracts * entry_price * _taker_rate(exchange_id)
    exit_rate  = _maker_rate(exchange_id) if exit_reason == "take_profit" else _taker_rate(exchange_id)
    exit_fee   = contracts * exit_price * exit_rate
    return -(entry_fee + exit_fee)


def _calc_funding(direction: str, notional: float, opened_at: str, pair: str) -> float:
    """Funding P&L using live 8h rate from MEXC API (cached per funding period)."""
    rate_8h = _live_funding_rate(pair)
    try:
        open_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        hours = (datetime.now(timezone.utc) - open_dt).total_seconds() / 3600
        intervals = hours / 8
        sign = -1 if direction == "long" else +1
        return sign * notional * rate_8h * intervals
    except Exception:
        return 0.0


def _calc_slippage(price: float, contracts: float, direction: str,
                   slippage_pct: float, side: str) -> tuple[float, float]:
    """Return (actual_price_after_slip, slippage_cost_usdt).
    side='entry': long buys high, short sells low.
    side='exit':  long sells low (SL), short buys high (SL).
    slippage_cost is always negative (a cost).
    """
    slip = price * slippage_pct
    if side == "entry":
        actual = price + slip if direction == "long" else price - slip
    else:
        actual = price - slip if direction == "long" else price + slip
    slip_cost = (actual - price) * contracts if direction == "long" else (price - actual) * contracts
    return round(actual, 8), round(-abs(slip_cost), 8)


# ── Circuit breaker ───────────────────────────────────────────────────────────

def _circuit_breaker_active(conn) -> bool:
    """Return True if consecutive-loss pause is in effect."""
    until = _get_state(conn, "circuit_breaker_until")
    if until and until != "0":
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < until_dt:
                return True
            _set_state(conn, "circuit_breaker_until", "0")
            _set_state(conn, "consecutive_losses", "0")
        except Exception:
            pass
    return False


def _record_close_outcome(conn, net_pnl: float) -> None:
    """Track consecutive losses; trip circuit breaker when threshold hit."""
    pt = cfg().get("paper_trader", {})
    max_losses = pt.get("circuit_breaker_losses", 5)
    cooldown_h = pt.get("circuit_breaker_cooldown_hours", 4)

    if net_pnl >= 0:
        _set_state(conn, "consecutive_losses", "0")
        return

    consecutive = int(_get_state(conn, "consecutive_losses") or "0") + 1
    _set_state(conn, "consecutive_losses", str(consecutive))
    if consecutive >= max_losses:
        from datetime import timedelta
        until = (datetime.now(timezone.utc) + timedelta(hours=cooldown_h)).isoformat()
        _set_state(conn, "circuit_breaker_until", until)
        logger.warning(
            f"Paper: circuit breaker — {consecutive} consecutive losses. "
            f"Pausing new entries until {until}"
        )


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

    # Circuit breaker gate
    if _circuit_breaker_active(conn):
        logger.debug(f"Paper: circuit breaker active — skipping signal {signal.get('id')}")
        return None

    # Regime confidence gates
    conf = signal.get("regime_confidence")
    regime_label = signal.get("regime", "")

    if conf is not None and conf < MIN_REGIME_CONFIDENCE:
        logger.debug(
            f"Paper: signal {signal.get('id')} regime_confidence={conf:.3f} "
            f"below {MIN_REGIME_CONFIDENCE} — skipping"
        )
        return None

    if conf is not None and "trending" in regime_label:
        max_conf = cfg()["signals"].get("trending_max_confidence", 0.65)
        if conf > max_conf:
            logger.debug(
                f"Paper: signal {signal.get('id')} {regime_label} conf={conf:.3f} "
                f"> {max_conf} — extended move gate, skipping"
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

    # Correlated pairs guard for liquidity_grab — BTC/ETH/SOL/BNB move together.
    # Stacking same-direction positions across correlated pairs multiplies loss
    # when the market moves against the thesis (all stop out simultaneously).
    _CORR_CLUSTER = {"BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
                     "BNB/USDT:USDT", "ETH/USDC:USDC", "BTC/USDC:USDC"}
    strategy = signal.get("strategy", "")
    if strategy == "liquidity_grab" and pair in _CORR_CLUSTER:
        cluster_peers = _CORR_CLUSTER - {pair}
        peer_placeholders = ",".join("?" * len(cluster_peers))
        corr_open = conn.execute(
            f"SELECT pair FROM paper_positions WHERE strategy='liquidity_grab' "
            f"AND direction=? AND exit_price IS NULL AND pair IN ({peer_placeholders})",
            (direction, *cluster_peers),
        ).fetchone()
        if corr_open:
            logger.debug(
                f"Paper: correlated pair guard — {pair} {direction} liquidity_grab skipped "
                f"(already open on {corr_open['pair']})"
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
            entry_price, contracts, margin_usdt, stop_loss, take_profit, opened_at, exchange)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (signal["id"], pair, direction, signal["strategy"], signal["regime"],
         live_price, contracts, margin, stop, tp, now, signal.get("exchange", "mexc")),
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
    """Close a position. Returns net PnL in USDT.

    Cost breakdown stored per-column so the dashboard can show each component:
      gross_pnl_usdt  — pure price movement (nominal entry → nominal exit)
      slippage_usdt   — market-impact cost on entry + SL/timeout exit (negative)
      fees_usdt       — exchange fees: entry taker + exit taker or maker (negative)
      funding_usdt    — hold-period funding (negative for longs in positive-rate markets)
      pnl_usdt        — net = sum of all four
    """
    pos = dict(pos)
    pt = cfg().get("paper_trader", {})
    exchange_id = pos.get("exchange") or "mexc"
    direction   = pos["direction"]
    pair        = pos["pair"]
    contracts   = pos["contracts"]
    entry_price = pos["entry_price"]

    # ── Entry slippage (market order at signal price) ─────────────────────────
    entry_slip_pct = pt.get("entry_slippage_pct", 0.0002)
    _actual_entry, entry_slip_cost = _calc_slippage(
        entry_price, contracts, direction, entry_slip_pct, side="entry"
    )

    # ── Exit slippage: SL/timeout = market order; TP/flip = limit, no slip ────
    market_exit_reasons = {"stop_loss", "timeout"}
    if reason in market_exit_reasons:
        actual_exit, exit_slip_cost = _calc_slippage(
            exit_price, contracts, direction, pt.get("slippage_pct", 0.0005), side="exit"
        )
    else:
        actual_exit   = exit_price
        exit_slip_cost = 0.0

    total_slippage = round(entry_slip_cost + exit_slip_cost, 8)

    # ── Gross P&L — nominal price movement, no execution costs ───────────────
    if direction == "long":
        gross_pnl = (exit_price - entry_price) * contracts
    else:
        gross_pnl = (entry_price - exit_price) * contracts

    # ── Fees — entry taker; exit maker for TP, taker otherwise ───────────────
    fees_usdt = _calc_fees(entry_price, exit_price, contracts, exchange_id, reason)

    # ── Funding — per-pair rate × 8h intervals held ───────────────────────────
    funding_usdt = _calc_funding(direction, contracts * entry_price, pos["opened_at"], pair)

    net_pnl = gross_pnl + total_slippage + fees_usdt + funding_usdt

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE paper_positions
           SET closed_at=?, exit_price=?, exit_reason=?,
               gross_pnl_usdt=?, slippage_usdt=?, fees_usdt=?, funding_usdt=?, pnl_usdt=?
           WHERE id=?""",
        (now, actual_exit, reason,
         round(gross_pnl, 4), round(total_slippage, 4),
         round(fees_usdt, 4), round(funding_usdt, 4), round(net_pnl, 4),
         pos["id"]),
    )
    conn.commit()
    _record_close_outcome(conn, net_pnl)

    outcome = "WIN" if net_pnl >= 0 else "LOSS"
    logger.info(
        f"Paper CLOSE [{pos['id']}] {direction.upper()} {pair} "
        f"exit={actual_exit:.4f} reason={reason} "
        f"gross={gross_pnl:+.2f} slip={total_slippage:.2f} "
        f"fees={fees_usdt:.2f} funding={funding_usdt:+.2f} "
        f"net={net_pnl:+.2f} USDT [{outcome}]"
    )
    return net_pnl


# ── Poll cycle ────────────────────────────────────────────────────────────────

def check_positions(conn, exchange_map: dict) -> int:
    """Check open positions against live prices; close on SL/TP hit. Returns closed count."""
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE exit_price IS NULL"
    ).fetchall()
    if not rows:
        return 0

    prices = _fetch_tickers(exchange_map, rows)

    closed = 0
    for pos in rows:
        exc_id = pos["exchange"] if "exchange" in pos.keys() else "mexc"
        live = prices.get((exc_id, pos["pair"]))
        if live is None:
            logger.warning(f"Paper: no ticker for {pos['pair']} ({exc_id}) — skipping position check")
            continue

        conn.execute("UPDATE paper_positions SET last_price=? WHERE id=?", (live, pos["id"]))

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
    conn.commit()
    return closed


def check_timeouts(conn, exchange_map: dict) -> int:
    """Close positions open longer than position_timeout_hours at market price."""
    from datetime import timedelta
    timeout_h = cfg().get("paper_trader", {}).get("position_timeout_hours", 48)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_h)).isoformat()
    rows = conn.execute(
        "SELECT * FROM paper_positions WHERE exit_price IS NULL AND opened_at < ?",
        (cutoff,),
    ).fetchall()
    if not rows:
        return 0
    prices = _fetch_tickers(exchange_map, rows)
    closed = 0
    for pos in rows:
        exc_id = (dict(pos).get("exchange") or "mexc")
        live = prices.get((exc_id, pos["pair"]))
        if live is None:
            continue
        close_position(conn, dict(pos), live, "timeout")
        closed += 1
    return closed


def poll_new_signals(conn) -> list[dict]:
    """Fetch all new live (non-backtest) signals since last seen id."""
    last_id = int(_get_state(conn, "last_signal_id"))
    rows = conn.execute(
        "SELECT * FROM signals WHERE id > ? AND backtest_run_id IS NULL ORDER BY id",
        (last_id,),
    ).fetchall()
    if not rows:
        return []
    _set_state(conn, "last_signal_id", str(rows[-1]["id"]))
    return [dict(row) for row in rows]


# ── Daily snapshot ────────────────────────────────────────────────────────────

def snapshot_day(conn, exchange_map: dict) -> dict:
    """Capture end-of-day PnL snapshot and write JSON log."""
    day_number = int(_get_state(conn, "day_number")) + 1

    free       = get_free_balance(conn)
    unrealized = get_unrealized_pnl(conn, exchange_map)
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

def poll_job(exchange_map: dict) -> None:
    with get_conn() as conn:
        closed = check_positions(conn, exchange_map)
        timed_out = check_timeouts(conn, exchange_map)
        if closed or timed_out:
            logger.info(f"Paper: closed {closed} position(s) · timed out {timed_out} this tick")

        signals = poll_new_signals(conn)
        for sig in signals:
            exc_id = sig.get("exchange", "mexc")
            exchange = exchange_map.get(exc_id) or next(iter(exchange_map.values()))
            ticker = fetch_ticker_safe(exchange, sig["pair"])
            if not ticker or not ticker.get("last"):
                logger.warning(f"Paper: no live price for {sig['pair']} ({exc_id}) signal {sig['id']} — skipping")
                continue
            live_price = float(ticker["last"])
            open_position(conn, sig, live_price)


def snapshot_job(exchange_map: dict) -> None:
    with get_conn() as conn:
        snapshot_day(conn, exchange_map)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="{time:HH:mm:ss} | {level:<7} | paper  | {message}")
    logger.add("logs/paper_trader.log", rotation="1 day", retention="30 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}")

    with get_conn() as conn:
        init_paper_db(conn)
        # Config-driven account reset — set paper_trader.reset_account: true to wipe and restart
        if cfg().get("paper_trader", {}).get("reset_account", False):
            max_live_id_row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM signals WHERE backtest_run_id IS NULL"
            ).fetchone()
            max_live_id = max_live_id_row[0] if max_live_id_row else 0
            conn.executescript("""
                DELETE FROM paper_positions;
                DELETE FROM paper_daily_pnl;
            """)
            _set_state(conn, "last_signal_id", str(max_live_id))
            _set_state(conn, "day_number", "0")
            _set_state(conn, "reset_note", f"Paper account v2 reset at {datetime.now(timezone.utc).isoformat()} — post signal quality overhaul, 1k starting balance")
            logger.info(f"Paper account reset to $1,000 USDT — will process signals from id>{max_live_id}")

    exchange_map: dict = {}
    for exc_id, exc_cfg in cfg().get("exchanges", {}).items():
        if not exc_cfg.get("enabled", False):
            continue
        try:
            exchange_map[exc_id] = make_exchange(exc_id)
        except Exception as e:
            logger.error(f"Paper: failed to init exchange {exc_id}: {e}")

    if not exchange_map:
        logger.error("Paper: no exchanges enabled — check config.yaml")
        return

    free = 0.0
    with get_conn() as conn:
        free = get_free_balance(conn)

    logger.info(
        f"Paper trader starting | exchanges={list(exchange_map)} balance={free:.2f} USDT "
        f"leverage={LEVERAGE}x risk={RISK_PCT:.0%}"
    )

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        poll_job,
        "interval",
        minutes=15,
        args=[exchange_map],
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        snapshot_job,
        "cron",
        hour=0,
        minute=0,
        args=[exchange_map],
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Paper trader stopped by user")


if __name__ == "__main__":
    main()
