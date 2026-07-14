"""
Unit tests for all game mode modules.

Run with:  python -m pytest tests/ -v
"""

import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest

from game_modes import get_mode, list_modes
from game_modes.x01 import X01Mode
from game_modes.cricket import CricketMode, CRICKET_TARGETS
from game_modes.cut_throat import CutThroatMode
from game_modes.around_the_clock import AroundTheClockMode, SEQUENCE
from game_modes.detection import DetectionMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dart(number=20, zone="Single", multiplier=1, score=None):
    if score is None:
        if zone == "Bullseye":
            score = 50
        elif zone == "Bull":
            score = 25
        elif zone == "Miss":
            score = 0
        else:
            score = number * multiplier
    return {"number": number, "zone": zone, "multiplier": multiplier, "score": score, "confidence": 1.0}


def _make_players(mode, count=2):
    return [mode.create_player(str(uuid.uuid4()), f"P{i+1}") for i in range(count)]


# ===========================================================================
# Mode registry
# ===========================================================================

class TestRegistry:
    def test_list_modes_returns_all(self):
        modes = list_modes()
        ids = {m["id"] for m in modes}
        assert "detection" in ids
        assert "501" in ids
        assert "cricket" in ids
        assert "cut_throat" in ids
        assert "around_the_clock" in ids

    def test_get_mode_unknown_raises(self):
        with pytest.raises(KeyError):
            get_mode("nonexistent_mode")

    def test_each_mode_has_required_fields(self):
        for m in list_modes():
            assert "id" in m
            assert "label" in m
            assert "rules_summary" in m
            assert "darts_per_turn" in m


# ===========================================================================
# Detection mode
# ===========================================================================

class TestDetectionMode:
    def setup_method(self):
        self.mode = DetectionMode()

    def test_create_player(self):
        p = self.mode.create_player("p1", "Alice")
        assert p["score"] == 0
        assert p["darts_thrown"] == 0

    def test_score_accumulates(self):
        players = _make_players(self.mode, 1)
        self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        self.mode.process_throw(players, 0, _make_dart(20, "Double", 2))
        assert players[0]["score"] == 60

    def test_no_win_condition(self):
        players = _make_players(self.mode, 1)
        for _ in range(10):
            self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        assert self.mode.check_win(players) is None

    def test_turn_complete_after_3_darts(self):
        players = _make_players(self.mode, 1)
        results = [self.mode.process_throw(players, 0, _make_dart()) for _ in range(3)]
        assert results[-1]["turn_complete"] is True

    def test_on_turn_start_resets_darts_this_turn(self):
        players = _make_players(self.mode, 1)
        players[0]["darts_this_turn"] = 3
        self.mode.on_turn_start(players, 0)
        assert players[0]["darts_this_turn"] == 0


# ===========================================================================
# X01 (501) mode
# ===========================================================================

