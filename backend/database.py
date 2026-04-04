"""
SQLite persistence layer for dart hit logging.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "darts.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not already exist."""
    conn = _connect()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            total_score INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS dart_hits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL REFERENCES sessions(id),
            timestamp   TEXT    NOT NULL,
            number      INTEGER NOT NULL DEFAULT 0,
            zone        TEXT    NOT NULL DEFAULT 'Miss',
            multiplier  INTEGER NOT NULL DEFAULT 0,
            score       INTEGER NOT NULL DEFAULT 0,
            confidence  REAL    NOT NULL DEFAULT 0.0,
            x_pos       REAL    NOT NULL DEFAULT 0.0,
            y_pos       REAL    NOT NULL DEFAULT 0.0,
            manual      INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


def create_session(session_id: str) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
        (session_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def log_dart_hit(
    session_id: str,
    number: int,
    zone: str,
    multiplier: int,
    score: int,
    confidence: float,
    x_pos: float = 0.0,
    y_pos: float = 0.0,
    manual: bool = False,
) -> int:
    """Insert a dart hit record and update the session total. Returns new row id."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO dart_hits
            (session_id, timestamp, number, zone, multiplier, score, confidence, x_pos, y_pos, manual)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            datetime.now().isoformat(),
            number,
            zone,
            multiplier,
            score,
            confidence,
            x_pos,
            y_pos,
            int(manual),
        ),
    )
    row_id = cur.lastrowid
    conn.execute(
        "UPDATE sessions SET total_score = total_score + ? WHERE id = ?",
        (score, session_id),
    )
    conn.commit()
    conn.close()
    return row_id


def get_session_hits(session_id: str) -> list:
    """Return all dart hits for a session as a list of dicts."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM dart_hits WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_last_hit(session_id: str) -> dict | None:
    """Remove the most recent dart hit and return it, or None if empty."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM dart_hits WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row:
        hit = dict(row)
        conn.execute("DELETE FROM dart_hits WHERE id = ?", (hit["id"],))
        conn.execute(
            "UPDATE sessions SET total_score = total_score - ? WHERE id = ?",
            (hit["score"], session_id),
        )
        conn.commit()
    conn.close()
    return dict(row) if row else None


def clear_session_hits(session_id: str) -> None:
    """Remove all dart hits for a session and reset total."""
    conn = _connect()
    conn.execute("DELETE FROM dart_hits WHERE session_id = ?", (session_id,))
    conn.execute("UPDATE sessions SET total_score = 0 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
