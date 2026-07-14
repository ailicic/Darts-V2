"""
Dart Detection Server
=====================
Flask + Flask-SocketIO backend.

Routes
------
GET  /                        – Landing page (mode selector)
GET  /setup                   – Game setup page
GET  /g/<slug>                – Join a group (sets cookie, redirects to setup)
GET  /detect                  – Standalone detection UI (backward compat)
GET  /video_feed              – MJPEG stream
GET  /api/status              – JSON status snapshot
GET  /api/export/<fmt>        – Export session as CSV or JSON
GET  /api/cameras             – List available camera indices
GET  /api/modes               – List available game modes

Game API
--------
POST /api/games               – Create a new game  {mode, players[], group_id?}
GET  /api/games/<id>          – Get game state
GET  /api/games/by-code/<c>   – Lookup game by short code
POST /api/games/<id>/throw    – Submit a manual dart throw
POST /api/games/<id>/end-turn – End the current player's turn early
POST /api/games/<id>/undo     – Undo the last dart of current turn

Group API
---------
POST /api/groups              – Create a group  {slug, name}
GET  /api/groups/<slug>       – Get group info
GET  /api/leaderboard         – Recent finished games  [?group_id&mode&limit]

WebSocket events (client → server)
-----------------------------------
start_camera      – Open camera and begin MJPEG stream
stop_camera       – Close camera
start_detection   – Enable dart-detection logic
stop_detection    – Disable dart-detection logic
toggle_overlay    – Toggle dartboard overlay on/off
clear_scores      – Reset current session
undo_last         – Remove last detected dart
manual_correction – Add a dart hit entered by the user
                    payload: {number, zone}
set_calibration   – Provide board centre + radius manually
                    payload: {center_x, center_y, radius}
reset_reference   – Re-snapshot the current frame as baseline

WebSocket events (server → client)
-----------------------------------
status            – Full status on connect
board_detected    – Dartboard found automatically
dart_detected     – New dart scored
dart_undone       – Last dart removed
scores_cleared    – Session reset
calibration_set   – Manual calibration acknowledged
overlay_toggled   – Overlay state changed
game_updated      – Game state changed (throw, undo, end-turn)
game_won          – A player has won the game
"""

import csv
import io
import os
import threading
import time
import uuid
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response, jsonify, redirect, request, send_from_directory, url_for
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit

import game_manager
from database import (
    clear_session_hits,
    create_group,
    create_session,
    delete_last_hit,
    get_group_by_id,
    get_group_by_slug,
    get_leaderboard,
    get_session_hits,
    init_db,
    log_dart_hit,
    save_finished_game,
)
from detector import DartDetector

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, template_folder=FRONTEND_DIR)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Rate limiter – default key: remote IP
_rate_limit_games = os.getenv("RATE_LIMIT_GAMES", "10 per 10 minutes")
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

init_db()
game_manager.start_cleanup_thread()

# ---------------------------------------------------------------------------
# Global mutable state (all access serialised via _state_lock)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Global mutable state (all access serialised via _state_lock)
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()

_state: dict = {
    "camera_running": False,
    "detection_active": False,
    "overlay_enabled": True,
    "total_score": 0,
    "dart_history": [],
    "session_id": str(uuid.uuid4()),
    "camera_index": 0,
    "fps": 0.0,
    "calibrated": False,
    "active_game_id": None,    # game routed darts to this game (if any)
}

# The reference frame is used as the "board with N darts already in it"
# baseline for detecting the next dart.
_detector = DartDetector()

# Camera capture thread
_camera_thread: threading.Thread | None = None

# Shared frame for MJPEG streaming (BGR numpy array)
_frame_lock = threading.Lock()
_current_frame: np.ndarray | None = None

