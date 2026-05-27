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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.config import env, db_path, get as cfg
from utils.ccxt_wrapper import make_exchange, fetch_ticker_safe
from db.schema import get_conn
from regime.hmm_classifier import MACRO_RISK_MULT

_MACRO_FILE = Path("data/macro/current_regime.json")

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

# Lock files written on peak-drawdown lockout; must be deleted manually to resume.
_LOCK_FILES: dict[str, Path] = {
    "":     LOG_DIR / "LOCKOUT_crypto.lock",
    "idx_": LOG_DIR / "LOCKOUT_indices.lock",
}

# Deduplication: only alert once per (account, mode, calendar-date) per process run.
_dd_alert_sent: set[str] = set()


def _macro_risk_mult() -> tuple[str, float]:
    """Read macro regime from shared JSON written by signal_engine.
    Returns (label, multiplier). Falls back to ('neutral', 1.0) if file missing."""
    try:
        if _MACRO_FILE.exists():
            data = json.loads(_MACRO_FILE.read_text())
            label = data.get("label", "neutral")
            mult = MACRO_RISK_MULT.get(label, 1.0)
            return label, mult
    except Exception:
        pass
    return "neutral", 1.0

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
    last_price      REAL,
    risk_usdt_at_open REAL  DEFAULT 0
);

CREATE TABLE IF NOT EXISTS paper_daily_pnl (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT    NOT NULL DEFAULT 'crypto',
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
        "ALTER TABLE paper_positions ADD COLUMN risk_usdt_at_open REAL DEFAULT 0",
        "ALTER TABLE paper_daily_pnl ADD COLUMN account_id TEXT NOT NULL DEFAULT 'crypto'",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass  # column already exists
    for key, default in [
        ("last_signal_id", "0"), ("day_number", "0"),
        ("consecutive_losses", "0"), ("circuit_breaker_until", "0"),
        # Drawdown state — crypto account
        ("peak_balance", str(INITIAL_BALANCE)),
        ("daily_open_balance", str(INITIAL_BALANCE)), ("daily_open_date", ""),
        ("weekly_open_balance", str(INITIAL_BALANCE)), ("weekly_open_date", ""),
        # Indices account state (idx_ prefix)
        ("idx_last_signal_id", "0"), ("idx_day_number", "0"),
        ("idx_consecutive_losses", "0"), ("idx_circuit_breaker_until", "0"),
        # Drawdown state — indices account
        ("idx_peak_balance", str(INITIAL_BALANCE)),
        ("idx_daily_open_balance", str(INITIAL_BALANCE)), ("idx_daily_open_date", ""),
        ("idx_weekly_open_balance", str(INITIAL_BALANCE)), ("idx_weekly_open_date", ""),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO paper_state (key, value) VALUES (?, ?)",
            (key, default),
        )
    conn.commit()


# ── Balance helpers ───────────────────────────────────────────────────────────

def get_free_balance(conn) -> float:
    """Free balance for the crypto account (excludes tradenation positions)."""
    closed = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_positions "
        "WHERE exit_price IS NOT NULL AND exchange != 'tradenation'"
    ).fetchone()[0]
    locked = conn.execute(
        "SELECT COALESCE(SUM(margin_usdt), 0) FROM paper_positions "
        "WHERE exit_price IS NULL AND exchange != 'tradenation'"
    ).fetchone()[0]
    return INITIAL_BALANCE + closed - locked


