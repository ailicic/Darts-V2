"""
SQLite persistence layer for dart hit logging, groups, and game results.

Schema history
--------------
v1  – sessions + dart_hits (original)
v2  – groups table; group_id added to sessions; finished_games table
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "darts.db")

#: Slug for data that existed before groups were introduced
LEGACY_GROUP_SLUG = "default"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create or migrate tables to the current schema."""
    conn = _connect()
    cur = conn.cursor()
    cur.executescript("""
        -- v1 tables (unchanged)
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

        -- v2: group isolation
        CREATE TABLE IF NOT EXISTS groups (
            id         TEXT PRIMARY KEY,
            slug       TEXT NOT NULL UNIQUE,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- v2: finished game results (persisted after in-memory game is purged)
        CREATE TABLE IF NOT EXISTS finished_games (
            id          TEXT PRIMARY KEY,
            short_code  TEXT,
            mode        TEXT NOT NULL,
            group_id    TEXT REFERENCES groups(id),
            winner_name TEXT,
            player_names TEXT NOT NULL,  -- JSON array
            dart_count  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # v2 migration: add group_id column to sessions if it doesn't exist yet
    cols = {row[1] for row in cur.execute("PRAGMA table_info(sessions)").fetchall()}
    if "group_id" not in cols:
        cur.execute("ALTER TABLE sessions ADD COLUMN group_id TEXT REFERENCES groups(id)")

    # Ensure the legacy/default group exists
    cur.execute(
        "INSERT OR IGNORE INTO groups (id, slug, name) VALUES (?, ?, ?)",
        (LEGACY_GROUP_SLUG, LEGACY_GROUP_SLUG, "Default Group"),
    )

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


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------

def create_group(group_id: str, slug: str, name: str) -> dict:
    """Insert a new group and return it.  Raises sqlite3.IntegrityError on dupe slug."""
    conn = _connect()
    conn.execute(
        "INSERT INTO groups (id, slug, name) VALUES (?, ?, ?)",
        (group_id, slug, name),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return dict(row)


def get_group_by_slug(slug: str) -> Optional[dict]:
    """Return group dict for *slug*, or None."""
    conn = _connect()
    row = conn.execute("SELECT * FROM groups WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_group_by_id(group_id: str) -> Optional[dict]:
    """Return group dict for *group_id*, or None."""
    conn = _connect()
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Finished game persistence
# ---------------------------------------------------------------------------

def save_finished_game(
    game_id: str,
    short_code: str,
    mode: str,
    group_id: Optional[str],
    winner_name: Optional[str],
    player_names: list,
    dart_count: int,
    created_at: str,
) -> None:
    """Persist a finished game record for leaderboard / history."""
    import json
    conn = _connect()
    conn.execute(
        """
        INSERT OR REPLACE INTO finished_games
            (id, short_code, mode, group_id, winner_name, player_names, dart_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            short_code,
            mode,
            group_id,
            winner_name,
            json.dumps(player_names),
            dart_count,
            created_at,
        ),
    )
    conn.commit()
    conn.close()


def get_leaderboard(group_id: Optional[str] = None, mode: Optional[str] = None, limit: int = 20) -> list:
    """
    Return recent finished games for the leaderboard.

    If *group_id* is provided, restrict to that group.
    If *mode* is provided, restrict to that game mode.
    """
    conn = _connect()
    conditions = []
    params: list = []

    if group_id:
        conditions.append("group_id = ?")
        params.append(group_id)
    if mode:
        conditions.append("mode = ?")
        params.append(mode)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, short_code, mode, group_id, winner_name, player_names,
               dart_count, created_at, finished_at
        FROM finished_games
        {where}
        ORDER BY finished_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()

    import json
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["player_names"] = json.loads(d["player_names"])
        except Exception:
            pass
        result.append(d)
    return result
