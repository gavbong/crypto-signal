import sqlite3
from pathlib import Path
from utils.config import db_path


def get_conn(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


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
        """)
        # Migration: add column if DB was created before take-profit was introduced
        try:
            conn.execute("ALTER TABLE signals ADD COLUMN suggested_take_profit REAL")
            conn.commit()
        except Exception:
            pass  # column already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS regime_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                pair       TEXT      NOT NULL,
                regime     TEXT      NOT NULL,
                confidence REAL,
                age_candles INTEGER,
                stable     INTEGER,
                logged_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)


def log_signal(conn: sqlite3.Connection, signal: dict) -> int:
    cur = conn.execute(
        """INSERT INTO signals
           (pair, direction, strategy, regime, regime_confidence, regime_age_candles,
            entry_price, suggested_stop_loss, suggested_take_profit, timeframe,
            fired_at, shadow_mode, llm_commentary, commentary_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal["pair"], signal["direction"], signal["strategy"],
            signal["regime"], signal["regime_confidence"], signal["regime_age_candles"],
            signal["entry_price"], signal["suggested_stop_loss"],
            signal.get("suggested_take_profit"),
            signal["timeframe"], signal["fired_at"], signal["shadow_mode"],
            signal.get("llm_commentary"), signal.get("commentary_status", "pending"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def is_duplicate(conn: sqlite3.Connection, pair: str, direction: str,
                 strategy: str, regime: str, window_hours: int) -> bool:
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()
    row = conn.execute(
        """SELECT 1 FROM signals
           WHERE pair=? AND direction=? AND strategy=? AND regime=?
             AND fired_at > ? LIMIT 1""",
        (pair, direction, strategy, regime, cutoff),
    ).fetchone()
    return row is not None


def get_pending_outcomes(conn: sqlite3.Connection, older_than_hours: int) -> list:
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=older_than_hours)).isoformat()
    return conn.execute(
        """SELECT * FROM signals
           WHERE outcome IS NULL AND fired_at <= ?
           ORDER BY fired_at""",
        (cutoff,),
    ).fetchall()


def update_outcome(conn: sqlite3.Connection, signal_id: int, outcome: str,
                   outcome_price: float) -> None:
    from datetime import datetime
    conn.execute(
        """UPDATE signals
           SET outcome=?, outcome_price=?, outcome_resolved_at=?
           WHERE id=?""",
        (outcome, outcome_price, datetime.utcnow().isoformat(), signal_id),
    )
    conn.commit()


def update_commentary(conn: sqlite3.Connection, signal_id: int,
                      commentary: str) -> None:
    conn.execute(
        "UPDATE signals SET llm_commentary=?, commentary_status='done' WHERE id=?",
        (commentary, signal_id),
    )
    conn.commit()


def get_accuracy_stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """SELECT regime,
                  COUNT(*) as total,
                  SUM(CASE WHEN outcome IN ('win', 'tp_hit') THEN 1 ELSE 0 END) as wins,
                  SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as resolved
           FROM signals
           WHERE shadow_mode=1
           GROUP BY regime"""
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