def get_free_balance_indices(conn) -> float:
    """Free balance for the indices (tradenation) account."""
    closed = conn.execute(
        "SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_positions "
        "WHERE exit_price IS NOT NULL AND exchange = 'tradenation'"
    ).fetchone()[0]
    locked = conn.execute(
        "SELECT COALESCE(SUM(margin_usdt), 0) FROM paper_positions "
        "WHERE exit_price IS NULL AND exchange = 'tradenation'"
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


def get_unrealized_pnl(conn, exchange_map: dict, exchange_filter: str | None = None) -> float:
    """Sum unrealized PnL for open positions. exchange_filter scopes to one account."""
    if exchange_filter:
        rows = conn.execute(
            "SELECT * FROM paper_positions WHERE exit_price IS NULL AND exchange=?",
            (exchange_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM paper_positions WHERE exit_price IS NULL AND exchange != 'tradenation'"
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


def _calc_funding(direction: str, notional: float, opened_at: str, pair: str,
                  exchange_id: str = "mexc") -> float:
    """Funding cost for the hold period.

    Crypto (MEXC/Binance/OKX): continuous 8h rate × intervals held.
    CFD (Trade Nation): daily cutoff at 22:00 UTC — charge once per cutoff passed.
    """
    try:
        open_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        sign = -1 if direction == "long" else +1

        if exchange_id == "tradenation":
            pt = cfg().get("paper_trader", {})
            annual_rate = pt.get("overnight_finance_rate_annual", 0.05)
            daily_rate = annual_rate / 365

            # Count 22:00 UTC cutoffs that have passed since position opened
            cutoffs = 0
            cursor = open_dt.replace(hour=22, minute=0, second=0, microsecond=0)
            if cursor <= open_dt:
                cursor = cursor.replace(day=cursor.day + 1)
            while cursor <= now:
                cutoffs += 1
                cursor = cursor.replace(day=cursor.day + 1)

            return sign * notional * daily_rate * cutoffs

        # Crypto: continuous 8h perpetual funding
        rate_8h = _live_funding_rate(pair)
        hours = (now - open_dt).total_seconds() / 3600
        intervals = hours / 8
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

def _circuit_breaker_active(conn, pfx: str = "") -> bool:
    """Return True if consecutive-loss pause is in effect. pfx='idx_' for indices account."""
    until = _get_state(conn, f"{pfx}circuit_breaker_until")
    if until and until != "0":
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < until_dt:
                return True
            _set_state(conn, f"{pfx}circuit_breaker_until", "0")
            _set_state(conn, f"{pfx}consecutive_losses", "0")
        except Exception:
            pass
    return False


def _record_close_outcome(conn, net_pnl: float, pfx: str = "") -> None:
    """Track consecutive losses; trip circuit breaker when threshold hit."""
    pt = cfg().get("paper_trader", {})
    max_losses = pt.get("circuit_breaker_losses", 5)
    cooldown_h = pt.get("circuit_breaker_cooldown_hours", 4)

    if net_pnl >= 0:
        _set_state(conn, f"{pfx}consecutive_losses", "0")
        return

    consecutive = int(_get_state(conn, f"{pfx}consecutive_losses") or "0") + 1
    _set_state(conn, f"{pfx}consecutive_losses", str(consecutive))
    if consecutive >= max_losses:
        from datetime import timedelta
        until = (datetime.now(timezone.utc) + timedelta(hours=cooldown_h)).isoformat()
        _set_state(conn, f"{pfx}circuit_breaker_until", until)
        logger.warning(
            f"Paper: circuit breaker ({pfx or 'crypto'}) — {consecutive} consecutive losses. "
            f"Pausing new entries until {until}"
        )


# ── Drawdown circuit breakers ─────────────────────────────────────────────────

def _is_locked_out(pfx: str) -> bool:
    return _LOCK_FILES.get(pfx, _LOCK_FILES[""]).exists()


def _write_lockout(pfx: str, reason: str, balance: float = 0.0, peak: float = 0.0) -> None:
    path = _LOCK_FILES.get(pfx, _LOCK_FILES[""])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    acct = "indices" if pfx == "idx_" else "crypto"
    path.write_text(
        f"PAPER TRADER LOCKOUT\n"
        f"Triggered : {datetime.now(timezone.utc).isoformat()}\n"
        f"Account   : {acct}\n"
        f"Reason    : {reason}\n\n"
        f"Delete this file to resume trading: {path}\n"
    )
    logger.critical(
        f"Paper: LOCKOUT ({acct}) — {reason}. Delete {path} to resume."
    )
    try:
        from alerts.telegram import send_drawdown_alert
        send_drawdown_alert(acct, "lockout", balance, peak)
    except Exception:
        pass


def _refresh_drawdown_state(conn, pfx: str, balance: float) -> None:
    """Update peak / daily-open / weekly-open balance in state. Call after every close and at poll start."""
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    today   = now_utc.strftime("%Y-%m-%d")
    monday  = (now_utc - timedelta(days=now_utc.weekday())).strftime("%Y-%m-%d")

    if _get_state(conn, f"{pfx}daily_open_date") != today:
        _set_state(conn, f"{pfx}daily_open_balance", str(round(balance, 4)))
        _set_state(conn, f"{pfx}daily_open_date", today)

    if _get_state(conn, f"{pfx}weekly_open_date") != monday:
        _set_state(conn, f"{pfx}weekly_open_balance", str(round(balance, 4)))
        _set_state(conn, f"{pfx}weekly_open_date", monday)

    peak = float(_get_state(conn, f"{pfx}peak_balance") or INITIAL_BALANCE)
    if balance > peak:
        _set_state(conn, f"{pfx}peak_balance", str(round(balance, 4)))


def _drawdown_mode(conn, pfx: str, balance: float) -> str:
    """
    Returns the current drawdown control mode for an account:
      'ok'        — trade normally
      'half_size' — daily loss 2-3%: halve new position sizes
      'halt'      — daily loss >3% or weekly loss >5%: no new entries, close all open
      'lockout'   — peak drawdown >10%: lock file written, must be deleted manually
    """
    if _is_locked_out(pfx):
        return "lockout"

    pt  = cfg().get("paper_trader", {})
    dd  = pt.get("drawdown", {})
    peak_pct    = dd.get("peak_lockout_pct",   0.10)
    daily_halt  = dd.get("daily_halt_pct",     0.03)
    daily_half  = dd.get("daily_half_size_pct", 0.02)
    weekly_halt = dd.get("weekly_halt_pct",    0.05)

    peak        = float(_get_state(conn, f"{pfx}peak_balance")         or INITIAL_BALANCE)
    daily_open  = float(_get_state(conn, f"{pfx}daily_open_balance")   or INITIAL_BALANCE)
    weekly_open = float(_get_state(conn, f"{pfx}weekly_open_balance")  or INITIAL_BALANCE)

    if peak > 0 and (peak - balance) / peak >= peak_pct:
        if not _is_locked_out(pfx):
            _write_lockout(
                pfx,
                f"Peak drawdown {(peak - balance) / peak:.1%} >= {peak_pct:.0%} limit "
                f"(peak={peak:.2f}, current={balance:.2f})",
                balance=balance,
                peak=peak,
            )
        return "lockout"

    if daily_open > 0 and (daily_open - balance) / daily_open >= daily_halt:
        logger.warning(
            f"Paper[{'indices' if pfx == 'idx_' else 'crypto'}]: daily drawdown "
            f"{(daily_open - balance) / daily_open:.1%} >= {daily_halt:.0%} — HALT"
        )
        return "halt"

    if weekly_open > 0 and (weekly_open - balance) / weekly_open >= weekly_halt:
        logger.warning(
            f"Paper[{'indices' if pfx == 'idx_' else 'crypto'}]: weekly drawdown "
            f"{(weekly_open - balance) / weekly_open:.1%} >= {weekly_halt:.0%} — HALT"
        )
        return "halt"

    if daily_open > 0 and (daily_open - balance) / daily_open >= daily_half:
        logger.info(
            f"Paper[{'indices' if pfx == 'idx_' else 'crypto'}]: daily drawdown "
            f"{(daily_open - balance) / daily_open:.1%} >= {daily_half:.0%} — HALF SIZE"
        )
        return "half_size"

    return "ok"


# ── Position management ───────────────────────────────────────────────────────

def _risk_pct_for_regime(regime: str) -> float:
    """Return the risk fraction for this regime, falling back to RISK_PCT."""
    pt = cfg().get("paper_trader", {})
    by_regime = pt.get("risk_pct_by_regime", {})
    default = pt.get("risk_pct_default", RISK_PCT)
    return by_regime.get(regime, default)


def _kelly_risk_pct(strategy: str, regime: str, direction: str, conn) -> float | None:
    """
    Compute half-Kelly position size from recent live trade history.

    Queries the last 60 days of resolved signals for this strategy+regime+direction,
    computes avg win R and avg loss R, derives full Kelly, returns half-Kelly.

    Returns None if insufficient data (< 20 resolved trades) so the caller
    can fall back to the fixed risk_pct.

    The half-Kelly fraction is capped at KELLY_MAX_RISK to prevent runaway sizing.
    """
    KELLY_MIN_TRADES = 20
    KELLY_MAX_RISK   = 0.03   # hard ceiling: never risk more than 3% per trade

    try:
        rows = conn.execute(
            """SELECT outcome, pnl_r FROM signals
               WHERE strategy=? AND regime=? AND direction=?
                 AND shadow_mode=0 AND outcome IS NOT NULL AND pnl_r IS NOT NULL
                 AND fired_at >= datetime('now', '-60 days')""",
            (strategy, regime, direction),
        ).fetchall()
    except Exception:
        return None

    wins   = [r["pnl_r"] for r in rows if r["outcome"] in ("win", "tp_hit") and r["pnl_r"] > 0]
    losses = [r["pnl_r"] for r in rows if r["outcome"] in ("loss", "stopped_out") and r["pnl_r"] < 0]
    resolved = len(wins) + len(losses)

    if resolved < KELLY_MIN_TRADES or not wins or not losses:
        return None

    win_rate  = len(wins) / resolved
    avg_win_r = sum(wins) / len(wins)
    avg_loss_r = abs(sum(losses) / len(losses))

    kelly = win_rate / avg_loss_r - (1 - win_rate) / avg_win_r
    if kelly <= 0:
        return None

    half_kelly = kelly / 2
    capped = min(half_kelly, KELLY_MAX_RISK)
    logger.debug(
        f"Kelly sizing: {strategy}/{regime}/{direction} "
        f"n={resolved} WR={win_rate:.0%} avgW={avg_win_r:.2f}R avgL=-{avg_loss_r:.2f}R "
        f"kelly={kelly:.3f} half={half_kelly:.3f} capped={capped:.3f}"
    )
    return capped


def open_position(conn, signal: dict, live_price: float) -> dict | None:
    """
    Attempt to open a paper position for a signal.
    Same-direction duplicate on the same pair is skipped.
    Opposite-direction signal closes the existing position and flips.
    Returns the position row dict on success, None if skipped.
    """
    pair        = signal["pair"]
    direction   = signal["direction"]
    exchange_id = signal.get("exchange", "mexc")
    _cb_pfx     = "idx_" if exchange_id == "tradenation" else ""

    # Circuit breaker gate (consecutive losses)
    if _circuit_breaker_active(conn, _cb_pfx):
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
        "SELECT * FROM paper_positions WHERE pair=? AND exchange=? AND exit_price IS NULL",
        (pair, exchange_id),
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
                     "BNB/USDT:USDT"}
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

    # Size on effective risk so actual $ loss on SL = target %, not larger.
    # Without this: slippage is accounted in PnL but not in sizing, so we're
    # implicitly over-leveraged vs our target risk fraction.
    # Index CFDs (Trade Nation) use spread-only pricing — no order-book slippage.
    _pt_cfg = cfg().get("paper_trader", {})
    if _pt_cfg.get("slip_adjust_sizing", False) and exchange_id != "tradenation":
        _entry_slip = _pt_cfg.get("entry_slippage_pct", 0.0005)
        _exit_slip  = _pt_cfg.get("slippage_pct", 0.0052)
        risk_per_contract += live_price * (_entry_slip + _exit_slip)

    free = get_free_balance_indices(conn) if exchange_id == "tradenation" else get_free_balance(conn)
    if free <= 0:
        logger.warning("Paper: no free balance — skipping")
        return None

    # Drawdown gate — check mode before sizing so half_size can reduce risk_pct
    _dd_mode = _drawdown_mode(conn, _cb_pfx, free)
    if _dd_mode in ("lockout", "halt"):
        logger.debug(
            f"Paper: drawdown mode={_dd_mode} — skipping signal {signal.get('id')}"
        )
        return None

    min_contract = MIN_CONTRACTS.get(pair, DEFAULT_MIN_CONTRACT)
    regime_label = signal.get("regime", "")

    _kelly_on = cfg().get("paper_trader", {}).get("kelly_sizing", False)
    if _kelly_on:
        _ks = _kelly_risk_pct(signal.get("strategy", ""), regime_label, direction, conn)
        if _ks is not None:
            risk_pct = _ks
            logger.debug(f"Paper: Kelly sizing active — risk_pct={risk_pct:.4f}")
        else:
            risk_pct = _risk_pct_for_regime(regime_label)
            logger.debug(f"Paper: Kelly insufficient data — fallback risk_pct={risk_pct:.4f}")
    else:
        risk_pct = _risk_pct_for_regime(regime_label)

    if _dd_mode == "half_size":
        risk_pct *= 0.5
        logger.debug(f"Paper: half-size drawdown mode — risk_pct={risk_pct:.4f}")

    # Macro regime multiplier — scale down in bear/crash cycles
    _macro_label, _macro_mult = _macro_risk_mult()
    if _macro_mult < 1.0:
        risk_pct *= _macro_mult
        logger.debug(
            f"Paper: macro regime={_macro_label} mult={_macro_mult:.0%} "
            f"— risk_pct={risk_pct:.4f}"
        )
    if risk_pct <= 0:
        logger.debug(
            f"Paper: macro regime={_macro_label} (mult=0) — skipping signal {signal.get('id')}"
        )
        return None
    risk_usdt     = free * risk_pct
    raw_contracts = risk_usdt / risk_per_contract
    max_contracts = (free * LEVERAGE) / live_price
    contracts     = max(min_contract, min(raw_contracts, max_contracts))
    contracts     = math.floor(contracts / min_contract) * min_contract  # round to lot
    if contracts < min_contract:
        logger.warning(f"Paper: contracts {contracts} below minimum for {pair} — skipping")
        return None

    # Fee-adjusted R gate: round-trip taker fees as a fraction of 1R.
    # Tight stops → high notional relative to risk → fees eat a large share of expected R.
    # Threshold 0.35R: at this level fee drag raises choppy BE WR by ~14pp (40→54%).
    _notional    = contracts * live_price
    _exc_id_fee  = signal.get("exchange", "mexc")
    _rt_fees     = _taker_rate(_exc_id_fee) * 2 * _notional
    _fee_r       = _rt_fees / risk_usdt if risk_usdt > 0 else 999.0
    _FEE_R_MAX   = 0.35
    if _fee_r > _FEE_R_MAX:
        logger.info(
            f"Paper: fee gate — {pair} {direction} {strategy} "
            f"fee_r={_fee_r:.3f}R (fees={_rt_fees:.2f} / risk={risk_usdt:.2f}) — skipping"
        )
        return None

    margin = (contracts * live_price) / LEVERAGE

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO paper_positions
           (signal_id, pair, direction, strategy, regime,
            entry_price, contracts, margin_usdt, stop_loss, take_profit, opened_at, exchange,
            risk_usdt_at_open)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (signal["id"], pair, direction, signal["strategy"], signal["regime"],
         live_price, contracts, margin, stop, tp, now, signal.get("exchange", "mexc"),
         round(risk_usdt, 4)),
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
        "margin_usdt": margin, "risk_usdt_at_open": round(risk_usdt, 4),
        "stop_loss": stop, "take_profit": tp,
        "opened_at": now, "exchange": signal.get("exchange", "mexc"),
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

    # ── Entry / exit slippage ─────────────────────────────────────────────────
    # Index CFDs trade at Trade Nation's quoted spread price — no order-book
    # gap slippage. Crypto CEX/perp orders incur market-impact slippage.
    is_index_cfd = (exchange_id == "tradenation")

    entry_slip_pct = 0.0 if is_index_cfd else pt.get("entry_slippage_pct", 0.0002)
    _actual_entry, entry_slip_cost = _calc_slippage(
        entry_price, contracts, direction, entry_slip_pct, side="entry"
    )

    market_exit_reasons = {"stop_loss", "timeout"}
    if reason in market_exit_reasons and not is_index_cfd:
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

    # ── Gap-risk cap — prevent single candle gap from exceeding N× intended risk ──
    max_loss_mult = pt.get("max_loss_mult", 3.0)
    risk_at_open = pos.get("risk_usdt_at_open") or (pos["margin_usdt"] * RISK_PCT)
    gap_cap = -(risk_at_open * max_loss_mult)
    if gross_pnl < gap_cap:
        logger.warning(
            f"Gap cap triggered on {pair}: gross_pnl {gross_pnl:.2f} → capped at {gap_cap:.2f} "
            f"(risk_at_open={risk_at_open:.2f} × {max_loss_mult})"
        )
        gross_pnl = gap_cap

    # ── Fees — entry taker; exit maker for TP, taker otherwise ───────────────
    fees_usdt = _calc_fees(entry_price, exit_price, contracts, exchange_id, reason)

    # ── Funding — crypto: 8h rate × intervals; CFD: daily 22:00 UTC cutoff ─────
    funding_usdt = _calc_funding(direction, contracts * entry_price, pos["opened_at"], pair, exchange_id)

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
    _cb_pfx = "idx_" if exchange_id == "tradenation" else ""
    _record_close_outcome(conn, net_pnl, _cb_pfx)

    # Refresh drawdown state so next open_position sees current balance
    _updated_balance = (get_free_balance_indices(conn) if exchange_id == "tradenation"
                        else get_free_balance(conn))
    _refresh_drawdown_state(conn, _cb_pfx, _updated_balance)

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


def poll_new_signals(conn, for_indices: bool = False) -> list[dict]:
    """Fetch new live signals for the crypto or indices account.

    Both accounts maintain an independent highwater mark. All new signals are
    scanned to advance the mark, then filtered to the correct account so
    neither account re-scans old rows on the next cycle.
    """
    state_key = "idx_last_signal_id" if for_indices else "last_signal_id"
    last_id = int(_get_state(conn, state_key))

    all_rows = conn.execute(
        "SELECT * FROM signals WHERE id > ? AND backtest_run_id IS NULL ORDER BY id",
        (last_id,),
    ).fetchall()
    if not all_rows:
        return []

    # Always advance cursor past all rows — prevents re-scan even if rows are stale.
    _set_state(conn, state_key, str(all_rows[-1]["id"]))

    # Drop signals whose candle fired more than 2 hours ago (e.g. backfilled history).
    # The paper trader prices positions at the current market price, so acting on
    # a signal from hours/days ago would fill at the wrong price.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    fresh_rows = []
    skipped = 0
    for row in all_rows:
        try:
            fired_str = dict(row).get("fired_at", "")
            fired_dt = datetime.fromisoformat(fired_str.replace("Z", "+00:00"))
            if fired_dt >= cutoff:
                fresh_rows.append(row)
            else:
                skipped += 1
        except Exception:
            fresh_rows.append(row)
    if skipped:
        logger.warning(f"poll_new_signals: skipped {skipped} stale signal(s) (fired_at > 2h ago)")

    if for_indices:
        return [dict(r) for r in fresh_rows if (dict(r).get("exchange") or "mexc") == "tradenation"]
    return [dict(r) for r in fresh_rows if (dict(r).get("exchange") or "mexc") != "tradenation"]


# ── Daily snapshot ────────────────────────────────────────────────────────────

def snapshot_day(conn, exchange_map: dict,
                 account_id: str = "crypto", exchange_filter: str | None = None) -> dict:
    """Capture end-of-day PnL snapshot for one account."""
    day_key = "idx_day_number" if account_id == "indices" else "day_number"
    day_number = int(_get_state(conn, day_key)) + 1

    exc_clause = "exchange = 'tradenation'" if account_id == "indices" else "exchange != 'tradenation'"

    free       = get_free_balance_indices(conn) if account_id == "indices" else get_free_balance(conn)
    unrealized = get_unrealized_pnl(conn, exchange_map, exchange_filter)
    equity     = free + unrealized

    realized_pnl = conn.execute(
        f"SELECT COALESCE(SUM(pnl_usdt), 0) FROM paper_positions WHERE exit_price IS NOT NULL AND {exc_clause}"
    ).fetchone()[0]
    open_count = conn.execute(
        f"SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NULL AND {exc_clause}"
    ).fetchone()[0]
    total_trades = conn.execute(
        f"SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL AND {exc_clause}"
    ).fetchone()[0]
    wins = conn.execute(
        f"SELECT COUNT(*) FROM paper_positions WHERE exit_price IS NOT NULL AND pnl_usdt >= 0 AND {exc_clause}"
    ).fetchone()[0]
    losses   = total_trades - wins
    win_rate = wins / total_trades if total_trades > 0 else None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO paper_daily_pnl
           (account_id, day_number, snapshot_date, balance_usdt, equity_usdt, realized_pnl,
            unrealized_pnl, open_positions, total_trades, wins, losses, win_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (account_id, day_number, today, free, equity, realized_pnl, unrealized,
         open_count, total_trades, wins, losses, win_rate),
    )
    conn.commit()
    _set_state(conn, day_key, str(day_number))

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

def _run_poll(conn, exchange_map: dict, for_indices: bool) -> None:
    """Shared poll logic for crypto and indices accounts."""
    acct = "indices" if for_indices else "crypto"
    exc_filter = "exchange = 'tradenation'" if for_indices else "exchange != 'tradenation'"
    _cb_pfx = "idx_" if for_indices else ""

    # Refresh daily/weekly open balance (handles day/week boundary resets)
    _current_balance = (get_free_balance_indices(conn) if for_indices
                        else get_free_balance(conn))
    _refresh_drawdown_state(conn, _cb_pfx, _current_balance)

    # Drawdown halt: close all open positions and skip new signals
    _dd_mode = _drawdown_mode(conn, _cb_pfx, _current_balance)
    if _dd_mode in ("lockout", "halt"):
        halt_rows = conn.execute(
            f"SELECT * FROM paper_positions WHERE exit_price IS NULL AND {exc_filter}"
        ).fetchall()
        if halt_rows:
            halt_prices = _fetch_tickers(exchange_map, halt_rows)
            for pos in halt_rows:
                exc_id = dict(pos).get("exchange") or "mexc"
                live = halt_prices.get((exc_id, pos["pair"]))
                if live:
                    close_position(conn, dict(pos), live, f"drawdown_{_dd_mode}")
            logger.warning(
                f"Paper[{acct}]: drawdown {_dd_mode} — closed {len(halt_rows)} position(s), "
                f"skipping new signals"
            )
        # Alert once per mode per day (lockout alert is sent inside _write_lockout)
        if _dd_mode == "halt":
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _alert_key = f"{_cb_pfx}halt_{_today}"
            if _alert_key not in _dd_alert_sent:
                _dd_alert_sent.add(_alert_key)
                try:
                    from alerts.telegram import send_drawdown_alert
                    _peak = float(_get_state(conn, f"{_cb_pfx}peak_balance") or INITIAL_BALANCE)
                    _d_open = float(_get_state(conn, f"{_cb_pfx}daily_open_balance") or INITIAL_BALANCE)
                    _w_open = float(_get_state(conn, f"{_cb_pfx}weekly_open_balance") or INITIAL_BALANCE)
                    send_drawdown_alert(acct, "halt", _current_balance, _peak, _d_open, _w_open)
                except Exception:
                    pass
        return

    # Alert for half-size mode (once per day)
    if _dd_mode == "half_size":
        _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _alert_key = f"{_cb_pfx}half_size_{_today}"
        if _alert_key not in _dd_alert_sent:
            _dd_alert_sent.add(_alert_key)
            try:
                from alerts.telegram import send_drawdown_alert
                _peak  = float(_get_state(conn, f"{_cb_pfx}peak_balance") or INITIAL_BALANCE)
                _d_open = float(_get_state(conn, f"{_cb_pfx}daily_open_balance") or INITIAL_BALANCE)
                send_drawdown_alert(acct, "half_size", _current_balance, _peak, _d_open)
            except Exception:
                pass

    # Check / close open positions for this account only
    rows = conn.execute(
        f"SELECT * FROM paper_positions WHERE exit_price IS NULL AND {exc_filter}"
    ).fetchall()
    if rows:
        prices = _fetch_tickers(exchange_map, rows)
        closed = timed_out = 0
        pt = cfg().get("paper_trader", {})
        timeout_h = pt.get("position_timeout_hours", 48)
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_h)).isoformat()
        for pos in rows:
            exc_id = pos["exchange"] if "exchange" in pos.keys() else "mexc"
            live = prices.get((exc_id, pos["pair"]))
            if live is None:
                logger.warning(f"Paper[{acct}]: no ticker for {pos['pair']} — skipping")
                continue
            conn.execute("UPDATE paper_positions SET last_price=? WHERE id=?", (live, pos["id"]))
            if pos["direction"] == "long":
                if live <= pos["stop_loss"]:
                    close_position(conn, dict(pos), live, "stop_loss"); closed += 1
                elif live >= pos["take_profit"]:
                    close_position(conn, dict(pos), live, "take_profit"); closed += 1
            else:
                if live >= pos["stop_loss"]:
                    close_position(conn, dict(pos), live, "stop_loss"); closed += 1
                elif live <= pos["take_profit"]:
                    close_position(conn, dict(pos), live, "take_profit"); closed += 1
            if pos["opened_at"] < cutoff and pos["id"] not in []:
                pass  # handled below
        conn.commit()
        if closed:
            logger.info(f"Paper[{acct}]: closed {closed} position(s) this tick")

    # Timeout check
    from datetime import timedelta
    pt = cfg().get("paper_trader", {})
    timeout_h = pt.get("position_timeout_hours", 48)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_h)).isoformat()
    timed_rows = conn.execute(
        f"SELECT * FROM paper_positions WHERE exit_price IS NULL AND opened_at < ? AND {exc_filter}",
        (cutoff,),
    ).fetchall()
    if timed_rows:
        prices_t = _fetch_tickers(exchange_map, timed_rows)
        for pos in timed_rows:
            exc_id = dict(pos).get("exchange") or "mexc"
            live = prices_t.get((exc_id, pos["pair"]))
            if live:
                close_position(conn, dict(pos), live, "timeout")
                logger.info(f"Paper[{acct}]: timeout close {pos['pair']}")

    # New signals
    signals = poll_new_signals(conn, for_indices=for_indices)
    for sig in signals:
        exc_id = sig.get("exchange", "mexc")
        exchange = exchange_map.get(exc_id) or next(iter(exchange_map.values()))
        ticker = fetch_ticker_safe(exchange, sig["pair"])
        if not ticker or not ticker.get("last"):
            logger.warning(f"Paper[{acct}]: no live price for {sig['pair']} signal {sig['id']} — skipping")
            continue
        open_position(conn, sig, float(ticker["last"]))


