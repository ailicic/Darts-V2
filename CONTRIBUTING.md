# Contributing to Darts-V2

## Overview

Darts-V2 is a real-time dart detection and game management application. The backend is Python (Flask + Flask-SocketIO + OpenCV + SQLite) and the frontend is vanilla HTML/CSS/JS.

## Development setup

```bash
# Clone and enter the repo
git clone https://github.com/ailicic/Darts-V2.git
cd Darts-V2

# Install dependencies
pip install -r requirements.txt

# Run tests (must be green before any PR)
python -m pytest tests/ -v

# Start the server
cd backend && python app.py
# Open http://localhost:5000
```

## Project structure

```
Darts-V2/
├── backend/
│   ├── app.py              ← Flask + Socket.IO server, REST API, camera loop
│   ├── detector.py         ← OpenCV dart & dartboard detection
│   ├── dartboard.py        ← Scoring geometry (segments, rings, score calc)
│   ├── database.py         ← SQLite persistence
│   ├── game_manager.py     ← In-memory game store + short-code generation
│   ├── game_modes/         ← Pluggable game-mode modules
│   │   ├── __init__.py     ← Mode registry
│   │   ├── base.py         ← Abstract GameMode interface
│   │   ├── detection.py    ← Default: cumulative detection score
│   │   ├── x01.py          ← 501 / 301 countdown mode
│   │   ├── cricket.py      ← Standard Cricket
│   │   ├── cut_throat.py   ← Cut Throat Cricket (penalties go to opponents)
│   │   └── around_the_clock.py ← Sequential target 1→20→Bull
│   └── requirements.txt
├── frontend/
│   ├── landing.html        ← Entry point: mode & flow selector
│   ├── setup.html          ← Game setup: players, mode, group
│   ├── index.html          ← Detection/play UI (game overlay when gameId in URL)
│   ├── css/style.css
│   └── js/
│       ├── app.js          ← Detection UI logic
│       ├── setup.js        ← Setup page logic
│       ├── game.js         ← Game overlay logic
│       └── socket.io.min.js
├── tests/
│   ├── test_dartboard.py
│   ├── test_database.py
│   ├── test_game_modes.py
│   └── test_game_manager.py
└── README.md
```

## Public launch plan (phase-by-phase roadmap)

This plan transforms Darts-V2 from an internal tool into something any group of people can open and immediately use.

### Phase 0 — Housekeeping ✅
- No `.bak` files in `public/`/`frontend/`
- `python -m pytest tests/` must be green on clean checkout

### Phase 1 — Landing page / mode selector + short room codes ✅
- `landing.html` at `GET /` offers mode choices (TV, single-phone, individual phones)
- `setup.html` at `GET /setup` for entering players and choosing game mode
- Short 5-char codes generated at game creation, e.g. `X7K2A`
- `GET /api/games/by-code/<code>` resolves to a game state

### Phase 2 — Groups / leaderboard isolation ✅
- New `groups` table in SQLite (id, slug, name, created_at)
- `games` and `sessions` linked to a `group_id`
- `GET /g/<slug>` sets localStorage `groupId` and forwards to setup
- Leaderboard endpoint `GET /api/leaderboard` filters by group from query-param

### Phase 3 — Additional game modes ✅
- Pluggable `game_modes/` folder; each mode exports a `GameMode` subclass
- Modes: `detection` (default, cumulative), `501`, `cricket`, `cut_throat`, `around_the_clock`
- `processThrow` / `check_win` contract stable; existing tests must pass without changes

### Phase 4 — Infrastructure hardening ✅
- `flask-limiter`: `POST /api/games` capped at 10 games/IP/10 min
- Input sanitisation on player names, slugs, mode IDs
- Background task deletes games inactive > 6 h
- `.env.example` documents all tuneable env vars

### Phase 5 — Mobile UX polish ✅
- Touch targets ≥ 44 × 44 px in `style.css`
- Current-player indicator visible at top of play page
- Offline banner when Socket.IO disconnects; auto-reconnect with backoff

### Phase 6 — Nice-to-have (post-launch)
- Onboarding micro-tutorial (3 slides, skip)
- Read-only spectator link `/watch/<gameId>`
- PWA manifest + service worker for static assets
- i18n strings in `frontend/i18n/sr.json` + `en.json`
- Rules card per game mode in setup/play UI

## Commit conventions

- Each phase = one PR; don't merge until `python -m pytest tests/ -v` is fully green.
- Do **not** change the Cut Throat or any game-mode logic after tests are written for it unless you also update the tests.
- API contracts (route paths, request/response shapes) may only be changed if all clients (`landing.html`, `setup.html`, `index.html`) are updated in the same commit.

## Environment variables (see `.env.example`)

| Variable | Default | Description |
|---|---|---|
| `FLASK_PORT` | `5000` | Port to listen on |
| `GAME_TTL_HOURS` | `6` | Hours of inactivity before a game is purged |
| `RATE_LIMIT_GAMES` | `10/10 minutes` | Rate limit for POST /api/games per IP |
| `DEFAULT_GROUP_SLUG` | `default` | Slug for the legacy/default group |
