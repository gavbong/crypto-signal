import sqlite3
from contextlib import contextmanager
from pathlib import Path
from utils.config import db_path


@contextmanager
def get_conn(path: Path | None = None):
    conn = sqlite3.connect(path or db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with get_conn(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                pair                 TEXT    NOT NULL,
                direction            TEXT    NOT NULL,
                strategy             TEXT    NOT NULL,
                regime               TEXT    NOT NULL,
                regime_confidence    REAL,
                regime_age_candles   INTEGER,
                entry_price          REAL    NOT NULL,
                suggested_stop_loss  REAL,
                suggested_take_profit REAL,
                timeframe            TEXT    NOT NULL,
                fired_at             TIMESTAMP NOT NULL,
                shadow_mode          INTEGER NOT NULL DEFAULT 1,
                llm_commentary       TEXT,
                commentary_status    TEXT    NOT NULL DEFAULT 'pending',
                outcome              TEXT,
                outcome_price        REAL,
                outcome_resolved_at  TIMESTAMP,
                created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_signals_dedup
            ON signals (pair, direction, strategy, regime, fired_at);

            CREATE INDEX IF NOT EXISTS idx_signals_pending_outcome
            ON signals (fired_at, outcome);

            CREATE INDEX IF NOT EXISTS idx_signals_commentary_pending
            ON signals (commentary_status, created_at);

            CREATE INDEX IF NOT EXISTS idx_signals_advisor
            ON signals (outcome, fired_at, strategy, regime);
        """)
        # Migrations: add columns introduced after initial schema
        for migration in [
            "ALTER TABLE signals ADD COLUMN suggested_take_profit REAL",
            "ALTER TABLE signals ADD COLUMN pnl_r REAL",
            "ALTER TABLE signals ADD COLUMN exchange TEXT NOT NULL DEFAULT 'mexc'",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except Exception:
                pass  # column already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at  TIMESTAMP,
                since_date   TEXT NOT NULL,
                pairs        TEXT,
                pid          INTEGER,
                signal_count INTEGER,
                win_count    INTEGER,
                net_r        REAL,
                win_rate     REAL,
                status       TEXT NOT NULL DEFAULT 'running',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                progress_msg TEXT,
                config_snapshot TEXT
            );
        """)

        for migration in [
            "ALTER TABLE signals ADD COLUMN backtest_run_id INTEGER",
            "CREATE INDEX IF NOT EXISTS idx_signals_backtest_run ON signals(backtest_run_id, fired_at)",
            "ALTER TABLE signals ADD COLUMN quality_score REAL",
            "ALTER TABLE backtest_runs ADD COLUMN sharpe REAL",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except Exception:
                pass

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS permutation_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at  TIMESTAMP,
                since_date   TEXT NOT NULL,
                pairs        TEXT,
                n_perms      INTEGER NOT NULL DEFAULT 200,
                pid          INTEGER,
                status       TEXT NOT NULL DEFAULT 'running',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                progress_msg TEXT
            );

            CREATE TABLE IF NOT EXISTS permutation_tests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       INTEGER REFERENCES permutation_runs(id),
                pair         TEXT NOT NULL,
                since_date   TEXT NOT NULL,
                n_perms      INTEGER NOT NULL,
                n_candles    INTEGER NOT NULL,
                results_json TEXT NOT NULL,
                created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_permutation_tests_pair
            ON permutation_tests (pair, created_at DESC);
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategy_health (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy     TEXT    NOT NULL,
                regime       TEXT    NOT NULL,
                direction    TEXT    NOT NULL,
                asset_class  TEXT    NOT NULL DEFAULT 'crypto',
                window_start TEXT,
                window_end   TEXT,
                signal_count INTEGER NOT NULL DEFAULT 0,
                win_count    INTEGER NOT NULL DEFAULT 0,
                win_rate     REAL,
                net_r        REAL    NOT NULL DEFAULT 0.0,
                status       TEXT    NOT NULL DEFAULT 'HEALTHY',
                disabled_at  TEXT,
                UNIQUE(strategy, regime, direction, asset_class)
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_health_lookup
            ON strategy_health (strategy, regime, direction, asset_class);

            CREATE INDEX IF NOT EXISTS idx_signals_quality_lookup
            ON signals (strategy, regime, direction, outcome, fired_at)
            WHERE backtest_run_id IS NULL;

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_correlation ON signals(fired_at, direction)"
            )
            conn.commit()
        except Exception:
            pass

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS regime_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pair        TEXT      NOT NULL,
                regime      TEXT      NOT NULL,
                confidence  REAL,
                age_candles INTEGER,
                stable      INTEGER,
                logged_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS index_candles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pair        TEXT    NOT NULL,
                timeframe   TEXT    NOT NULL,
                ts          INTEGER NOT NULL,
                open        REAL    NOT NULL,
                high        REAL    NOT NULL,
                low         REAL    NOT NULL,
                close       REAL    NOT NULL,
                volume      REAL    NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pair, timeframe, ts)
            );

            CREATE INDEX IF NOT EXISTS idx_index_candles_lookup
            ON index_candles (pair, timeframe, ts DESC);
        """)


def log_signal(conn: sqlite3.Connection, signal: dict, backtest_run_id: int | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO signals
           (pair, direction, strategy, regime, regime_confidence, regime_age_candles,
            entry_price, suggested_stop_loss, suggested_take_profit, timeframe,
            fired_at, shadow_mode, llm_commentary, commentary_status, exchange,
            backtest_run_id, quality_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal["pair"], signal["direction"], signal["strategy"],
            signal["regime"], signal["regime_confidence"], signal["regime_age_candles"],
            signal["entry_price"], signal["suggested_stop_loss"],
            signal.get("suggested_take_profit"),
            signal["timeframe"], signal["fired_at"], signal["shadow_mode"],
            signal.get("llm_commentary"), signal.get("commentary_status", "pending"),
            signal.get("exchange", "mexc"),
            backtest_run_id,
            signal.get("quality_score"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def log_regime(conn: sqlite3.Connection, pair: str, regime: str,
               confidence: float, age_candles: int, stable: bool) -> None:
    conn.execute(
        """INSERT INTO regime_log (pair, regime, confidence, age_candles, stable)
           VALUES (?, ?, ?, ?, ?)""",
        (pair, regime, confidence, age_candles, int(stable)),
    )
    conn.commit()


def is_duplicate(conn: sqlite3.Connection, base_asset: str, direction: str,
                 strategy: str, regime: str, window_hours: int) -> bool:
    """Check if any exchange has already fired this signal for this base asset recently.
    Uses base_asset (e.g. 'BTC') so BTC/USDT:USDT and BTC/USDC:USDC share the same dedup bucket."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    row = conn.execute(
        """SELECT 1 FROM signals
           WHERE SUBSTR(pair, 1, INSTR(pair, '/') - 1) = ?
             AND direction=? AND strategy=? AND regime=?
             AND fired_at > ? LIMIT 1""",
        (base_asset, direction, strategy, regime, cutoff),
    ).fetchone()
    return row is not None


