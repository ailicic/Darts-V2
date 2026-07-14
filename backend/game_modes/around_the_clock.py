"""
Around the Clock game mode.

Players must hit targets in sequence: 1, 2, 3, … 20, then Bull.
Any hit on the current target advances the player (Single, Double, or Treble
all count).  A Treble advances by 3 positions; a Double by 2.
The first player to complete Bull wins.
"""

from typing import Optional

from .base import GameMode

SEQUENCE = list(range(1, 21)) + ["bull"]  # 1–20 then bull


class AroundTheClockMode(GameMode):
    id = "around_the_clock"
    label = "Around the Clock"
    rules_summary = (
        "Hit 1, then 2, … 20, then Bull in order. "
        "Double advances 2 numbers, Treble advances 3. "
        "First to Bull wins."
    )
    darts_per_turn = 3

    def create_player(self, player_id: str, name: str) -> dict:
        return {
            "id": player_id,
            "name": name,
            "target_index": 0,       # index into SEQUENCE
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

        player["darts_this_turn"] += 1
        player["darts_thrown"] += 1

        target_idx = player["target_index"]
        if target_idx >= len(SEQUENCE):
            # Already won — shouldn't happen but be safe
            turn_complete = player["darts_this_turn"] >= self.darts_per_turn
            return {
                "valid": True, "bust": False, "score_delta": 0,
                "turn_complete": turn_complete, "message": "Already finished!",
            }

        current_target = SEQUENCE[target_idx]
        dart_target = _dart_to_atc_target(number, zone)

        message = ""
        score_delta = 0

        if dart_target == current_target:
            advance = multiplier  # Double → 2, Treble → 3, Single → 1
            new_idx = min(target_idx + advance, len(SEQUENCE))
            player["target_index"] = new_idx
            score_delta = advance

            if new_idx >= len(SEQUENCE):
                message = "🏆 FINISHED!"
            else:
                next_target = SEQUENCE[new_idx]
                message = f"Hit {current_target}! → next: {next_target}"
        else:
            next_target = SEQUENCE[target_idx]
            message = f"Need {next_target}"

        turn_complete = player["darts_this_turn"] >= self.darts_per_turn
        return {
            "valid": True, "bust": False, "score_delta": score_delta,
            "turn_complete": turn_complete, "message": message,
        }

    def check_win(self, players: list) -> Optional[str]:
        for p in players:
            if p["target_index"] >= len(SEQUENCE):
                return p["id"]
        return None

    def scoreboard_rows(self, players: list) -> list:
        rows = []
        for p in players:
            idx = p["target_index"]
            if idx >= len(SEQUENCE):
                display = "DONE"
                extra = "Finished!"
            else:
                display = str(SEQUENCE[idx])
                extra = f"{idx}/{len(SEQUENCE)} targets"
            rows.append({
                "id": p["id"],
                "name": p["name"],
                "display": display,
                "extra": extra,
                "target_index": idx,
                "sequence_length": len(SEQUENCE),
            })
        return rows


def _dart_to_atc_target(number: int, zone: str):
    """Convert a dart hit to the ATC target value it represents."""
    if zone in ("Bull", "Bullseye"):
        return "bull"
    if zone == "Miss":
        return None
    return number
