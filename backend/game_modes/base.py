"""
Abstract base class for all game modes.

Every game mode must subclass GameMode and implement:
  - create_player(player_id, name) -> dict
  - process_throw(players, current_player_index, dart) -> dict
  - check_win(players) -> str | None

The dart dict passed to process_throw has these keys:
  number, zone, multiplier, score, confidence, manual (bool)
"""

from abc import ABC, abstractmethod
from typing import Optional


class GameMode(ABC):
    """Abstract interface that every game mode must implement."""

    #: Short machine-readable identifier, e.g. "501" or "cut_throat"
    id: str = ""
    #: Human-readable label shown in the UI
    label: str = ""
    #: One-line rules summary shown on the setup/play page
    rules_summary: str = ""
    #: How many darts each player throws per turn
    darts_per_turn: int = 3

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------

    @abstractmethod
    def create_player(self, player_id: str, name: str) -> dict:
        """Return a fresh player-state dict for this mode."""

    @abstractmethod
    def process_throw(
        self,
        players: list,
        current_player_index: int,
        dart: dict,
    ) -> dict:
        """
        Process one dart throw.  Mutates the relevant player dict in *players*
        and returns a result dict:

        {
            "valid":          bool,   # dart scored (not a bust/miss-turn)
            "bust":           bool,   # bust — turn voided
            "score_delta":    int,    # points actually credited this dart
            "turn_complete":  bool,   # True → caller should advance to next player
            "message":        str,    # human-readable event description
        }
        """

    @abstractmethod
    def check_win(self, players: list) -> Optional[str]:
        """
        Inspect *players* and return the winner's player_id, or None if the
        game is still in progress.
        """

    # ------------------------------------------------------------------
    # Optional hooks (sensible defaults provided)
    # ------------------------------------------------------------------

    def on_turn_start(self, players: list, current_player_index: int) -> None:
        """Called just before a player's turn begins.  Override to reset per-turn state."""

    def scoreboard_rows(self, players: list) -> list:
        """
        Return a list of dicts used to render the scoreboard.
        Each dict should have at minimum: id, name, display (primary score string).
        """
        return [
            {"id": p["id"], "name": p["name"], "display": str(p.get("score", 0))}
            for p in players
        ]
