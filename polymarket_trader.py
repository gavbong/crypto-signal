"""
polymarket_trader.py — Shadow copy-trader following top Polymarket prediction market traders.

Weekly (Sunday 00:30 UTC): refreshes top N traders by 30d PnL from Polymarket leaderboard.
Every 15 min (:03/:18/:33/:48): polls their open positions, copies opens/closes/resolutions.

Always shadow mode — no real execution.
5th systemd service: mexc-poly-trader.
"""
import sys
import re
import json
import requests
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.config import get as cfg
from db.schema import get_conn
from alerts.telegram import send_poly_open_alert, send_poly_close_alert

_PM_POSITIONS  = "https://data-api.polymarket.com/positions"
_GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"

_CRYPTO   = {'crypto','bitcoin','btc','ethereum','eth','defi','solana','sol','xrp','bnb','doge'}
_POLITICS = {'politics','election','trump','biden','congress','president','vote','senate','harris'}
_SPORTS   = {'sports','nba','nfl','soccer','tennis','football','basketball','nhl','mlb','ufc'}
_TICKER_RE = re.compile(r'\b(BTC|ETH|SOL|XRP|BNB|DOGE|ADA|AVAX|MATIC|DOT|LINK)\b', re.I)

# ── DB schema ──────────────────────────────────────────────────────────────────

_POLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS poly_traders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet          TEXT NOT NULL UNIQUE,
    alias           TEXT,
    pnl_30d         REAL,
    volume_30d      REAL,
    tracked_since   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_refreshed  TIMESTAMP,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS poly_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trader_wallet   TEXT NOT NULL,
    market_id       TEXT NOT NULL,
    yes_token_id    TEXT,
    market_title    TEXT,
    category        TEXT,
    outcome         TEXT NOT NULL,
    shares          REAL NOT NULL,
    entry_price     REAL NOT NULL,
    current_price   REAL,
    exit_price      REAL,
    cost_basis      REAL NOT NULL,
    pnl_usdt        REAL,
    end_date        TEXT,
    opened_at       TIMESTAMP NOT NULL,
    closed_at       TIMESTAMP,
    exit_reason     TEXT
);

CREATE TABLE IF NOT EXISTS poly_state (
    trader_wallet   TEXT NOT NULL,
    market_id       TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    side            TEXT NOT NULL,
    PRIMARY KEY (trader_wallet, market_id, outcome)
);

