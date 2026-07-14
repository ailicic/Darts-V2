"""
Unit tests for game_manager module.

Run with:  python -m pytest tests/ -v
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
import game_manager


@pytest.fixture(autouse=True)
def reset_games():
    """Clear the in-memory game store before each test."""
    with game_manager._lock:
        game_manager._games.clear()
        game_manager._code_index.clear()
    yield


# ---------------------------------------------------------------------------
# Short code generation
# ---------------------------------------------------------------------------

class TestShortCode:
    def test_code_length(self):
        game = game_manager.create_game("detection", ["Alice"])
        assert len(game["short_code"]) == game_manager._CODE_LENGTH

    def test_code_charset(self):
        alphabet = set(game_manager._ALPHABET)
        game = game_manager.create_game("detection", ["Alice"])
        for ch in game["short_code"]:
            assert ch in alphabet

    def test_codes_unique(self):
        games = [game_manager.create_game("detection", ["P1"]) for _ in range(20)]
        codes = {g["short_code"] for g in games}
        assert len(codes) == 20

    def test_lookup_by_code(self):
        game = game_manager.create_game("detection", ["Alice"])
        found = game_manager.get_game_by_code(game["short_code"])
        assert found is not None
        assert found["id"] == game["id"]

    def test_lookup_case_insensitive(self):
        game = game_manager.create_game("detection", ["Alice"])
        found = game_manager.get_game_by_code(game["short_code"].lower())
        assert found is not None

    def test_lookup_nonexistent_returns_none(self):
        assert game_manager.get_game_by_code("XXXXX") is None


# ---------------------------------------------------------------------------
# create_game
# ---------------------------------------------------------------------------

class TestCreateGame:
    def test_returns_game_dict(self):
        game = game_manager.create_game("detection", ["Alice", "Bob"])
        assert "id" in game
        assert "short_code" in game
        assert game["mode"] == "detection"
        assert len(game["players"]) == 2

    def test_player_names_sanitised(self):
        game = game_manager.create_game("detection", ["  Alice  ", "B<ob>"])
        names = [p["name"] for p in game["players"]]
        assert names[0] == "Alice"
        assert "<" not in names[1]

    def test_empty_players_raises(self):
        with pytest.raises(ValueError):
            game_manager.create_game("detection", [])

    def test_unknown_mode_raises(self):
        with pytest.raises(KeyError):
            game_manager.create_game("nonexistent", ["Alice"])

    def test_game_starts_active(self):
        game = game_manager.create_game("detection", ["Alice"])
        assert game["status"] == "active"

    def test_group_id_stored(self):
        game = game_manager.create_game("detection", ["Alice"], group_id="group-123")
        assert game["group_id"] == "group-123"

    def test_501_mode_created(self):
        game = game_manager.create_game("501", ["Alice"])
        assert game["players"][0]["score"] == 501


# ---------------------------------------------------------------------------
# get_game
# ---------------------------------------------------------------------------

class TestGetGame:
    def test_returns_game(self):
        created = game_manager.create_game("detection", ["Alice"])
        found = game_manager.get_game(created["id"])
        assert found is not None
        assert found["id"] == created["id"]

    def test_unknown_id_returns_none(self):
        assert game_manager.get_game("nonexistent") is None

    def test_includes_scoreboard(self):
        game = game_manager.create_game("detection", ["Alice"])
        assert "scoreboard" in game


# ---------------------------------------------------------------------------
# apply_throw
# ---------------------------------------------------------------------------

def _dart(number=20, zone="Single", multiplier=1, score=None):
    if score is None:
        score = number * multiplier if zone not in ("Bull", "Bullseye", "Miss") else (
            25 if zone == "Bull" else (50 if zone == "Bullseye" else 0)
        )
    return {"number": number, "zone": zone, "multiplier": multiplier, "score": score, "confidence": 1.0}


class TestApplyThrow:
    def test_returns_result(self):
        game = game_manager.create_game("detection", ["Alice", "Bob"])
        result = game_manager.apply_throw(game["id"], _dart())
        assert result is not None
        assert "game" in result
        assert "throw_result" in result

    def test_score_updates(self):
        game = game_manager.create_game("detection", ["Alice"])
        game_manager.apply_throw(game["id"], _dart(20, "Single"))
        updated = game_manager.get_game(game["id"])
        assert updated["players"][0]["score"] == 20

    def test_turn_advances_after_3_darts(self):
        game = game_manager.create_game("detection", ["Alice", "Bob"])
        for _ in range(3):
            game_manager.apply_throw(game["id"], _dart(1, "Single"))
        updated = game_manager.get_game(game["id"])
        assert updated["current_player_index"] == 1

    def test_nonexistent_game_returns_none(self):
        assert game_manager.apply_throw("nonexistent", _dart()) is None

    def test_finished_game_returns_none(self):
        game = game_manager.create_game("501", ["Alice"])
        with game_manager._lock:
            game_manager._games[game["id"]]["status"] = "finished"
        assert game_manager.apply_throw(game["id"], _dart()) is None

    def test_501_win_detected(self):
        game = game_manager.create_game("501", ["Alice"])
        with game_manager._lock:
            game_manager._games[game["id"]]["players"][0]["score"] = 40
            game_manager._games[game["id"]]["players"][0]["score_at_turn_start"] = 40
        result = game_manager.apply_throw(game["id"], _dart(20, "Double", 2, 40))
        assert result["winner_id"] is not None
        updated = game_manager.get_game(game["id"])
        assert updated["status"] == "finished"


# ---------------------------------------------------------------------------
# end_turn
# ---------------------------------------------------------------------------

class TestEndTurn:
    def test_advances_player(self):
        game = game_manager.create_game("detection", ["Alice", "Bob"])
        assert game["current_player_index"] == 0
        updated = game_manager.end_turn(game["id"])
        assert updated["current_player_index"] == 1

    def test_wraps_to_first_player(self):
        game = game_manager.create_game("detection", ["Alice", "Bob"])
        game_manager.end_turn(game["id"])
        updated = game_manager.end_turn(game["id"])
        assert updated["current_player_index"] == 0

    def test_nonexistent_returns_none(self):
        assert game_manager.end_turn("nonexistent") is None


# ---------------------------------------------------------------------------
# undo_last_throw
# ---------------------------------------------------------------------------

class TestUndoLastThrow:
    def test_undo_reverts_score(self):
        game = game_manager.create_game("detection", ["Alice"])
        game_manager.apply_throw(game["id"], _dart(20, "Single"))
        game_manager.undo_last_throw(game["id"])
        updated = game_manager.get_game(game["id"])
        assert updated["players"][0]["score"] == 0

    def test_undo_empty_returns_none(self):
        game = game_manager.create_game("detection", ["Alice"])
        assert game_manager.undo_last_throw(game["id"]) is None

    def test_nonexistent_returns_none(self):
        assert game_manager.undo_last_throw("nonexistent") is None

    def test_undo_dart_log_shrinks(self):
        game = game_manager.create_game("detection", ["Alice"])
        game_manager.apply_throw(game["id"], _dart(20, "Single"))
        game_manager.apply_throw(game["id"], _dart(5, "Single"))
        game_manager.undo_last_throw(game["id"])
        updated = game_manager.get_game(game["id"])
        assert len(updated["dart_log"]) == 1


# ---------------------------------------------------------------------------
# purge_old_games
# ---------------------------------------------------------------------------

class TestPurge:
    def test_purge_removes_old_games(self, monkeypatch):
        game = game_manager.create_game("detection", ["Alice"])
        # Force last_activity to be very old
        with game_manager._lock:
            game_manager._games[game["id"]]["last_activity"] = 0.0
        monkeypatch.setattr(game_manager, "GAME_TTL_HOURS", 0.0)
        removed = game_manager.purge_old_games()
        assert removed >= 1
        assert game_manager.get_game(game["id"]) is None

    def test_purge_keeps_recent_games(self):
        game = game_manager.create_game("detection", ["Alice"])
        removed = game_manager.purge_old_games()
        assert removed == 0
        assert game_manager.get_game(game["id"]) is not None


# ---------------------------------------------------------------------------
# active_games_count
# ---------------------------------------------------------------------------

class TestActiveGamesCount:
    def test_counts_active_only(self):
        game_manager.create_game("detection", ["Alice"])
        game_manager.create_game("detection", ["Bob"])
        assert game_manager.active_games_count() == 2

    def test_finished_not_counted(self):
        game = game_manager.create_game("detection", ["Alice"])
        with game_manager._lock:
            game_manager._games[game["id"]]["status"] = "finished"
        assert game_manager.active_games_count() == 0