class TestX01Mode:
    def setup_method(self):
        self.mode = X01Mode(501)

    def test_create_player_starts_at_501(self):
        p = self.mode.create_player("p1", "Alice")
        assert p["score"] == 501

    def test_normal_throw_subtracts(self):
        players = _make_players(self.mode, 1)
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert players[0]["score"] == 481
        assert result["score_delta"] == 20
        assert not result["bust"]

    def test_bust_below_zero(self):
        players = _make_players(self.mode, 1)
        players[0]["score"] = 10
        players[0]["score_at_turn_start"] = 10
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert result["bust"] is True
        assert result["turn_complete"] is True
        assert players[0]["score"] == 10  # reverted

    def test_bust_landing_on_1(self):
        players = _make_players(self.mode, 1)
        players[0]["score"] = 3
        players[0]["score_at_turn_start"] = 3
        # Score = 3, hit Single 2 → leaves 1 → bust
        result = self.mode.process_throw(players, 0, _make_dart(2, "Single"))
        assert result["bust"] is True
        assert players[0]["score"] == 3  # reverted

    def test_checkout_on_double(self):
        players = _make_players(self.mode, 1)
        players[0]["score"] = 40
        players[0]["score_at_turn_start"] = 40
        result = self.mode.process_throw(players, 0, _make_dart(20, "Double", 2))
        assert result["bust"] is False
        assert players[0]["score"] == 0
        assert self.mode.check_win(players) == players[0]["id"]

    def test_checkout_on_bullseye(self):
        players = _make_players(self.mode, 1)
        players[0]["score"] = 50
        players[0]["score_at_turn_start"] = 50
        result = self.mode.process_throw(players, 0, _make_dart(0, "Bullseye", 1, 50))
        assert result["bust"] is False
        assert players[0]["score"] == 0

    def test_no_checkout_on_single(self):
        players = _make_players(self.mode, 1)
        players[0]["score"] = 20
        players[0]["score_at_turn_start"] = 20
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert result["bust"] is True  # single 20 would leave 0 but not on double

    def test_turn_complete_after_3_darts(self):
        players = _make_players(self.mode, 1)
        for i in range(2):
            r = self.mode.process_throw(players, 0, _make_dart(1, "Single"))
            assert not r["turn_complete"]
        r = self.mode.process_throw(players, 0, _make_dart(1, "Single"))
        assert r["turn_complete"]

    def test_no_win_before_zero(self):
        players = _make_players(self.mode, 2)
        assert self.mode.check_win(players) is None

    def test_301_mode(self):
        mode = X01Mode(301)
        p = mode.create_player("p1", "Bob")
        assert p["score"] == 301
        assert mode.id == "301"

    def test_scoreboard_rows(self):
        players = _make_players(self.mode, 2)
        rows = self.mode.scoreboard_rows(players)
        assert len(rows) == 2
        assert rows[0]["display"] == "501"


# ===========================================================================
# Standard Cricket
# ===========================================================================