CREATE TABLE IF NOT EXISTS poly_account (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    balance         REAL NOT NULL,
    initial_balance REAL NOT NULL,
    realized_pnl    REAL NOT NULL DEFAULT 0.0,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP
);
"""


def init_poly_db(conn) -> None:
    conn.executescript(_POLY_SCHEMA)
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM poly_account").fetchone()[0] == 0:
        initial = float(cfg().get("polymarket_trader", {}).get("initial_balance", 10_000))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO poly_account (id, balance, initial_balance, updated_at) VALUES (1, ?, ?, ?)",
            (initial, initial, now),
        )
        conn.commit()


# ── Balance helpers ────────────────────────────────────────────────────────────

def get_poly_balance(conn) -> float:
    row = conn.execute("SELECT balance FROM poly_account WHERE id=1").fetchone()
    return row["balance"] if row else 0.0


def _set_poly_balance(conn, balance: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO poly_account (id, balance, initial_balance, updated_at)
           VALUES (1, ?, 0, ?)
           ON CONFLICT(id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
        (round(balance, 4), now),
    )


def _adjust_poly_balance(conn, delta: float) -> None:
    _set_poly_balance(conn, get_poly_balance(conn) + delta)


# ── API helpers ────────────────────────────────────────────────────────────────

_PM_LEADERBOARD_PAGE = "https://polymarket.com/leaderboard"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL)


def fetch_poly_leaderboard(top_n: int, min_pnl: float, volume_floor: float) -> list[dict]:
    """
    Scrapes __NEXT_DATA__ from polymarket.com/leaderboard — no auth needed.
    Polymarket embeds the first-page leaderboard rows in the page HTML as JSON.
    """
    try:
        resp = requests.get(
            _PM_LEADERBOARD_PAGE,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=25,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"PM leaderboard page fetch failed: {e}")
        return []

    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        logger.error("PM leaderboard: __NEXT_DATA__ not found in page HTML")
        return []

    try:
        page_data = json.loads(m.group(1))
    except Exception as e:
        logger.error(f"PM leaderboard: __NEXT_DATA__ JSON parse failed: {e}")
        return []

    # Navigate: props.pageProps.dehydratedState.queries[n].state.data
    rows = []
    queries = (
        page_data.get("props", {})
                 .get("pageProps", {})
                 .get("dehydratedState", {})
                 .get("queries", [])
    )
    for q in queries:
        candidates = q.get("state", {}).get("data", [])
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict) \
                and "proxyWallet" in candidates[0]:
            rows = candidates
            break

    if not rows:
        logger.error("PM leaderboard: leaderboard rows not found in __NEXT_DATA__")
        return []

    result = []
    for row in rows:
        wallet = row.get("proxyWallet")
        if not wallet:
            continue
        pnl = float(row.get("pnl") or 0)
        vol = float(row.get("volume") or row.get("amount") or 0)
        if pnl < min_pnl or vol < volume_floor:
            continue
        alias = row.get("name") or row.get("pseudonym")
        result.append({"wallet": wallet, "pnl_30d": pnl, "volume_30d": vol, "alias": alias})

    result.sort(key=lambda r: r["pnl_30d"], reverse=True)
    logger.info(f"PM leaderboard scraped: {len(rows)} total, {len(result)} qualify")
    return result[:top_n]


def fetch_poly_positions(wallet: str) -> list[dict] | None:
    try:
        resp = requests.get(_PM_POSITIONS, params={"user": wallet}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("data") or data.get("positions") or []
    except Exception as e:
        logger.warning(f"PM positions failed for {wallet[:12]}…: {e}")
        return None

    result = []
    for item in data:
        market_id = item.get("conditionId") or item.get("condition_id")
        if not market_id:
            continue
        outcome = str(item.get("outcome") or "YES").upper()
        if outcome not in ("YES", "NO"):
            continue
        size      = float(item.get("size") or item.get("amount") or 0)
        avg_price = float(item.get("avgPrice") or item.get("avg_price") or 0)
        if size <= 0 or avg_price < 0.01:
            continue
        title = str(item.get("title") or item.get("question") or "")[:200]
        tags  = item.get("tags") or []
        # For YES positions the `asset` field is the YES token ID directly
        asset = item.get("asset")
        yes_token_id = asset if outcome == "YES" else None
        result.append({
            "market_id": market_id,
            "outcome": outcome,
            "size": size,
            "avg_price": avg_price,
            "title": title,
            "tags": tags,
            "yes_token_id": yes_token_id,
        })
    return result


def fetch_market_meta(market_id: str) -> dict | None:
    try:
        resp = requests.get(_GAMMA_MARKETS, params={"conditionId": market_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            data = data[0] if data else {}
    except Exception as e:
        logger.warning(f"Gamma meta failed for {market_id[:12]}…: {e}")
        return None

    yes_token_id = None
    tokens = data.get("tokens") or data.get("clobTokenIds") or []
    for tok in tokens:
        if isinstance(tok, dict):
            oc = str(tok.get("outcome", "")).upper()
            if oc in ("YES", "YES "):
                yes_token_id = tok.get("token_id") or tok.get("tokenId")
                break
    # Fallback: tokens might be a plain list [yes_id, no_id]
    if yes_token_id is None and tokens and isinstance(tokens[0], str):
        yes_token_id = tokens[0]

    title = str(data.get("question") or data.get("title") or "")[:200]
    tags  = data.get("tags") or []
    if tags and isinstance(tags[0], dict):
        tags = [t.get("label") or t.get("name") or "" for t in tags]

    resolved         = bool(data.get("resolved") or data.get("closed"))
    resolution_price = data.get("resolutionPrice")
    if resolution_price is not None:
        resolution_price = float(resolution_price)

    best_bid = data.get("bestBid")
    best_ask = data.get("bestAsk")
    if best_bid is not None and best_ask is not None:
        mid_price = round((float(best_bid) + float(best_ask)) / 2, 4)
    elif resolution_price is not None:
        mid_price = resolution_price
    else:
        mid_price = None

    end_date = data.get("endDate") or data.get("endDateIso")

    return {
        "yes_token_id":    yes_token_id,
        "title":           title,
        "tags":            [str(t) for t in tags],
        "resolved":        resolved,
        "resolution_price": resolution_price,
        "mid_price":       mid_price,
        "end_date":        end_date,
    }



# ── Helpers ────────────────────────────────────────────────────────────────────

def classify_category(tags: list) -> str:
    tag_set = {str(t).lower() for t in tags}
    if tag_set & _CRYPTO:   return "crypto"
    if tag_set & _POLITICS: return "politics"
    if tag_set & _SPORTS:   return "sports"
    return "other"


def _find_convergent_signal(conn, market_title: str, outcome: str) -> dict | None:
    """Return a matching engine signal fired within 24h, or None."""
    m = _TICKER_RE.search(market_title)
    if not m:
        return None
    ticker    = m.group(1).upper()
    direction = "long" if outcome == "YES" else "short"
    try:
        row = conn.execute(
            """SELECT pair, direction, strategy, entry_price, created_at
               FROM signals
               WHERE pair LIKE ? AND direction = ?
                 AND created_at > datetime('now', '-24 hours')
               ORDER BY created_at DESC LIMIT 1""",
            (f"%{ticker}%", direction),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


# ── Position operations ────────────────────────────────────────────────────────

def _poly_open(
    conn, wallet: str, pos: dict, meta: dict | None,
    position_size_pct: float, max_concurrent: int,
) -> None:
    market_id   = pos["market_id"]
    outcome     = pos["outcome"]
    entry_price = pos["avg_price"]

    if entry_price <= 0:
        return

    open_count = conn.execute(
        "SELECT COUNT(*) FROM poly_positions WHERE closed_at IS NULL"
    ).fetchone()[0]
    if open_count >= max_concurrent:
        logger.warning(f"Max positions ({max_concurrent}) reached — skipping {market_id[:12]}…")
        return

    balance    = get_poly_balance(conn)
    cost_basis = round(balance * position_size_pct, 2)
    if cost_basis < 0.50:
        logger.warning(f"Insufficient balance ({balance:.2f}) to open {market_id[:12]}…")
        return

    shares = round(cost_basis / entry_price, 4)

    title        = (meta and meta["title"]) or pos.get("title") or ""
    tags         = (meta and meta["tags"])  or pos.get("tags")  or []
    yes_token_id = (meta and meta["yes_token_id"]) or pos.get("yes_token_id")
    end_date     = (meta and meta.get("end_date")) or None
    category     = classify_category(tags)
    now          = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """INSERT INTO poly_positions
           (trader_wallet, market_id, yes_token_id, market_title, category,
            outcome, shares, entry_price, current_price, cost_basis, end_date, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (wallet, market_id, yes_token_id, title, category,
         outcome, shares, entry_price, entry_price, cost_basis, end_date, now),
    )
    conn.execute(
        """INSERT INTO poly_state (trader_wallet, market_id, outcome, side)
           VALUES (?, ?, ?, 'open')
           ON CONFLICT(trader_wallet, market_id, outcome) DO UPDATE SET side='open'""",
        (wallet, market_id, outcome),
    )
    _adjust_poly_balance(conn, -cost_basis)
    conn.commit()

    balance_after = get_poly_balance(conn)
    logger.info(
        f"Poly OPEN  {wallet[:10]}… {outcome} [{title[:50]}] "
        f"@ {entry_price:.3f} shares={shares:.0f} cost=${cost_basis:.2f}"
    )
    convergent = _find_convergent_signal(conn, title, outcome)
    send_poly_open_alert(
        wallet, title, outcome, shares, entry_price, cost_basis,
        balance_after, category, convergent,
    )


