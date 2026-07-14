"""
501 / X01 countdown mode.

Rules:
  - Each player starts at the configured starting score (default 501).
  - Each dart subtracts its score value.
  - A player wins by reaching exactly 0.
  - **Double-out rule:** the final dart that brings a player to 0 must land on
    a Double or Bullseye.
  - **Bust:** if a throw would take the score below 0 *or* leave exactly 1,
    the entire turn is voided (score reverts to the value at the start of that
    turn).  The turn ends immediately on a bust.
"""

from typing import Optional

from .base import GameMode


class X01Mode(GameMode):
    id = "501"
    label = "501"
    rules_summary = (
        "Start at 501. Subtract each dart. "
        "Finish on a Double or Bullseye. "
        "Going below 0 or leaving 1 is a bust — whole turn voided."
    )
    darts_per_turn = 3

    def __init__(self, starting_score: int = 501) -> None:
        self.starting_score = starting_score
        if starting_score != 501:
            self.id = str(starting_score)
            self.label = str(starting_score)

    def create_player(self, player_id: str, name: str) -> dict:
        return {
            "id": player_id,
            "name": name,
            "score": self.starting_score,
            "score_at_turn_start": self.starting_score,
            "darts_this_turn": 0,
            "darts_thrown": 0,
            "turns": 0,
            "busts": 0,
            "last_turn_score": 0,
        }

    def on_turn_start(self, players: list, current_player_index: int) -> None:
        p = players[current_player_index]
        p["score_at_turn_start"] = p["score"]
        p["darts_this_turn"] = 0

    def process_throw(self, players: list, current_player_index: int, dart: dict) -> dict:
        player = players[current_player_index]

        dart_score = dart.get("score", 0)
        zone = dart.get("zone", "Single")
        number = dart.get("number", 0)

        proposed = player["score"] - dart_score

        # --- Bust check ---
        if proposed < 0 or proposed == 1:
            player["score"] = player["score_at_turn_start"]  # revert whole turn
            player["busts"] += 1
            player["darts_this_turn"] += 1
            player["darts_thrown"] += 1
            return {
                "valid": False,
                "bust": True,
                "score_delta": 0,
                "turn_complete": True,
                "message": "Bust! Turn score voided.",
            }

        # --- Double-out check ---
        if proposed == 0:
            if zone not in ("Double", "Bullseye"):
                player["score"] = player["score_at_turn_start"]  # revert
                player["busts"] += 1
                player["darts_this_turn"] += 1
                player["darts_thrown"] += 1
                return {
                    "valid": False,
                    "bust": True,
                    "score_delta": 0,
                    "turn_complete": True,
                    "message": "Must finish on Double or Bullseye!",
                }
            # Valid finish
            player["score"] = 0
            player["darts_this_turn"] += 1
            player["darts_thrown"] += 1
            player["last_turn_score"] = player["score_at_turn_start"] - 0
            return {
                "valid": True,
                "bust": False,
                "score_delta": dart_score,
                "turn_complete": True,
                "message": f"🏆 CHECKOUT! {zone} {number if number else ''}",
            }

        # --- Normal throw ---
        scored = player["score"] - proposed
        player["score"] = proposed
        player["darts_this_turn"] += 1
        player["darts_thrown"] += 1

        turn_complete = player["darts_this_turn"] >= self.darts_per_turn
        if turn_complete:
            player["last_turn_score"] = player["score_at_turn_start"] - proposed

        label = _dart_label(zone, number, dart.get("multiplier", 1), dart_score)
        return {
            "valid": True,
            "bust": False,
            "score_delta": scored,
            "turn_complete": turn_complete,
            "message": f"{label} — {proposed} remaining",
        }

    def check_win(self, players: list) -> Optional[str]:
        for p in players:
            if p["score"] == 0:
                return p["id"]
        return None

    def scoreboard_rows(self, players: list) -> list:
        rows = []
        for p in players:
            rows.append({
                "id": p["id"],
                "name": p["name"],
                "display": str(p["score"]),
                "extra": f"Last turn: {p.get('last_turn_score', 0)}",
                "darts_thrown": p["darts_thrown"],
            })
        return rows


def _dart_label(zone: str, number: int, multiplier: int, score: int) -> str:
    if zone == "Bullseye":
        return "Bullseye (50)"
    if zone == "Bull":
        return "Bull (25)"
    if zone == "Miss":
        return "Miss"
    prefix = f"{zone} " if multiplier > 1 else ""
    return f"{prefix}{number} = {score}"
