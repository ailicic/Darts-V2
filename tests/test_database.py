"""
Unit tests for the database persistence layer.
"""

import os
import sys
import uuid
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import database


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Redirect every test to a fresh temporary database file."""
    db_file = str(tmp_path / "test_darts.db")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    yield db_file


@pytest.fixture
def session():
    sid = str(uuid.uuid4())
    database.create_session(sid)
    return sid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_tables_exist(self, temp_db):
        import sqlite3
        conn = sqlite3.connect(temp_db)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "sessions"  in tables
        assert "dart_hits" in tables


class TestLogDartHit:
    def test_logs_single_hit(self, session):
        database.log_dart_hit(session, 20, "Double", 2, 40, 0.9)
        hits = database.get_session_hits(session)
        assert len(hits) == 1
        h = hits[0]
        assert h["number"]     == 20
        assert h["zone"]       == "Double"
        assert h["multiplier"] == 2
        assert h["score"]      == 40

    def test_logs_multiple_hits(self, session):
        for _ in range(5):
            database.log_dart_hit(session, 1, "Single", 1, 1, 0.8)
        assert len(database.get_session_hits(session)) == 5

    def test_manual_flag(self, session):
        database.log_dart_hit(session, 7, "Single", 1, 7, 1.0, manual=True)
        hits = database.get_session_hits(session)
        assert hits[0]["manual"] == 1

    def test_returns_row_id(self, session):
        row_id = database.log_dart_hit(session, 5, "Single", 1, 5, 0.7)
        assert isinstance(row_id, int)
        assert row_id > 0


class TestDeleteLastHit:
    def test_removes_last_hit(self, session):
        database.log_dart_hit(session, 20, "Double", 2, 40, 0.9)
        database.log_dart_hit(session, 17, "Treble", 3, 51, 0.85)
        removed = database.delete_last_hit(session)
        assert removed["score"] == 51
        remaining = database.get_session_hits(session)
        assert len(remaining) == 1
        assert remaining[0]["score"] == 40

    def test_returns_none_when_empty(self, session):
        result = database.delete_last_hit(session)
        assert result is None


class TestClearSessionHits:
    def test_removes_all_hits(self, session):
        for _ in range(3):
            database.log_dart_hit(session, 1, "Single", 1, 1, 0.9)
        database.clear_session_hits(session)
        assert database.get_session_hits(session) == []


class TestGetSessionHits:
    def test_empty_session(self, session):
        assert database.get_session_hits(session) == []

    def test_hits_are_dicts(self, session):
        database.log_dart_hit(session, 20, "Single", 1, 20, 0.9)
        hits = database.get_session_hits(session)
        assert isinstance(hits[0], dict)

    def test_hits_ordered_by_timestamp(self, session):
        scores = [20, 40, 60]
        for s in scores:
            database.log_dart_hit(session, s, "Single", 1, s, 0.9)
        hits = database.get_session_hits(session)
        returned_scores = [h["score"] for h in hits]
        assert returned_scores == scores