def poll_job(exchange_map: dict) -> None:
    with get_conn() as conn:
        _run_poll(conn, exchange_map, for_indices=False)


def poll_job_indices(exchange_map: dict) -> None:
    with get_conn() as conn:
        _run_poll(conn, exchange_map, for_indices=True)


def snapshot_job(exchange_map: dict) -> None:
    with get_conn() as conn:
        snapshot_day(conn, exchange_map, account_id="crypto")


def snapshot_job_indices(exchange_map: dict) -> None:
    with get_conn() as conn:
        snapshot_day(conn, exchange_map, account_id="indices", exchange_filter="tradenation")


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

    if cfg().get("indices", {}).get("enabled", False):
        try:
            from exchanges.index_reader import IndexReader
            exchange_map["tradenation"] = IndexReader()
            logger.info("Paper: IndexReader added for tradenation account")
        except Exception as e:
            logger.error(f"Paper: failed to init IndexReader: {e}")

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

    if "tradenation" in exchange_map:
        scheduler.add_job(
            poll_job_indices,
            "interval",
            minutes=15,
            args=[exchange_map],
            next_run_time=datetime.now(timezone.utc),
        )
        scheduler.add_job(
            snapshot_job_indices,
            "cron",
            hour=0,
            minute=1,
            args=[exchange_map],
        )
        logger.info("Paper: indices account (tradenation) scheduler jobs registered")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Paper trader stopped by user")


if __name__ == "__main__":
    main()