def get_pending_outcomes(conn: sqlite3.Connection, older_than_hours: int) -> list:
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    return conn.execute(
        """SELECT * FROM signals
           WHERE outcome IS NULL AND fired_at <= ? AND backtest_run_id IS NULL
           ORDER BY fired_at""",
        (cutoff,),
    ).fetchall()


def update_outcome(conn: sqlite3.Connection, signal_id: int, outcome: str,
                   outcome_price: float, pnl_r: float | None = None) -> None:
    from datetime import datetime, timezone
    conn.execute(
        """UPDATE signals
           SET outcome=?, outcome_price=?, outcome_resolved_at=?, pnl_r=?
           WHERE id=?""",
        (outcome, outcome_price, datetime.now(timezone.utc).isoformat(), pnl_r, signal_id),
    )
    conn.commit()


def update_commentary(conn: sqlite3.Connection, signal_id: int,
                      commentary: str) -> None:
    conn.execute(
        "UPDATE signals SET llm_commentary=?, commentary_status='done' WHERE id=?",
        (commentary, signal_id),
    )
    conn.commit()


def get_accuracy_stats(conn: sqlite3.Connection, shadow_mode: int = 0) -> dict:
    rows = conn.execute(
        """SELECT regime,
                  COUNT(*) as total,
                  SUM(CASE WHEN outcome IN ('win', 'tp_hit') THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved
           FROM signals
           WHERE shadow_mode=?
           GROUP BY regime""",
        (shadow_mode,),
    ).fetchall()
    stats = {}
    for row in rows:
        resolved = row["resolved"] or 0
        wins = row["wins"] or 0
        stats[row["regime"]] = {
            "total": row["total"],
            "resolved": resolved,
            "wins": wins,
            "accuracy": wins / resolved if resolved > 0 else None,
        }
    return stats