class TestCricketMode:
    def setup_method(self):
        self.mode = CricketMode()

    def test_create_player(self):
        p = self.mode.create_player("p1", "Alice")
        assert all(p["marks"][t] == 0 for t in CRICKET_TARGETS)
        assert p["score"] == 0

    def test_single_mark(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert players[0]["marks"][20] == 1

    def test_treble_closes(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        assert players[0]["closed"][20] is True

    def test_double_gives_2_marks(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(20, "Double", 2))
        assert players[0]["marks"][20] == 2

    def test_overflow_scores_against_open_opponents(self):
        players = _make_players(self.mode, 2)
        # P1 closes 20 with treble (no overflow)
        self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        # P2 still hasn't closed 20, P1 hits another single → scores +20 for P1
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert players[0]["score"] == 20
        assert result["score_delta"] == 20

    def test_no_score_when_all_closed(self):
        players = _make_players(self.mode, 2)
        # Both close 20
        self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        self.mode.process_throw(players, 1, _make_dart(20, "Treble", 3))
        # P1 hits 20 again — no score for anyone
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert result["score_delta"] == 0

    def test_non_cricket_target_ignored(self):
        players = _make_players(self.mode, 2)
        result = self.mode.process_throw(players, 0, _make_dart(10, "Single"))
        assert result["score_delta"] == 0

    def test_bull_marks(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(0, "Bull", 1, 25))
        assert players[0]["marks"]["bull"] == 1

    def test_bullseye_gives_2_marks(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(0, "Bullseye", 1, 50))
        assert players[0]["marks"]["bull"] == 2

    def test_win_condition(self):
        players = _make_players(self.mode, 1)
        for t in CRICKET_TARGETS:
            if t == "bull":
                players[0]["marks"][t] = 3
                players[0]["closed"][t] = True
            else:
                players[0]["marks"][t] = 3
                players[0]["closed"][t] = True
        assert self.mode.check_win(players) == players[0]["id"]

    def test_no_win_partial_close(self):
        players = _make_players(self.mode, 2)
        assert self.mode.check_win(players) is None

    def test_scoreboard_rows(self):
        players = _make_players(self.mode, 2)
        rows = self.mode.scoreboard_rows(players)
        assert len(rows) == 2
        assert "marks" in rows[0]
        assert "closed" in rows[0]


# ===========================================================================
# Cut Throat Cricket
# ===========================================================================

class TestCutThroatMode:
    def setup_method(self):
        self.mode = CutThroatMode()

    def test_penalty_goes_to_opponents(self):
        players = _make_players(self.mode, 2)
        # P1 closes 20
        self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        # P1 hits 20 again — P2 (open) gets +20
        self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert players[1]["score"] == 20  # penalty on P2
        assert players[0]["score"] == 0   # P1 gets nothing

    def test_no_penalty_when_all_closed(self):
        players = _make_players(self.mode, 2)
        self.mode.process_throw(players, 0, _make_dart(20, "Treble", 3))
        self.mode.process_throw(players, 1, _make_dart(20, "Treble", 3))
        # Now both closed; P1 hits 20 → no penalty
        result = self.mode.process_throw(players, 0, _make_dart(20, "Single"))
        assert result["score_delta"] == 0

    def test_win_requires_all_closed_and_lowest_score(self):
        players = _make_players(self.mode, 2)
        # Close all for both players — P1 has higher score
        for p in players:
            for t in CRICKET_TARGETS:
                p["marks"][t] = 3
                p["closed"][t] = True
        players[0]["score"] = 100  # higher
        players[1]["score"] = 50   # lower
        assert self.mode.check_win(players) == players[1]["id"]

    def test_no_win_if_not_all_fully_closed(self):
        players = _make_players(self.mode, 2)
        # Only P1 fully closed
        for t in CRICKET_TARGETS:
            players[0]["marks"][t] = 3
            players[0]["closed"][t] = True
        assert self.mode.check_win(players) is None


# ===========================================================================
# Around the Clock
# ===========================================================================

class TestAroundTheClockMode:
    def setup_method(self):
        self.mode = AroundTheClockMode()

    def test_create_player_starts_at_index_0(self):
        p = self.mode.create_player("p1", "Alice")
        assert p["target_index"] == 0  # target = 1

    def test_hit_advances_target(self):
        players = _make_players(self.mode, 1)
        result = self.mode.process_throw(players, 0, _make_dart(1, "Single"))
        assert players[0]["target_index"] == 1  # now targeting 2
        assert result["score_delta"] == 1

    def test_miss_does_not_advance(self):
        players = _make_players(self.mode, 1)
        self.mode.process_throw(players, 0, _make_dart(2, "Single"))  # wrong number
        assert players[0]["target_index"] == 0

    def test_double_advances_two(self):
        players = _make_players(self.mode, 1)
        self.mode.process_throw(players, 0, _make_dart(1, "Double", 2, 2))
        assert players[0]["target_index"] == 2  # skip to 3

    def test_treble_advances_three(self):
        players = _make_players(self.mode, 1)
        self.mode.process_throw(players, 0, _make_dart(1, "Treble", 3, 3))
        assert players[0]["target_index"] == 3  # skip to 4

    def test_win_after_bull(self):
        players = _make_players(self.mode, 1)
        players[0]["target_index"] = len(SEQUENCE) - 1  # on "bull"
        self.mode.process_throw(players, 0, _make_dart(0, "Bull", 1, 25))
        assert self.mode.check_win(players) == players[0]["id"]

    def test_no_win_before_bull(self):
        players = _make_players(self.mode, 1)
        players[0]["target_index"] = len(SEQUENCE) - 2  # on 20
        assert self.mode.check_win(players) is None

    def test_bull_target_resolved(self):
        players = _make_players(self.mode, 1)
        players[0]["target_index"] = len(SEQUENCE) - 1
        result = self.mode.process_throw(players, 0, _make_dart(0, "Bullseye", 1, 50))
        # Bullseye = 2 marks but we're at the last target; cap at sequence length
        assert players[0]["target_index"] >= len(SEQUENCE)

    def test_scoreboard_shows_current_target(self):
        players = _make_players(self.mode, 1)
        rows = self.mode.scoreboard_rows(players)
        assert rows[0]["display"] == "1"  # current target is 1
