"""
copy_trader.py — Shadow copy-trader following top Hyperliquid leaderboard traders.

Weekly:  refresh_leaderboard_job() — fetches 35K-row leaderboard, scores top 500
         wallets by composite formula, updates hl_candidates + copy_traders.
Daily:   score_candidates_job() — increments cycle counters, promotes/drops candidates.
Every N: poll_positions_job() — syncs open positions; closes timed-out positions;
         deactivates silent traders.

Budget: pool-based — each new position draws position_size_pct of current balance.
Stop-loss: auto-closes any position that loses > stop_loss_pct of its margin.
Max positions: hard cap via max_concurrent_positions.

Always shadow mode — no real execution regardless of global config flag.
Runs as 4th systemd service: mexc-copy-trader (starts at :07/:22/:37/:52).
"""
import sys
from math import log1p
from datetime import datetime, timedelta, timezone
from loguru import logger
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.config import get as cfg
from db.schema import get_conn
import os
from alerts.telegram import (
    send_copy_open_alert, send_copy_close_alert,
    send_convergence_alert, send_rotation_alert,
)

# ── API endpoints ─────────────────────────────────────────────────────────────

_HL_INFO   = "https://api.hyperliquid.xyz/info"
_HL_LEADER = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

_ARBISCAN_API      = "https://api.arbiscan.io/api"
_ARBISCAN_USDC     = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # native USDC on Arbitrum