def _close_position(
    conn, wallet: str, market_id: str, outcome: str,
    exit_price: float, reason: str,
) -> None:
    row = conn.execute(
        """SELECT id, market_title, category, shares, entry_price, cost_basis
           FROM poly_positions
           WHERE trader_wallet=? AND market_id=? AND outcome=? AND closed_at IS NULL
           ORDER BY opened_at DESC LIMIT 1""",
        (wallet, market_id, outcome),
    ).fetchone()
    if row is None:
        return

    pnl      = 0.0 if reason == "voided" else round(row["shares"] * (exit_price - row["entry_price"]), 4)
    now      = datetime.now(timezone.utc).isoformat()
    new_side = "resolved" if reason in ("resolved_win", "resolved_loss", "voided") else "closed"

    conn.execute(
        """UPDATE poly_positions
           SET exit_price=?, current_price=?, pnl_usdt=?, closed_at=?, exit_reason=?
           WHERE id=?""",
        (exit_price, exit_price, pnl, now, reason, row["id"]),
    )
    conn.execute(
        "UPDATE poly_state SET side=? WHERE trader_wallet=? AND market_id=? AND outcome=?",
        (new_side, wallet, market_id, outcome),
    )
    win_delta  = 1 if reason == "resolved_win"  else 0
    loss_delta = 1 if reason == "resolved_loss" else 0
    conn.execute(
        """UPDATE poly_account SET
           realized_pnl = realized_pnl + ?,
           wins         = wins   + ?,
           losses       = losses + ?,
           balance      = balance + ?,
           updated_at   = ?
           WHERE id = 1""",
        (pnl, win_delta, loss_delta, round(row["cost_basis"] + pnl, 4), now),
    )
    conn.commit()

    balance_after = get_poly_balance(conn)
    logger.info(
        f"Poly {reason.upper()} {wallet[:10]}… {outcome} [{row['market_title'][:50]}] "
        f"exit={exit_price:.3f} pnl={pnl:+.2f}"
    )
    send_poly_close_alert(
        wallet, row["market_title"], outcome,
        row["entry_price"], exit_price, pnl, row["cost_basis"],
        reason, balance_after, row["category"],
    )


