"""
Cut Throat Cricket game mode.

Same closing mechanics as Standard Cricket, but point scoring is reversed:
when you close a number and opponents haven't, extra hits add points to
**their** scores, not yours.  Lowest score wins.

Win condition: close all 7 targets AND have the lowest (or tied-lowest) score
among players who have also closed everything.  If you've closed everything
but lead in points you must wait for opponents to close or for your score to
become lowest.
"""

from typing import Optional

from .base import GameMode
from .cricket import (
    CRICKET_TARGETS,
    _resolve_target,
    _target_value,
)


class CutThroatMode(GameMode):
    id = "cut_throat"
    label = "Cut Throat Cricket"
    rules_summary = (
        "Close 20→15 and Bull (3 marks each). "
        "Extra hits after closing add points to opponents who haven't closed. "
        "Win by closing all numbers with the LOWEST score."
    )
    darts_per_turn = 3

    def create_player(self, player_id: str, name: str) -> dict:
        return {
            "id": player_id,
            "name": name,
            "marks": {t: 0 for t in CRICKET_TARGETS},
            "closed": {t: False for t in CRICKET_TARGETS},
            "score": 0,          # penalty points received from opponents
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

        total_penalties = 0
        message = ""

        if target is None:
            turn_complete = player["darts_this_turn"] >= self.darts_per_turn
            return {
                "valid": True, "bust": False, "score_delta": 0,
                "turn_complete": turn_complete, "message": "Not a cricket target",
            }

        already_closed = player["closed"][target]
        current_marks = player["marks"][target]

        if already_closed:
            # Apply penalty marks to each open opponent
            open_opponents = _open_opponents_ct(players, current_player_index, target)
            if open_opponents:
                pts = _target_value(target) * hit_marks
                for opp in open_opponents:
                    opp["score"] += pts
                total_penalties = pts * len(open_opponents)
                names = ", ".join(o["name"] for o in open_opponents)
                message = f"+{pts} pts each to {names}"
            else:
                message = f"{target} closed by all — no penalty"
        else:
            added = min(hit_marks, 3 - current_marks)
            player["marks"][target] = min(3, current_marks + hit_marks)
            overflow = hit_marks - added

            if player["marks"][target] >= 3:
                player["closed"][target] = True
                message = f"Closed {target}!"
                if overflow > 0:
                    open_opponents = _open_opponents_ct(players, current_player_index, target)
                    if open_opponents:
                        pts = _target_value(target) * overflow
                        for opp in open_opponents:
                            opp["score"] += pts
                        total_penalties = pts * len(open_opponents)
                        names = ", ".join(o["name"] for o in open_opponents)
                        message += f" — +{pts} pts each to {names}"
            else:
                message = f"{target}: {player['marks'][target]}/3 marks"

        turn_complete = player["darts_this_turn"] >= self.darts_per_turn
        # score_delta here represents total penalties distributed (informational)
        return {
            "valid": True, "bust": False, "score_delta": total_penalties,
            "turn_complete": turn_complete, "message": message,
        }

    def check_win(self, players: list) -> Optional[str]:
        """
        Winner is the first player who has closed all targets AND has the
        lowest score among all players who have also fully closed.
        """
        fully_closed = [
            p for p in players if all(p["closed"][t] for t in CRICKET_TARGETS)
        ]
        if not fully_closed:
            return None
        min_score = min(p["score"] for p in fully_closed)
        # Only declare a winner if everyone remaining is also fully closed
        # (otherwise the un-closed players might still close with fewer points)
        if len(fully_closed) < len(players):
            return None
        winners = [p for p in fully_closed if p["score"] == min_score]
        if len(winners) == 1:
            return winners[0]["id"]
        # Tie — no winner yet (very rare in practice)
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


def _open_opponents_ct(players: list, current_idx: int, target) -> list:
    return [
        p for i, p in enumerate(players)
        if i != current_idx and not p["closed"][target]
    ]