# ── DB schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS copy_traders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet          TEXT NOT NULL UNIQUE,
    alias           TEXT,
    pnl_30d         REAL,
    tracked_since   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_refreshed  TIMESTAMP,
    active          INTEGER NOT NULL DEFAULT 1,
    silence_cycles  INTEGER NOT NULL DEFAULT 0
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
    open_fee_usdt   REAL DEFAULT 0,
    close_fee_usdt  REAL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS copy_account (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    balance    REAL NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hl_candidates (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet                   TEXT NOT NULL UNIQUE,
    composite_score          REAL NOT NULL,
    pnl_7d                   REAL,
    pnl_30d                  REAL,
    trade_count_30d          INTEGER,
    roi_7d                   REAL,
    cycles_above_threshold   INTEGER NOT NULL DEFAULT 0,
    first_seen               TIMESTAMP NOT NULL,
    promoted_at              TIMESTAMP,
    dropped_at               TIMESTAMP,
    status                   TEXT NOT NULL DEFAULT 'watching'
);

CREATE TABLE IF NOT EXISTS wallet_graph (
    wallet           TEXT NOT NULL,
    funder_address   TEXT NOT NULL,
    chain            TEXT NOT NULL DEFAULT 'arbitrum',
    detected_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (wallet, funder_address)
);
"""


def init_copy_db(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
    # Migrations for columns added after initial production schema
    for migration in [
        "ALTER TABLE copy_traders ADD COLUMN silence_cycles INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE copy_positions ADD COLUMN open_fee_usdt REAL DEFAULT 0",
        "ALTER TABLE copy_positions ADD COLUMN close_fee_usdt REAL DEFAULT 0",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass  # column already exists — safe to ignore
    c = cfg().get("copy_trader", {})
    initial = float(c.get("initial_balance", 10_000))
    if conn.execute("SELECT COUNT(*) FROM copy_account").fetchone()[0] == 0:
        _set_copy_balance(conn, initial)
        conn.commit()
    elif c.get("reset_balance", False):
        open_pos = conn.execute(
            "SELECT COUNT(*) FROM copy_positions WHERE closed_at IS NULL"
        ).fetchone()[0]
        if open_pos == 0:
            _set_copy_balance(conn, initial)
            conn.commit()
            logger.info(f"Balance reset to ${initial:,.2f} (reset_balance=true, no open positions)")
        else:
            logger.warning(f"reset_balance=true ignored — {open_pos} open position(s) still active")


# ── Balance helpers ────────────────────────────────────────────────────────────

def get_copy_balance(conn) -> float:
    row = conn.execute("SELECT balance FROM copy_account WHERE id=1").fetchone()
    return row["balance"] if row else 0.0


def _set_copy_balance(conn, balance: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO copy_account (id, balance, updated_at) VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
        (round(balance, 4), now),
    )


def _adjust_copy_balance(conn, delta: float) -> None:
    _set_copy_balance(conn, get_copy_balance(conn) + delta)


# ── HL API helpers ─────────────────────────────────────────────────────────────

def _composite_score(pnl_7d: float, pnl_30d: float, trade_count_30d: int, roi_7d: float) -> float:
    """
    Composite leaderboard score across time windows.
    All terms use log1p(value / baseline_unit) so each contributes ~0.69 at baseline.
    Baselines: $5K 7d PnL, $20K 30d PnL, 5 trades, 1% ROI.
    """
    # API may return roi as percentage (5.0) or decimal (0.05) — normalise to decimal
    if roi_7d > 1.0:
        roi_7d = roi_7d / 100.0
    return round(
        0.40 * log1p(max(0.0, pnl_7d) / 5_000) +
        0.30 * log1p(max(0.0, pnl_30d) / 20_000) +
        0.15 * log1p(max(0.0, trade_count_30d) / 5) +
        0.15 * log1p(max(0.0, roi_7d * 100)),
        4,
    )


def fetch_leaderboard(min_pnl: float, top_n: int) -> tuple[list[dict], int]:
    """
    Downloads the full HL leaderboard and returns:
      (scored_rows, raw_count)

    scored_rows: all wallets with pnl_30d >= min_pnl, sorted descending by composite
                 score. Each entry: {wallet, alias, pnl_7d, pnl_30d, trade_count_30d,
                 roi_7d, composite_score}.
    raw_count:   total rows returned by the API (used for outage guard).
    Returns ([], 0) on network error.
    """
    try:
        resp = requests.get(_HL_LEADER, timeout=20)
        resp.raise_for_status()
        raw_rows = resp.json().get("leaderboardRows", [])
    except Exception as e:
        logger.error(f"Leaderboard fetch failed: {e}")
        return [], 0

    raw_count = len(raw_rows)
    _roi_logged = False
    result = []

    for row in raw_rows:
        wallet = row.get("ethAddress")
        if not wallet:
            continue

        pnl_7d = pnl_30d = roi_7d = None
        trade_count = 0
        for window, stats in row.get("windowPerformances", []):
            if window == "week":
                pnl_7d = float(stats.get("pnl", 0) or 0)
                raw_roi = float(stats.get("roi", 0) or 0)
                if not _roi_logged:
                    logger.debug(f"Leaderboard roi raw sample: {raw_roi} (wallet {wallet[:10]}…)")
                    _roi_logged = True
                roi_7d = raw_roi
            elif window == "month":
                pnl_30d = float(stats.get("pnl", 0) or 0)
                trade_count = int(float(stats.get("vlm", 0) or 0))  # vlm is USD volume float

        if pnl_30d is None or pnl_30d < min_pnl:
            continue

        score = _composite_score(
            pnl_7d or 0.0, pnl_30d, trade_count, roi_7d or 0.0
        )
        result.append({
            "wallet": wallet,
            "alias": row.get("displayName"),
            "pnl_7d": pnl_7d or 0.0,
            "pnl_30d": pnl_30d,
            "trade_count_30d": trade_count,
            "roi_7d": roi_7d or 0.0,
            "composite_score": score,
        })

    result.sort(key=lambda r: r["composite_score"], reverse=True)
    return result, raw_count


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


def _pair_to_coin(pair: str) -> str:
    return pair.split("/")[0]


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


def _copy_open(
    conn, wallet: str, coin: str, pos: dict,
    position_size_pct: float, max_concurrent: int, min_position_usdt: float = 15.0,
) -> None:
    open_count = conn.execute(
        "SELECT COUNT(*) FROM copy_positions WHERE closed_at IS NULL"
    ).fetchone()[0]
    if open_count >= max_concurrent:
        logger.warning(f"Max concurrent positions ({max_concurrent}) reached — skipping {coin}")
        return

    balance = get_copy_balance(conn)
    margin_usdt = round(balance * position_size_pct, 2)
    if margin_usdt < min_position_usdt:
        logger.warning(f"Position size ${margin_usdt:.2f} below minimum ${min_position_usdt:.0f} — skipping {coin}")
        return

    fee_pct = float(cfg().get("copy_trader", {}).get("taker_fee_pct", 0.0005))
    entry = pos["entryPx"]
    contracts = (margin_usdt / entry) if entry > 0 else 0.0
    open_fee = round(margin_usdt * fee_pct, 4)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO copy_positions
           (trader_wallet, pair, direction, entry_price, last_price, contracts, margin_usdt, open_fee_usdt, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (wallet, _coin_to_pair(coin), pos["side"], entry, entry,
         round(contracts, 8), margin_usdt, open_fee, now),
    )
    _adjust_copy_balance(conn, -(margin_usdt + open_fee))
    conn.commit()
    balance_after = get_copy_balance(conn)
    logger.info(
        f"Copy OPEN  {wallet[:10]}… {coin} {pos['side'].upper()} "
        f"@ {entry} margin=${margin_usdt:.0f} fee=${open_fee:.4f} contracts={contracts:.6f}"
    )
    send_copy_open_alert(wallet, coin, pos["side"], margin_usdt, entry, balance_after)

    # Check for convergent algo signal within correlation window
    window_h = int(cfg().get("correlation_window_hours", 4))
    sig = conn.execute(
        """SELECT id, strategy, fired_at FROM signals
           WHERE pair LIKE ? AND direction=?
             AND backtest_run_id IS NULL
             AND fired_at >= datetime(?, ?)
             AND fired_at <= datetime(?, ?)
           ORDER BY fired_at DESC LIMIT 1""",
        (f"{coin}/%", pos["side"], now, f"-{window_h} hours", now, f"+{window_h} hours"),
    ).fetchone()
    if sig:
        logger.info(f"Convergence: {coin} {pos['side']} copy + signal [{sig['strategy']}]")
        send_convergence_alert(wallet, coin, pos["side"], now, sig["strategy"], sig["fired_at"])


def _copy_close(conn, wallet: str, coin: str, exit_price: float, reason: str) -> None:
    pair = _coin_to_pair(coin)
    row = conn.execute(
        """SELECT id, direction, entry_price, contracts, margin_usdt
           FROM copy_positions
           WHERE trader_wallet=? AND pair=? AND closed_at IS NULL
           ORDER BY opened_at DESC LIMIT 1""",
        (wallet, pair),
    ).fetchone()
    if row is None:
        return

    fee_pct = float(cfg().get("copy_trader", {}).get("taker_fee_pct", 0.0005))
    direction_sign = 1 if row["direction"] == "long" else -1
    gross_pnl = (exit_price - row["entry_price"]) * (row["contracts"] or 0.0) * direction_sign
    close_fee = round((row["contracts"] or 0.0) * exit_price * fee_pct, 4)
    pnl = gross_pnl - close_fee
    margin = row["margin_usdt"] or 0.0
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """UPDATE copy_positions
           SET exit_price=?, last_price=?, pnl_usdt=?, close_fee_usdt=?, closed_at=?, exit_reason=?
           WHERE id=?""",
        (exit_price, exit_price, round(pnl, 4), close_fee, now, reason, row["id"]),
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO copy_daily_pnl (date, pnl_usdt) VALUES (?, ?)
           ON CONFLICT(date) DO UPDATE SET pnl_usdt = pnl_usdt + excluded.pnl_usdt""",
        (today, round(pnl, 4)),
    )
    _adjust_copy_balance(conn, margin + pnl)
    conn.commit()
    balance_after = get_copy_balance(conn)
    outcome = "WIN" if pnl >= 0 else "LOSS"
    logger.info(
        f"Copy CLOSE {wallet[:10]}… {coin} {row['direction'].upper()} "
        f"exit={exit_price} reason={reason} pnl={pnl:+.2f} fee=${close_fee:.4f} [{outcome}]"
    )
    send_copy_close_alert(
        wallet, coin, row["direction"],
        row["entry_price"], exit_price,
        pnl, margin, reason, balance_after,
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
    top_n           = int(c.get("top_n", 5))
    min_pnl         = float(c.get("min_pnl_30d", 10_000))
    min_raw_rows    = int(c.get("min_leaderboard_rows", 10_000))
    score_threshold = float(c.get("candidate_score_threshold", 2.0))
    max_candidates  = int(c.get("max_candidates", 50))

    scored, raw_count = fetch_leaderboard(min_pnl, top_n=999_999)
    if raw_count < min_raw_rows:
        logger.warning(
            f"Leaderboard returned only {raw_count} raw rows (expected >={min_raw_rows}) "
            f"— skipping refresh to protect candidate state"
        )
        return
    if not scored:
        logger.warning("Leaderboard refresh: no qualifying traders above min_pnl")
        return

    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        # ── Update active copy_traders (top-N by composite score) ─────────────
        # Scope deactivation to wallets NOT promoted from hl_candidates — they
        # should remain active across weekly refreshes.
        conn.execute("""
            UPDATE copy_traders SET active=0
            WHERE wallet NOT IN (
                SELECT wallet FROM hl_candidates WHERE status='promoted'
            )
        """)
        for t in scored[:top_n]:
            conn.execute(
                """INSERT INTO copy_traders (wallet, alias, pnl_30d, last_refreshed, active)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(wallet) DO UPDATE SET
                     alias=excluded.alias, pnl_30d=excluded.pnl_30d,
                     last_refreshed=excluded.last_refreshed, active=1""",
                (t["wallet"], t["alias"], t["pnl_30d"], now),
            )
        conn.commit()

        # ── Update hl_candidates (top 500 above score threshold) ──────────────
        candidates = [t for t in scored if t["composite_score"] >= score_threshold][:500]
        candidate_wallets = {t["wallet"] for t in candidates}

        for t in candidates:
            conn.execute(
                """INSERT INTO hl_candidates
                     (wallet, composite_score, pnl_7d, pnl_30d, trade_count_30d, roi_7d,
                      cycles_above_threshold, first_seen, status)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'watching')
                   ON CONFLICT(wallet) DO UPDATE SET
                     composite_score=excluded.composite_score,
                     pnl_7d=excluded.pnl_7d,
                     pnl_30d=excluded.pnl_30d,
                     trade_count_30d=excluded.trade_count_30d,
                     roi_7d=excluded.roi_7d
                   WHERE status='watching'""",
                (t["wallet"], t["composite_score"], t["pnl_7d"], t["pnl_30d"],
                 t["trade_count_30d"], t["roi_7d"], now),
            )

        # Drop wallets that fell out of the scored set entirely
        conn.execute(
            """UPDATE hl_candidates SET status='dropped', dropped_at=?
               WHERE status='watching'
                 AND wallet NOT IN ({})""".format(
                ",".join("?" * len(candidate_wallets))
            ),
            [now] + list(candidate_wallets),
        )

        # Trim to max_candidates if exceeded (evict lowest-scored watching wallets)
        watching = conn.execute(
            """SELECT wallet FROM hl_candidates WHERE status='watching'
               ORDER BY composite_score DESC"""
        ).fetchall()
        if len(watching) > max_candidates:
            evict = [r["wallet"] for r in watching[max_candidates:]]
            conn.execute(
                "UPDATE hl_candidates SET status='dropped', dropped_at=? WHERE wallet IN ({})".format(
                    ",".join("?" * len(evict))
                ),
                [now] + evict,
            )
            logger.info(f"Evicted {len(evict)} lowest-scored candidates (max_candidates={max_candidates})")

        conn.commit()

    logger.info(
        f"Leaderboard refreshed | active={min(top_n, len(scored))} "
        f"top={scored[0]['wallet'][:12]}… "
        f"score={scored[0]['composite_score']:.2f} "
        f"candidates={len(candidates)} raw_rows={raw_count}"
    )


def _fetch_arbiscan_funder(wallet: str, api_key: str) -> str | None:
    """Return the first USDC sender to this wallet on Arbitrum, or None on error/not-found."""
    params = {
        "module": "account",
        "action": "tokentx",
        "address": wallet,
        "contractaddress": _ARBISCAN_USDC,
        "sort": "asc",
        "page": "1",
        "offset": "5",
    }
    if api_key:
        params["apikey"] = api_key
    try:
        resp = requests.get(_ARBISCAN_API, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1":
            return None
        for tx in data.get("result", []):
            if tx.get("to", "").lower() == wallet.lower():
                return tx.get("from", "").lower()
    except Exception as e:
        logger.warning(f"Arbiscan lookup failed for {wallet[:12]}…: {e}")
    return None


def _run_arbiscan_lookups(conn, c: dict) -> None:
    """Fetch Arbiscan funder for up to 3 new watching candidates per daily cycle.
    Fast-tracks candidates whose funder matches an already-promoted wallet's funder."""
    api_key = os.environ.get("ARBISCAN_API_KEY") or c.get("arbiscan_api_key", "")
    promote_cycles = int(c.get("candidate_promote_cycles", 3))
    now = datetime.now(timezone.utc).isoformat()

    # Candidates not yet in wallet_graph (sentinel "" counts as looked-up)
    new_cands = conn.execute(
        """SELECT wallet FROM hl_candidates
           WHERE status='watching'
             AND wallet NOT IN (SELECT wallet FROM wallet_graph)
           LIMIT 3"""
    ).fetchall()

    if not new_cands:
        return

    # Funder → wallet map for already-promoted wallets
    promoted_funders: dict[str, str] = {
        r["funder_address"]: r["wallet"]
        for r in conn.execute(
            """SELECT wg.funder_address, wg.wallet
               FROM wallet_graph wg
               JOIN hl_candidates hc ON hc.wallet = wg.wallet
               WHERE hc.status = 'promoted' AND wg.funder_address != ''"""
        ).fetchall()
    }

    for row in new_cands:
        wallet = row["wallet"]
        funder = _fetch_arbiscan_funder(wallet, api_key)
        # Record result — empty string = looked up but no funder found (sentinel)
        conn.execute(
            """INSERT OR REPLACE INTO wallet_graph (wallet, funder_address, chain, detected_at)
               VALUES (?, ?, 'arbitrum', ?)""",
            (wallet, funder or "", now),
        )
        conn.commit()

        if funder and funder in promoted_funders:
            known_wallet = promoted_funders[funder]
            conn.execute(
                "UPDATE hl_candidates SET cycles_above_threshold=? WHERE wallet=?",
                (promote_cycles, wallet),
            )
            conn.commit()
            logger.info(
                f"Rotation detected: {wallet[:12]}… funded by same source as "
                f"{known_wallet[:12]}… — fast-tracked ({promote_cycles} cycles)"
            )
            send_rotation_alert(wallet, known_wallet, funder)


def score_candidates_job() -> None:
    """Daily: increment cycle counters, promote/drop hl_candidates."""
    c = cfg().get("copy_trader", {})
    score_threshold   = float(c.get("candidate_score_threshold", 2.0))
    promote_cycles    = int(c.get("candidate_promote_cycles", 3))
    drop_cycles       = int(c.get("candidate_drop_cycles", 2))

    now = datetime.now(timezone.utc).isoformat()
    promoted = dropped = 0

    with get_conn() as conn:
        candidates = conn.execute(
            "SELECT * FROM hl_candidates WHERE status='watching'"
        ).fetchall()

        for cand in candidates:
            wallet = cand["wallet"]
            score = cand["composite_score"]
            cycles = cand["cycles_above_threshold"]

            if score >= score_threshold:
                new_cycles = cycles + 1
                conn.execute(
                    "UPDATE hl_candidates SET cycles_above_threshold=? WHERE wallet=?",
                    (new_cycles, wallet),
                )
                if new_cycles >= promote_cycles:
                    # Promote: add to copy_traders if not already there
                    conn.execute(
                        """INSERT INTO copy_traders (wallet, alias, pnl_30d, last_refreshed, active)
                           VALUES (?, ?, ?, ?, 1)
                           ON CONFLICT(wallet) DO UPDATE SET active=1, last_refreshed=excluded.last_refreshed""",
                        (wallet, None, cand["pnl_30d"], now),
                    )
                    conn.execute(
                        "UPDATE hl_candidates SET status='promoted', promoted_at=? WHERE wallet=?",
                        (now, wallet),
                    )
                    promoted += 1
                    logger.info(
                        f"Candidate PROMOTED {wallet[:12]}… "
                        f"score={score:.2f} cycles={new_cycles}"
                    )
            else:
                # Below threshold — check consecutive drop cycles
                # We reuse cycles_above_threshold as a negative counter when score drops
                # To track consecutive drops, reset to 0 when below, count down from promote threshold
                # Simple approach: if score drops below threshold, decrement cycles toward 0;
                # if cycles reach -drop_cycles, mark dropped.
                new_cycles = cycles - 1
                conn.execute(
                    "UPDATE hl_candidates SET cycles_above_threshold=? WHERE wallet=?",
                    (new_cycles, wallet),
                )
                if new_cycles <= -drop_cycles:
                    conn.execute(
                        "UPDATE hl_candidates SET status='dropped', dropped_at=? WHERE wallet=?",
                        (now, wallet),
                    )
                    dropped += 1
                    logger.info(
                        f"Candidate DROPPED {wallet[:12]}… "
                        f"score={score:.2f} cycles={new_cycles}"
                    )

        conn.commit()

    if promoted or dropped:
        logger.info(f"Score candidates: promoted={promoted} dropped={dropped}")
    else:
        logger.debug("Score candidates: no promotions or drops this cycle")

    # Run Arbiscan lookups for new candidates (max 3 per cycle, rate-limited)
    with get_conn() as conn:
        _run_arbiscan_lookups(conn, c)


def _check_copy_timeouts(conn, mids: dict) -> int:
    """Close copy positions that have been open longer than position_timeout_hours.
    Returns the number of positions closed."""
    c = cfg().get("copy_trader", {})
    timeout_h = int(c.get("position_timeout_hours", 24))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_h)).isoformat()

    stale = conn.execute(
        """SELECT trader_wallet, pair FROM copy_positions
           WHERE closed_at IS NULL AND opened_at < ?""",
        (cutoff,),
    ).fetchall()

    closed = 0
    for pos in stale:
        coin = _pair_to_coin(pos["pair"])
        live = mids.get(coin)
        if live:
            _copy_close(conn, pos["trader_wallet"], coin, live, "timeout")
            closed += 1
        else:
            logger.warning(f"Timeout: no live price for {coin} — skipping close")

    if closed:
        logger.info(f"Timeout: closed {closed} stale position(s) (>{timeout_h}h)")
    return closed