create_session(_state["session_id"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_state_snapshot() -> dict:
    with _state_lock:
        return {
            "camera_running": _state["camera_running"],
            "detection_active": _state["detection_active"],
            "overlay_enabled": _state["overlay_enabled"],
            "total_score": _state["total_score"],
            "dart_history": list(_state["dart_history"]),
            "calibrated": _state["calibrated"],
            "fps": _state["fps"],
            "active_game_id": _state["active_game_id"],
        }


def _make_dart_entry(
    number: int,
    zone: str,
    multiplier: int,
    score: int,
    confidence: float,
    manual: bool = False,
) -> dict:
    with _state_lock:
        dart_id = len(_state["dart_history"]) + 1
    return {
        "id": dart_id,
        "timestamp": datetime.now().isoformat(),
        "number": number,
        "zone": zone,
        "multiplier": multiplier,
        "score": score,
        "confidence": round(confidence, 3),
        "manual": manual,
    }


# ---------------------------------------------------------------------------
# Camera capture thread
# ---------------------------------------------------------------------------

def _camera_loop() -> None:
    """Background thread: capture, optionally process, stream frames."""
    global _current_frame

    with _state_lock:
        cam_idx = _state["camera_index"]

    cap = cv2.VideoCapture(cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if not cap.isOpened():
        with _state_lock:
            _state["camera_running"] = False
        socketio.emit("camera_stopped", {"error": f"Cannot open camera {cam_idx}"})
        return

    frame_count = 0
    fps_timer = time.time()
    last_board_check = 0.0
    last_dart_check = 0.0
    last_detected_tips: list = []

    while True:
        with _state_lock:
            still_running = _state["camera_running"]
            detection_on = _state["detection_active"]
            overlay_on = _state["overlay_enabled"]

        if not still_running:
            break

        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        now = time.time()

        # FPS bookkeeping
        frame_count += 1
        if now - fps_timer >= 1.0:
            fps_val = frame_count / (now - fps_timer)
            frame_count = 0
            fps_timer = now
            with _state_lock:
                _state["fps"] = round(fps_val, 1)

        # --- Dartboard auto-detection (every 3 s until calibrated) ---------
        if not _detector.calibrated and (now - last_board_check) >= 3.0:
            last_board_check = now
            if _detector.detect_dartboard(frame):
                with _state_lock:
                    _state["calibrated"] = True
                socketio.emit(
                    "board_detected",
                    {
                        "center": list(_detector.board_center),
                        "radius": _detector.board_radius,
                    },
                )
                # Capture baseline immediately after calibration
                _detector.capture_reference(frame)

        # --- Dart detection (every 0.5 s when active) ----------------------
        if detection_on and _detector.calibrated and (now - last_dart_check) >= 0.5:
            last_dart_check = now
            tips = _detector.detect_darts(frame)
            last_detected_tips = tips

            cooldown_ok = (now - _detector.last_detection_time) >= _detector.DETECTION_COOLDOWN
            if tips and cooldown_ok:
                _detector.last_detection_time = now
                tip = tips[0]
                result = _detector.analyse_hit(tip, confidence=0.75)

                if result and result["zone"] != "Miss":
                    with _state_lock:
                        sid = _state["session_id"]
                        entry = _make_dart_entry(
                            result["number"],
                            result["zone"],
                            result["multiplier"],
                            result["score"],
                            result["confidence"],
                        )
                        _state["dart_history"].append(entry)
                        _state["total_score"] += result["score"]
                        total = _state["total_score"]

                    log_dart_hit(
                        sid,
                        result["number"],
                        result["zone"],
                        result["multiplier"],
                        result["score"],
                        result["confidence"],
                        result["x"],
                        result["y"],
                    )

                    # Update baseline after logging the hit
                    _detector.capture_reference(frame)

                    socketio.emit("dart_detected", {"dart": entry, "total_score": total})

                    # --- Route dart to active game (if any) ---
                    dart_for_game = {
                        "number": result["number"],
                        "zone": result["zone"],
                        "multiplier": result["multiplier"],
                        "score": result["score"],
                        "confidence": result["confidence"],
                        "manual": False,
                    }
                    with _state_lock:
                        active_game_id = _state.get("active_game_id")
                    if active_game_id:
                        game_result = game_manager.apply_throw(active_game_id, dart_for_game)
                        if game_result:
                            _broadcast_game_update(game_result)

        # --- Build display frame -------------------------------------------
        if overlay_on and _detector.calibrated:
            display = _detector.draw_overlay(frame, darts=last_detected_tips or None)
        else:
            display = frame.copy()

        # FPS badge
        with _state_lock:
            fps_display = _state["fps"]
        cv2.putText(
            display,
            f"FPS: {fps_display:.1f}",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 230, 0),
            2,
            cv2.LINE_AA,
        )

        with _frame_lock:
            _current_frame = display

        time.sleep(1 / 30)

    cap.release()
    with _frame_lock:
        _current_frame = None


# ---------------------------------------------------------------------------
# MJPEG stream
# ---------------------------------------------------------------------------

def _generate_mjpeg():
    """Generator that yields JPEG frames as a multipart MJPEG stream."""
    while True:
        with _frame_lock:
            frame = _current_frame

        if frame is None:
            # Send a blank black frame so the browser <img> doesn't break
            placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(
                placeholder,
                "Camera offline",
                (180, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (100, 100, 100),
                2,
            )
            _, buf = cv2.imencode(".jpg", placeholder)
        else:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )
        time.sleep(1 / 30)


# ---------------------------------------------------------------------------
# HTTP routes — frontend pages
# ---------------------------------------------------------------------------

@app.route("/")
def root():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/setup")
def setup_page():
    return send_from_directory(FRONTEND_DIR, "setup.html")


@app.route("/detect")
def detect_page():
    """Standalone detection UI (backward compat — original index.html)."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/g/<slug>")
def group_join(slug: str):
    """
    Group entry point.  Redirects to /setup with the group's id embedded so
    the setup page can pre-populate groupId in localStorage.
    All user input is validated/sanitised before use; the redirect target is
    always the internal /setup path (no open-redirect risk).
    """
    from urllib.parse import urlencode

    # Allow only safe characters in slug before any use
    clean_slug = _sanitize_slug(slug)
    if not clean_slug:
        return redirect("/setup")

    group = get_group_by_slug(clean_slug)
    if not group:
        # Group doesn't exist yet — send to setup. The browser can create it there.
        # We do NOT include user-supplied data in the redirect URL.
        return redirect("/setup")

    # Use DB-returned values (trusted) for the redirect query params
    params = urlencode({"group_id": group["id"], "group_name": group["name"]})
    return redirect(f"/setup?{params}")


@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory(FRONTEND_DIR, path)


@app.route("/video_feed")
def video_feed():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# HTTP routes — detection API (unchanged)
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    return jsonify(_get_state_snapshot())


@app.route("/api/cameras")
def api_cameras():
    cameras = []
    for i in range(6):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cameras.append({"index": i, "name": f"Camera {i}"})
            cap.release()
    return jsonify(cameras)


@app.route("/api/export/<fmt>")
def api_export(fmt: str):
    with _state_lock:
        sid = _state["session_id"]
    hits = get_session_hits(sid)

    if fmt == "json":
        return jsonify(hits)

    if fmt == "csv":
        output = io.StringIO()
        if hits:
            writer = csv.DictWriter(output, fieldnames=hits[0].keys())
            writer.writeheader()
            writer.writerows(hits)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=darts_results.csv"},
        )

    return jsonify({"error": f"Unknown format: {fmt}"}), 400


# ---------------------------------------------------------------------------
# HTTP routes — game API
# ---------------------------------------------------------------------------

@app.route("/api/modes")
def api_modes():
    """List all available game modes."""
    return jsonify(game_manager.list_available_modes())


@app.route("/api/games", methods=["POST"])
@limiter.limit(_rate_limit_games)
def api_create_game():
    """
    Create a new game.

    Request body (JSON):
        mode        str  – game mode id (e.g. "501", "cricket")
        players     list – player name strings (1–8)
        group_id    str  – optional group UUID
    """
    data = request.get_json(silent=True) or {}
    mode_id = str(data.get("mode", "detection")).strip()
    raw_players = data.get("players", [])
    group_id = data.get("group_id") or None

    if not isinstance(raw_players, list) or not raw_players:
        return jsonify({"error": "players must be a non-empty list"}), 400
    if len(raw_players) > 8:
        return jsonify({"error": "Maximum 8 players"}), 400

    try:
        game = game_manager.create_game(mode_id, raw_players, group_id)
    except KeyError:
        return jsonify({"error": "Unknown game mode"}), 400
    except ValueError:
        return jsonify({"error": "Invalid player names or configuration"}), 400

    return jsonify(game), 201


@app.route("/api/games/by-code/<code>")
def api_game_by_code(code: str):
    """Look up a game by its 5-character short code."""
    game = game_manager.get_game_by_code(code)
    if not game:
        return jsonify({"error": "Game not found"}), 404
    return jsonify(game)


@app.route("/api/games/<game_id>")
def api_get_game(game_id: str):
    """Get current game state."""
    game = game_manager.get_game(game_id)
    if not game:
        return jsonify({"error": "Game not found"}), 404
    return jsonify(game)


@app.route("/api/games/<game_id>/throw", methods=["POST"])
def api_game_throw(game_id: str):
    """
    Submit a manual dart throw to a game.

    Request body (JSON): number, zone, multiplier, score
    """
    data = request.get_json(silent=True) or {}
    dart = _build_dart_from_request(data)
    if dart is None:
        return jsonify({"error": "Invalid dart data"}), 400

    result = game_manager.apply_throw(game_id, dart)
    if result is None:
        return jsonify({"error": "Game not found or already finished"}), 404

    _broadcast_game_update(result)
    return jsonify(result)


@app.route("/api/games/<game_id>/end-turn", methods=["POST"])
def api_end_turn(game_id: str):
    """Manually end the current player's turn and advance."""
    game = game_manager.end_turn(game_id)
    if game is None:
        return jsonify({"error": "Game not found or already finished"}), 404
    socketio.emit("game_updated", {"game": game, "event": "end_turn"})
    return jsonify({"game": game})


@app.route("/api/games/<game_id>/undo", methods=["POST"])
def api_undo_throw(game_id: str):
    """Undo the last dart of the current turn."""
    game = game_manager.undo_last_throw(game_id)
    if game is None:
        return jsonify({"error": "Nothing to undo"}), 400
    socketio.emit("game_updated", {"game": game, "event": "undo"})
    return jsonify({"game": game})


# ---------------------------------------------------------------------------
# HTTP routes — group API
# ---------------------------------------------------------------------------

@app.route("/api/groups", methods=["POST"])
def api_create_group():
    """
    Create a new group.

    Request body (JSON): slug (URL-friendly), name
    """
    data = request.get_json(silent=True) or {}
    slug = _sanitize_slug(str(data.get("slug", "")).strip())
    name = _sanitize_text(str(data.get("name", "")).strip())

    if not slug:
        return jsonify({"error": "slug is required"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(slug) > 40:
        return jsonify({"error": "slug must be 40 characters or fewer"}), 400

    import sqlite3
    try:
        group = create_group(str(uuid.uuid4()), slug, name)
    except sqlite3.IntegrityError:
        existing = get_group_by_slug(slug)
        if existing:
            return jsonify(existing), 200
        return jsonify({"error": "Slug already taken"}), 409

    return jsonify(group), 201


@app.route("/api/groups/<slug>")
def api_get_group(slug: str):
    """Get group info by slug."""
    group = get_group_by_slug(slug)
    if not group:
        return jsonify({"error": "Group not found"}), 404
    return jsonify(group)


@app.route("/api/leaderboard")
def api_leaderboard():
    """Recent finished games.  Query params: group_id, mode, limit (max 100)."""
    group_id = request.args.get("group_id") or None
    mode = request.args.get("mode") or None
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        limit = 20
    return jsonify(get_leaderboard(group_id=group_id, mode=mode, limit=limit))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_dart_from_request(data: dict):
    """Validate and build a dart dict from request JSON.  Returns None on error."""
    try:
        number = int(data.get("number", 0))
        zone = str(data.get("zone", "Single"))
        multiplier = int(data.get("multiplier", 1))
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        return None

    valid_zones = {"Single", "Double", "Treble", "Bull", "Bullseye", "Miss"}
    if zone not in valid_zones:
        return None
    if not (0 <= number <= 20):
        return None
    if multiplier not in (0, 1, 2, 3):
        return None

    return {
        "number": number,
        "zone": zone,
        "multiplier": multiplier,
        "score": score,
        "confidence": float(data.get("confidence", 1.0)),
        "manual": True,
    }


def _broadcast_game_update(result: dict) -> None:
    """Emit game_updated (and game_won if applicable) to all connected clients."""
    game = result.get("game", {})
    throw_result = result.get("throw_result", {})
    winner_id = result.get("winner_id")

    socketio.emit("game_updated", {
        "game": game,
        "throw_result": throw_result,
        "event": "throw",
    })

    if winner_id:
        winner_name = next(
            (p["name"] for p in game.get("players", []) if p["id"] == winner_id),
            "Unknown",
        )
        socketio.emit("game_won", {
            "game_id": game.get("id"),
            "winner_id": winner_id,
            "winner_name": winner_name,
        })
        # Persist the finished game
        _persist_finished_game(game)


def _persist_finished_game(game: dict) -> None:
    """Save a finished game to SQLite for the leaderboard."""
    try:
        save_finished_game(
            game_id=game["id"],
            short_code=game.get("short_code", ""),
            mode=game["mode"],
            group_id=game.get("group_id"),
            winner_name=next(
                (p["name"] for p in game.get("players", []) if p["id"] == game.get("winner_id")),
                None,
            ),
            player_names=[p["name"] for p in game.get("players", [])],
            dart_count=len(game.get("dart_log", [])),
            created_at=game.get("created_at", datetime.utcnow().isoformat()),
        )
    except Exception:
        pass  # leaderboard persistence is best-effort


def _sanitize_slug(text: str) -> str:
    """Allow only lowercase letters, digits, and hyphens."""
    import re
    cleaned = re.sub(r"[^a-z0-9-]", "", text.lower())
    return cleaned[:40]


def _sanitize_text(text: str) -> str:
    """Strip control characters and dangerous HTML chars."""
    return "".join(c for c in text if c.isprintable() and c not in "<>&\"'")[:80]


# ---------------------------------------------------------------------------
# WebSocket handlers
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    emit("status", _get_state_snapshot())


@socketio.on("start_camera")
def on_start_camera(data=None):
    global _camera_thread

    cam_idx = (data or {}).get("camera_index", 0)
    with _state_lock:
        if _state["camera_running"]:
            emit("camera_started", {"success": True, "already_running": True})
            return
        _state["camera_index"] = cam_idx
        _state["camera_running"] = True

    _camera_thread = threading.Thread(target=_camera_loop, daemon=True)
    _camera_thread.start()
    emit("camera_started", {"success": True})


@socketio.on("stop_camera")
def on_stop_camera():
    with _state_lock:
        _state["camera_running"] = False
        _state["detection_active"] = False
    emit("camera_stopped", {"success": True})


@socketio.on("start_detection")
def on_start_detection():
    with _state_lock:
        _state["detection_active"] = True
    # Capture a fresh baseline before we start watching for darts
    with _frame_lock:
        frame = _current_frame
    if frame is not None:
        _detector.capture_reference(frame)
    emit("detection_started", {"success": True})


@socketio.on("stop_detection")
def on_stop_detection():
    with _state_lock:
        _state["detection_active"] = False
    emit("detection_stopped", {"success": True})


@socketio.on("toggle_overlay")
def on_toggle_overlay():
    with _state_lock:
        _state["overlay_enabled"] = not _state["overlay_enabled"]
        enabled = _state["overlay_enabled"]
    emit("overlay_toggled", {"enabled": enabled})


@socketio.on("clear_scores")
def on_clear_scores():
    with _state_lock:
        sid = _state["session_id"]
        _state["total_score"] = 0
        _state["dart_history"] = []
    clear_session_hits(sid)
    emit("scores_cleared", {"success": True, "total_score": 0})


@socketio.on("undo_last")
def on_undo_last():
    with _state_lock:
        if not _state["dart_history"]:
            emit("error", {"message": "No darts to undo."})
            return
        last = _state["dart_history"].pop()
        _state["total_score"] = max(0, _state["total_score"] - last["score"])
        total = _state["total_score"]
        sid = _state["session_id"]
    delete_last_hit(sid)
    emit("dart_undone", {"removed": last, "total_score": total})


@socketio.on("manual_correction")
def on_manual_correction(data):
    number = int(data.get("number", 0))
    zone = data.get("zone", "Single")

    _zone_multipliers = {
        "Single": 1, "Double": 2, "Treble": 3, "Bull": 1, "Bullseye": 1,
    }
    multiplier = _zone_multipliers.get(zone, 1)

    if zone == "Bullseye":
        score = 50
    elif zone == "Bull":
        score = 25
    elif zone == "Miss":
        score = 0
    else:
        score = number * multiplier

    entry = _make_dart_entry(number, zone, multiplier, score, 1.0, manual=True)

    with _state_lock:
        _state["dart_history"].append(entry)
        _state["total_score"] += score
        total = _state["total_score"]
        sid = _state["session_id"]

    log_dart_hit(sid, number, zone, multiplier, score, 1.0, manual=True)
    emit("dart_detected", {"dart": entry, "total_score": total})


@socketio.on("set_calibration")
def on_set_calibration(data):
    cx = data.get("center_x")
    cy = data.get("center_y")
    radius = data.get("radius")
    if cx is None or cy is None or radius is None:
        emit("error", {"message": "center_x, center_y, and radius are required."})
        return
    _detector.set_calibration(float(cx), float(cy), float(radius))
    with _state_lock:
        _state["calibrated"] = True
    emit("calibration_set", {"success": True, "center": [cx, cy], "radius": radius})


@socketio.on("reset_reference")
def on_reset_reference():
    with _frame_lock:
        frame = _current_frame
    if frame is not None:
        _detector.capture_reference(frame)
        emit("reference_reset", {"success": True})
    else:
        emit("error", {"message": "No frame available – start the camera first."})


@socketio.on("link_game")
def on_link_game(data):
    """
    Link a game to the camera session so detected darts are routed to it.

    payload: {game_id: str}
    """
    game_id = (data or {}).get("game_id")
    if not game_id:
        emit("error", {"message": "game_id is required."})
        return
    game = game_manager.get_game(game_id)
    if not game:
        emit("error", {"message": f"Game {game_id} not found."})
        return
    if game["status"] != "active":
        emit("error", {"message": "Game is not active."})
        return
    with _state_lock:
        _state["active_game_id"] = game_id
    emit("game_linked", {"game_id": game_id, "game": game})


@socketio.on("unlink_game")
def on_unlink_game():
    """Detach the camera from any active game."""
    with _state_lock:
        _state["active_game_id"] = None
    emit("game_unlinked", {"success": True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    print("=" * 60)
    print("  Dart Detection Server")
    print(f"  Open http://localhost:{port} in your browser")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False)