# ── Scheduler jobs ─────────────────────────────────────────────────────────────

def refresh_leaderboard_job() -> None:
    c            = cfg().get("polymarket_trader", {})
    top_n        = int(c.get("top_n", 10))
    min_pnl      = float(c.get("min_pnl_30d", 50_000))
    volume_floor = float(c.get("volume_floor", 10_000))

    # Try leaderboard API first (best-effort — endpoint may not be public)
    traders = fetch_poly_leaderboard(top_n, min_pnl, volume_floor)

    # Fall back to manually specified wallets from config
    watched: list[str] = c.get("watched_wallets", [])
    if not traders and watched:
        logger.info(f"PM leaderboard API unavailable — seeding {len(watched)} watched wallets from config")
        traders = [{"wallet": w, "pnl_30d": None, "volume_30d": None, "alias": None}
                   for w in watched[:top_n]]

    if not traders:
        logger.warning(
            "PM leaderboard refresh: no traders available. "
            "Add wallet addresses to polymarket_trader.watched_wallets in config.yaml."
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE poly_traders SET active=0")
        for t in traders:
            conn.execute(
                """INSERT INTO poly_traders (wallet, alias, pnl_30d, volume_30d, last_refreshed, active)
                   VALUES (?, ?, ?, ?, ?, 1)
                   ON CONFLICT(wallet) DO UPDATE SET
                     alias=excluded.alias, pnl_30d=excluded.pnl_30d,
                     volume_30d=excluded.volume_30d,
                     last_refreshed=excluded.last_refreshed, active=1""",
                (t["wallet"], t["alias"], t["pnl_30d"], t["volume_30d"], now),
            )
        conn.commit()

    logger.info(
        f"PM leaderboard refreshed | active={len(traders)} "
        f"first={traders[0]['wallet'][:12]}…"
    )


def poll_positions_job() -> None:
    c                 = cfg().get("polymarket_trader", {})
    position_size_pct = float(c.get("position_size_pct", 0.05))
    max_concurrent    = int(c.get("max_concurrent_positions", 20))

    with get_conn() as conn:
        wallet_rows = conn.execute("""
            SELECT wallet FROM poly_traders WHERE active=1
            UNION
            SELECT DISTINCT trader_wallet FROM poly_state WHERE side='open'
        """).fetchall()

    wallets = [r["wallet"] for r in wallet_rows]
    if not wallets:
        logger.debug("No PM traders to poll")
        return

    # Shared meta cache across all wallets (deduplicates Gamma API calls)
    meta_cache: dict[str, dict] = {}

    for wallet in wallets:
        live = fetch_poly_positions(wallet)
        if live is None:
            continue

        current: dict = {
            (p["market_id"], p["outcome"]): p
            for p in live
            if p["market_id"] and p["outcome"] in ("YES", "NO")
        }

        with get_conn() as conn:
            prev_rows = conn.execute(
                "SELECT market_id, outcome, side FROM poly_state WHERE trader_wallet=?",
                (wallet,),
            ).fetchall()
        previous = {(r["market_id"], r["outcome"]): r["side"] for r in prev_rows}

        # ── Pre-fetch Gamma meta for new + still-open markets (HTTP outside DB) ─
        new_keys = [k for k in current if k not in previous]
        for market_id, _ in new_keys:
            if market_id not in meta_cache:
                meta = fetch_market_meta(market_id)
                if meta:
                    meta_cache[market_id] = meta

        still_open_markets = {
            market_id
            for (market_id, outcome), side in previous.items()
            if side == "open" and (market_id, outcome) in current
        }
        for market_id in still_open_markets:
            if market_id not in meta_cache:
                meta = fetch_market_meta(market_id)
                if meta:
                    meta_cache[market_id] = meta

        resolution_cache = {
            mid: m for mid, m in meta_cache.items()
            if mid in still_open_markets and m.get("resolved")
        }

        # ── Apply diff ────────────────────────────────────────────────────────
        with get_conn() as conn:
            # 1. Open new positions
            for (market_id, outcome) in new_keys:
                pos  = current[(market_id, outcome)]
                meta = meta_cache.get(market_id)
                _poly_open(conn, wallet, pos, meta, position_size_pct, max_concurrent)

            # 2. Trader closed (in previous-open, not in current)
            for (market_id, outcome), side in previous.items():
                if side != "open" or (market_id, outcome) in current:
                    continue
                mid_price = meta_cache.get(market_id, {}).get("mid_price")
                if mid_price is not None:
                    exit_price = mid_price if outcome == "YES" else 1.0 - mid_price
                else:
                    ep_row = conn.execute(
                        """SELECT entry_price FROM poly_positions
                           WHERE trader_wallet=? AND market_id=? AND outcome=? AND closed_at IS NULL
                           ORDER BY opened_at DESC LIMIT 1""",
                        (wallet, market_id, outcome),
                    ).fetchone()
                    exit_price = ep_row["entry_price"] if ep_row else 0.5
                _close_position(conn, wallet, market_id, outcome, exit_price, "trader_closed")

            # 3. Market resolved
            for (market_id, outcome), side in previous.items():
                if side != "open" or (market_id, outcome) not in current:
                    continue
                if market_id not in resolution_cache:
                    continue
                rp = resolution_cache[market_id].get("resolution_price")
                if rp is None:
                    continue
                rp = float(rp)
                # Snap to clean values
                if rp >= 0.99:   rp = 1.0
                elif rp <= 0.01: rp = 0.0
                else:            rp = 0.5

                if outcome == "YES":
                    exit_price = rp
                    if rp == 1.0:   reason = "resolved_win"
                    elif rp == 0.0: reason = "resolved_loss"
                    else:           reason = "voided"
                else:  # NO
                    exit_price = 1.0 - rp
                    if rp == 0.0:   reason = "resolved_win"
                    elif rp == 1.0: reason = "resolved_loss"
                    else:           reason = "voided"

                _close_position(conn, wallet, market_id, outcome, exit_price, reason)

    # ── Update current_price for all open positions from cached Gamma prices ──
    with get_conn() as conn:
        open_pos = conn.execute(
            "SELECT id, market_id, outcome FROM poly_positions WHERE closed_at IS NULL"
        ).fetchall()
        updates = []
        for pos in open_pos:
            meta = meta_cache.get(pos["market_id"])
            if meta and meta.get("mid_price") is not None:
                mp = meta["mid_price"]
                cp = mp if pos["outcome"] == "YES" else round(1.0 - mp, 4)
                updates.append((cp, pos["id"]))
        if updates:
            conn.executemany("UPDATE poly_positions SET current_price=? WHERE id=?", updates)
            conn.commit()

    logger.debug(f"PM poll complete | traders={len(wallets)}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="{time:HH:mm:ss} | {level:<7} | poly   | {message}")
    logger.add("logs/poly_trader.log", rotation="1 day", retention="30 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}")

    with get_conn() as conn:
        init_poly_db(conn)

    c = cfg().get("polymarket_trader", {})
    if not c.get("enabled", True):
        logger.info("Polymarket trader disabled in config — exiting")
        return

    logger.info(
        f"Poly trader starting | top_n={c.get('top_n', 10)} "
        f"budget=${float(c.get('initial_balance', 10_000)):,.0f} "
        f"pos_size={float(c.get('position_size_pct', 0.05))*100:.0f}% "
        f"max_pos={c.get('max_concurrent_positions', 20)} "
        f"min_30d_pnl=${float(c.get('min_pnl_30d', 50_000)):,.0f}"
    )

    refresh_leaderboard_job()

    scheduler = BlockingScheduler(timezone="UTC")

    # Staggered to :03 to avoid DB write contention with other services
    scheduler.add_job(
        poll_positions_job,
        "cron",
        minute="3,18,33,48",
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        refresh_leaderboard_job,
        CronTrigger(day_of_week="sun", hour=0, minute=30, timezone="UTC"),
        misfire_grace_time=3600,
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Poly trader stopped by user")


if __name__ == "__main__":
    main()