def poll_positions_job() -> None:
    c = cfg().get("copy_trader", {})
    position_size_pct  = float(c.get("position_size_pct", 0.05))
    stop_loss_pct      = float(c.get("stop_loss_pct", 0.20))
    max_concurrent     = int(c.get("max_concurrent_positions", 15))
    min_position_usdt  = float(c.get("min_position_usdt", 15.0))
    silence_threshold  = int(c.get("trader_silence_threshold", 3))

    mids = fetch_all_mids()
    if not mids:
        logger.warning("allMids empty — skipping poll cycle")
        return

    # ── Close positions that have exceeded the timeout ─────────────────────────
    with get_conn() as conn:
        _check_copy_timeouts(conn, mids)

    with get_conn() as conn:
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
            # ── Silence detection ──────────────────────────────────────────────
            if positions == {}:
                row = conn.execute(
                    "SELECT silence_cycles FROM copy_traders WHERE wallet=?", (wallet,)
                ).fetchone()
                if row is not None:
                    new_silence = row["silence_cycles"] + 1
                    conn.execute(
                        "UPDATE copy_traders SET silence_cycles=? WHERE wallet=?",
                        (new_silence, wallet),
                    )
                    conn.commit()
                    if new_silence >= silence_threshold:
                        # Deactivate trader and close all their open positions
                        open_coins = conn.execute(
                            """SELECT pair FROM copy_positions
                               WHERE trader_wallet=? AND closed_at IS NULL""",
                            (wallet,),
                        ).fetchall()
                        for p in open_coins:
                            coin = _pair_to_coin(p["pair"])
                            live = mids.get(coin, 0.0)
                            if live:
                                _copy_close(conn, wallet, coin, live, "trader_silent")
                        conn.execute(
                            "UPDATE copy_traders SET active=0, silence_cycles=0 WHERE wallet=?",
                            (wallet,),
                        )
                        conn.commit()
                        logger.info(
                            f"Trader SILENCED {wallet[:12]}… "
                            f"({new_silence} consecutive empty polls) — deactivated"
                        )
                continue  # no positions to diff

            # Reset silence counter when positions are present
            conn.execute(
                "UPDATE copy_traders SET silence_cycles=0 WHERE wallet=?", (wallet,)
            )

            previous = load_copy_state(conn, wallet)

            # ── Stop-loss check on active (non-stopped) copy positions ─────────
            sl_closed: set[str] = set()
            for coin, prev_pos in previous.items():
                if prev_pos["side"] == "stopped":
                    continue
                last_price = mids.get(coin, 0.0)
                entry_px   = prev_pos["entryPx"]
                if last_price <= 0 or entry_px <= 0:
                    continue
                direction_sign = 1 if prev_pos["side"] == "long" else -1
                pct_move = (last_price - entry_px) / entry_px * direction_sign
                if pct_move < -stop_loss_pct:
                    logger.info(
                        f"Stop-loss triggered {wallet[:10]}… {coin} "
                        f"move={pct_move*100:.1f}%"
                    )
                    _copy_close(conn, wallet, coin, last_price, "stop_loss")
                    sl_closed.add(coin)

            # ── Position diff ─────────────────────────────────────────────────
            for coin, pos in positions.items():
                last_price = mids.get(coin, 0.0)
                prev = previous.get(coin)

                if prev is None:
                    _copy_open(conn, wallet, coin, pos, position_size_pct, max_concurrent, min_position_usdt)
                elif prev["side"] == "stopped" or coin in sl_closed:
                    pass  # stopped out — don't re-enter while trader holds same position
                elif pos["side"] != prev["side"]:
                    _copy_close(conn, wallet, coin, last_price, "trader_reversed")
                    _copy_open(conn, wallet, coin, pos, position_size_pct, max_concurrent, min_position_usdt)
                else:
                    _update_last_price(conn, wallet, coin, last_price)

            # ── Detect closes ─────────────────────────────────────────────────
            for coin, prev_pos in previous.items():
                if coin not in positions:
                    if prev_pos["side"] != "stopped":
                        last_price = mids.get(coin, 0.0)
                        _copy_close(conn, wallet, coin, last_price, "trader_closed")

            # ── Persist new state ─────────────────────────────────────────────
            new_state: dict = {}
            for coin, pos in positions.items():
                if coin in sl_closed or previous.get(coin, {}).get("side") == "stopped":
                    new_state[coin] = {"side": "stopped", "size": pos["size"], "entryPx": pos["entryPx"]}
                else:
                    new_state[coin] = pos
            save_copy_state(conn, wallet, new_state)

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
        f"budget=${float(c.get('initial_balance', 10_000)):,.0f} "
        f"pos_size={float(c.get('position_size_pct', 0.05))*100:.0f}% "
        f"sl={float(c.get('stop_loss_pct', 0.20))*100:.0f}% "
        f"max_pos={c.get('max_concurrent_positions', 15)} "
        f"min_30d_pnl=${float(c.get('min_pnl_30d', 10_000)):,.0f} "
        f"timeout_h={c.get('position_timeout_hours', 24)}"
    )

    refresh_leaderboard_job()

    scheduler = BlockingScheduler(timezone="UTC")

    poll_interval = int(c.get("poll_interval_minutes", 2))
    scheduler.add_job(
        poll_positions_job,
        "interval",
        minutes=poll_interval,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        refresh_leaderboard_job,
        CronTrigger(day_of_week="sun", hour=0, minute=0, timezone="UTC"),
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        score_candidates_job,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        misfire_grace_time=3600,
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Copy trader stopped by user")


if __name__ == "__main__":
    main()
