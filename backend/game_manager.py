"""
In-memory game store with short-code generation.

All active games live in the module-level ``_games`` dict keyed by UUID.
Short codes are separate 5-character strings that map back to UUIDs.

Thread safety: all mutations use ``_lock`` (threading.Lock).

Games are auto-expired after ``GAME_TTL_HOURS`` hours of inactivity.
A background thread (``start_cleanup_thread``) must be called once at
app startup to enable this.
"""

import os
import random
import string
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from game_modes import get_mode, list_modes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Short code alphabet — excludes visually ambiguous characters (0, O, I, 1, l)
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 5
GAME_TTL_HOURS = float(os.getenv("GAME_TTL_HOURS", "6"))

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_games: dict = {}       # gameId → game dict
_code_index: dict = {}  # shortCode → gameId

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_game(
    mode_id: str,
    player_names: list,
    group_id: Optional[str] = None,
) -> dict:
    """
    Create a new game, register it, and return the full game dict.

    Raises ValueError on invalid mode or empty player list.
    """
    if not player_names:
        raise ValueError("At least one player is required.")
    # Sanitise names
    cleaned = [_sanitize_name(n) for n in player_names]
    if any(not n for n in cleaned):
        raise ValueError("Player names must not be empty after sanitisation.")

    mode = get_mode(mode_id)  # raises KeyError on unknown mode

    game_id = str(uuid.uuid4())
    short_code = _generate_unique_code()

    players = [mode.create_player(str(uuid.uuid4()), name) for name in cleaned]

    now = datetime.now(timezone.utc).isoformat()
    game: dict = {
        "id": game_id,
        "short_code": short_code,
        "mode": mode_id,
        "status": "active",            # active | finished
        "players": players,
        "current_player_index": 0,
        "winner_id": None,
        "dart_log": [],
        "group_id": group_id,
        "created_at": now,
        "last_activity": time.time(),
        "darts_this_turn": 0,
    }

    # Let the mode initialise the first player's turn state
    mode.on_turn_start(players, 0)

    with _lock:
        _games[game_id] = game
        _code_index[short_code] = game_id

    return _public_game(game)


def get_game(game_id: str) -> Optional[dict]:
    """Return a public snapshot of the game, or None if not found."""
    with _lock:
        game = _games.get(game_id)
    return _public_game(game) if game else None


def get_game_by_code(short_code: str) -> Optional[dict]:
    """Look up a game by its short code and return a public snapshot."""
    with _lock:
        game_id = _code_index.get(short_code.upper())
        game = _games.get(game_id) if game_id else None
    return _public_game(game) if game else None


