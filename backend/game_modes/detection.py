"""
Detection Score mode — the original single-session accumulation mode.

Players take turns throwing; each throw adds to that player's cumulative score.
No win condition (practice / warmup mode).
"""

from .base import GameMode


class DetectionMode(GameMode):
    id = "detection"
    label = "Detection Score"
    rules_summary = (
        "Each dart adds its face value to your total. "
        "No win condition — use for practice or calibration."
    )
    darts_per_turn = 3

    def create_player(self, player_id: str, name: str) -> dict:
        return {
            "id": player_id,
            "name": name,
            "score": 0,
            "darts_this_turn": 0,
            "darts_thrown": 0,
        }

    def process_throw(self, players: list, current_player_index: int, dart: dict) -> dict:
        player = players[current_player_index]
        score = dart.get("score", 0)

        player["score"] += score
        player["darts_this_turn"] += 1
        player["darts_thrown"] += 1

        turn_complete = player["darts_this_turn"] >= self.darts_per_turn

        return {
            "valid": True,
            "bust": False,
            "score_delta": score,
            "turn_complete": turn_complete,
            "message": f"{dart.get('zone', '')} {dart.get('number', '')} = {score}",
        }

    def on_turn_start(self, players: list, current_player_index: int) -> None:
        players[current_player_index]["darts_this_turn"] = 0

    def check_win(self, players: list):
        return None  # no win condition

    def scoreboard_rows(self, players: list) -> list:
        return [
            {"id": p["id"], "name": p["name"], "display": str(p["score"]), "extra": f"{p['darts_thrown']} darts"}
            for p in players
        ]
