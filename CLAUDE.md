# CLAUDE.md — Notes for AI coding agents

## Stack

- **Backend**: Python 3.10+, Flask, Flask-SocketIO, OpenCV, NumPy, SQLite
- **Frontend**: Vanilla HTML5 / CSS3 / JavaScript (no framework), Socket.IO client
- **Tests**: `pytest` — run with `python -m pytest tests/ -v` from repo root

## Source-of-truth files

| File | Role |
|---|---|
| `backend/app.py` | Flask + Socket.IO server, REST API, camera loop, WebSocket handlers |
| `backend/detector.py` | OpenCV dart & dartboard detection (frame diff, Hough circles) |
| `backend/dartboard.py` | Pure scoring geometry — do not change without updating tests |
| `backend/database.py` | SQLite schema + all DB helpers |
| `backend/game_manager.py` | In-memory game store, short-code generation |
| `backend/game_modes/` | Pluggable game mode modules (one class per mode) |
| `frontend/landing.html` | Entry point served at `GET /` |
| `frontend/setup.html` | Game setup page |
| `frontend/index.html` | Detection + play UI |

## Rules for agents

1. **Run `python -m pytest tests/ -v` before and after every change.**  
   Do not proceed to the next phase if tests are red.

2. **Do not break existing API contracts** without updating every client  
   (`landing.html`, `setup.html`, `index.html`).

3. **Do not modify `dartboard.py` scoring logic** without also updating  
   `tests/test_dartboard.py` to prove identical behaviour.

4. **Game mode contract** (`backend/game_modes/base.py`):  
   - `create_player(id, name) -> dict`  
   - `process_throw(players, current_player_index, dart) -> dict`  
   - `check_win(players) -> str | None`  
   Adding a new mode = new file in `game_modes/` + register in `game_modes/__init__.py` + test in `tests/test_game_modes.py`.

5. **In-memory game store** (`game_manager.py`) is the single source of truth for active games.  
   SQLite (`database.py`) is for persistence of finished sessions and leaderboard data.

6. **One server instance** constraint: `games` dict in `game_manager.py` is in-process only.  
   If horizontal scaling is needed in the future, see CONTRIBUTING.md Phase 6 notes.

7. **Rate limiting** is applied at `POST /api/games` via `flask-limiter`.  
   Default: 10 games / IP / 10 minutes (overridable via `RATE_LIMIT_GAMES` env var).

## Public launch plan execution order

See `CONTRIBUTING.md` for the full plan. Execution order:

1. Phase 0 — housekeeping ✅
2. Phase 1 — landing + short codes
3. Phase 2 — groups / leaderboard isolation
4. Phase 4 (partial) — rate limiting + cleanup (security-critical, before public exposure)
5. Phase 3 — game modes
6. Phase 5 — mobile UX polish
7. Phase 6 — nice-to-have (post-launch)