def apply_throw(game_id: str, dart: dict) -> Optional[dict]:
    """
    Apply one dart throw to the active game.

    Returns a result dict::

        {
            "game":          <public game snapshot>,
            "throw_result":  <dict from mode.process_throw>,
            "winner_id":     <str | None>,
        }

    Returns None if the game is not found or already finished.
    """
    with _lock:
        game = _games.get(game_id)
        if not game or game["status"] != "active":
            return None

        mode = get_mode(game["mode"])
        players = game["players"]
        idx = game["current_player_index"]

        result = mode.process_throw(players, idx, dart)

        # Log the dart
        game["dart_log"].append({
            **dart,
            "player_id": players[idx]["id"],
            "player_name": players[idx]["name"],
            "turn_result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        game["last_activity"] = time.time()

        winner_id = mode.check_win(players)

        if winner_id:
            game["status"] = "finished"
            game["winner_id"] = winner_id

        elif result.get("turn_complete"):
            _advance_turn(game, mode)

        return {
            "game": _public_game(game),
            "throw_result": result,
            "winner_id": winner_id,
        }


def end_turn(game_id: str) -> Optional[dict]:
    """Manually end the current player's turn and advance."""
    with _lock:
        game = _games.get(game_id)
        if not game or game["status"] != "active":
            return None
        mode = get_mode(game["mode"])
        _advance_turn(game, mode)
        game["last_activity"] = time.time()
        return _public_game(game)


def undo_last_throw(game_id: str) -> Optional[dict]:
    """
    Remove the most recent dart from the log and revert player state.
    Only the last dart of the *current* player's turn can be undone.

    Returns a public game snapshot, or None if not found / nothing to undo.
    """
    with _lock:
        game = _games.get(game_id)
        if not game or not game["dart_log"]:
            return None

        mode = get_mode(game["mode"])
        players = game["players"]
        idx = game["current_player_index"]
        current_pid = players[idx]["id"]

        last = game["dart_log"][-1]
        if last["player_id"] != current_pid:
            return None  # can only undo current turn

        game["dart_log"].pop()
        # Re-derive player state from scratch using remaining log entries
        _rebuild_player_state(game, mode)
        game["last_activity"] = time.time()
        return _public_game(game)


def list_available_modes() -> list:
    """Return metadata for all registered game modes."""
    return list_modes()


def active_games_count() -> int:
    with _lock:
        return sum(1 for g in _games.values() if g["status"] == "active")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def purge_old_games() -> int:
    """Remove games that have been inactive for more than GAME_TTL_HOURS."""
    cutoff = time.time() - GAME_TTL_HOURS * 3600
    removed = 0
    with _lock:
        stale = [gid for gid, g in _games.items() if g["last_activity"] < cutoff]
        for gid in stale:
            code = _games[gid].get("short_code")
            del _games[gid]
            if code:
                _code_index.pop(code, None)
            removed += 1
    return removed


def start_cleanup_thread(interval_seconds: int = 1800) -> None:
    """Start a daemon thread that calls purge_old_games every *interval_seconds*."""
    def _loop():
        while True:
            time.sleep(interval_seconds)
            purge_old_games()

    t = threading.Thread(target=_loop, daemon=True, name="game-cleanup")
    t.start()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _generate_unique_code() -> str:
    """Generate a unique short code not already in use."""
    with _lock:
        for _ in range(100):
            code = "".join(random.choices(_ALPHABET, k=_CODE_LENGTH))
            if code not in _code_index:
                return code
    raise RuntimeError("Could not generate a unique short code after 100 attempts.")


def _advance_turn(game: dict, mode) -> None:
    """Move to the next player and call on_turn_start.  Called with _lock held."""
    players = game["players"]
    n = len(players)
    game["current_player_index"] = (game["current_player_index"] + 1) % n
    mode.on_turn_start(players, game["current_player_index"])


def _rebuild_player_state(game: dict, mode) -> None:
    """
    Rebuild all player states from the dart log from scratch.
    Used by undo to revert state correctly.
    """
    players = game["players"]
    for p in players:
        # Reset to initial state
        fresh = mode.create_player(p["id"], p["name"])
        p.clear()
        p.update(fresh)

    game["current_player_index"] = 0
    mode.on_turn_start(players, 0)

    for entry in game["dart_log"]:
        pid = entry["player_id"]
        # Find the player index
        idx = next((i for i, p in enumerate(players) if p["id"] == pid), None)
        if idx is None:
            continue
        # Make current_player_index match
        game["current_player_index"] = idx
        dart = {k: entry[k] for k in ("number", "zone", "multiplier", "score", "confidence") if k in entry}
        result = mode.process_throw(players, idx, dart)
        if result.get("turn_complete"):
            _advance_turn(game, mode)


def _public_game(game: Optional[dict]) -> Optional[dict]:
    """Return a serialisable copy safe to send to the client."""
    if game is None:
        return None
    mode = get_mode(game["mode"])
    g = deepcopy(game)
    g["scoreboard"] = mode.scoreboard_rows(g["players"])
    return g


def _sanitize_name(name: str) -> str:
    """Strip/truncate player names; allow only printable non-control characters."""
    cleaned = "".join(c for c in str(name).strip() if c.isprintable() and c not in "<>&\"'")
    return cleaned[:40]
