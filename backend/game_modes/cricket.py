"""
Standard Cricket game mode.

Targets: 20, 19, 18, 17, 16, 15, Bull.

Rules:
  - Each number needs 3 marks to be *closed* by a player.
    Single = 1 mark, Double = 2 marks, Treble = 3 marks.
    Bull (25) = 1 mark, Bullseye (50) = 2 marks.
  - Once you close a number that opponents have *not* yet closed,
    additional hits on that number score points **for you**.
  - Win condition: close all 7 targets AND have a score ≥ all opponents' scores.
    (If you've closed everything but trail on points you must keep scoring to
    surpass opponents before they can close.)
"""

from typing import Optional

from .base import GameMode

CRICKET_TARGETS = [20, 19, 18, 17, 16, 15, "bull"]


class CricketMode(GameMode):
    id = "cricket"
    label = "Cricket"
    rules_summary = (
        "Close 20→15 and Bull (3 marks each). "
        "Once you close a number that others haven't, extra hits score for you. "
        "Win by closing all numbers with the highest (or tied) score."
    )
    darts_per_turn = 3

    def create_player(self, player_id: str, name: str) -> dict:
        return {
            "id": player_id,
            "name": name,
            "marks": {t: 0 for t in CRICKET_TARGETS},
            "closed": {t: False for t in CRICKET_TARGETS},
            "score": 0,
            "darts_this_turn": 0,
            "darts_thrown": 0,
        }

    def on_turn_start(self, players: list, current_player_index: int) -> None:
        players[current_player_index]["darts_this_turn"] = 0

    def process_throw(self, players: list, current_player_index: int, dart: dict) -> dict:
        player = players[current_player_index]
        number = dart.get("number", 0)
        zone = dart.get("zone", "Single")
        multiplier = dart.get("multiplier", 1)

        target, hit_marks = _resolve_target(number, zone, multiplier)
        player["darts_this_turn"] += 1
        player["darts_thrown"] += 1

        score_delta = 0
        message = ""

        if target is None:
            # Not a cricket target
            message = "Not a cricket target"
            turn_complete = player["darts_this_turn"] >= self.darts_per_turn
            return {
                "valid": True, "bust": False, "score_delta": 0,
                "turn_complete": turn_complete, "message": message,
            }

        current_marks = player["marks"][target]
        already_closed = player["closed"][target]

        if already_closed:
            # Already closed — check if any opponent is still open
            open_opponents = _open_opponents(players, current_player_index, target)
            if open_opponents:
                # Score points for each hit mark against each open opponent
                pts = _target_value(target) * hit_marks
                player["score"] += pts
                score_delta = pts
                message = f"+{pts} pts on {target}"
            else:
                message = f"{target} already closed by all — no score"
        else:
            # Still closing
            added = min(hit_marks, 3 - current_marks)
            player["marks"][target] = min(3, current_marks + hit_marks)
            overflow = hit_marks - added  # marks beyond the 3 needed to close

            if player["marks"][target] >= 3:
                player["closed"][target] = True
                message = f"Closed {target}!"
                # Overflow marks score if opponents still open
                if overflow > 0:
                    open_opponents = _open_opponents(players, current_player_index, target)
                    if open_opponents:
                        pts = _target_value(target) * overflow
                        player["score"] += pts
                        score_delta = pts
                        message += f" +{pts} pts"
            else:
                message = f"{target}: {player['marks'][target]}/3 marks"

        turn_complete = player["darts_this_turn"] >= self.darts_per_turn
        return {
            "valid": True, "bust": False, "score_delta": score_delta,
            "turn_complete": turn_complete, "message": message,
        }

    def check_win(self, players: list) -> Optional[str]:
        for p in players:
            if all(p["closed"][t] for t in CRICKET_TARGETS):
                # Must also have score ≥ every other player
                if all(p["score"] >= other["score"] for other in players if other["id"] != p["id"]):
                    return p["id"]
        return None

    def scoreboard_rows(self, players: list) -> list:
        rows = []
        for p in players:
            closed_count = sum(1 for t in CRICKET_TARGETS if p["closed"][t])
            rows.append({
                "id": p["id"],
                "name": p["name"],
                "display": str(p["score"]),
                "marks": {str(t): p["marks"][t] for t in CRICKET_TARGETS},
                "closed": {str(t): p["closed"][t] for t in CRICKET_TARGETS},
                "extra": f"{closed_count}/7 closed",
            })
        return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_target(number: int, zone: str, multiplier: int):
    """Return (target, hit_marks) or (None, 0) if not a cricket target."""
    if zone == "Miss":
        return None, 0
    if zone in ("Bull", "Bullseye"):
        marks = 1 if zone == "Bull" else 2
        return "bull", marks
    if number in CRICKET_TARGETS:
        return number, multiplier
    return None, 0


def _target_value(target) -> int:
    if target == "bull":
        return 25
    return int(target)


def _open_opponents(players: list, current_idx: int, target) -> list:
    """Return list of opponent player dicts that have NOT closed *target*."""
    return [
        p for i, p in enumerate(players)
        if i != current_idx and not p["closed"][target]
    ]
