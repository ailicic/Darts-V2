"""
Dart Detection Server
=====================
Flask + Flask-SocketIO backend.

Routes
------
GET  /                     – Serve the frontend index.html
GET  /video_feed            – MJPEG stream
GET  /api/status            – JSON status snapshot
GET  /api/export/<fmt>      – Export session as CSV or JSON
GET  /api/cameras           – List available camera indices

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
frame             – MJPEG frame (base64 JPEG)
board_detected    – Dartboard found automatically
dart_detected     – New dart scored
dart_undone       – Last dart removed
scores_cleared    – Session reset
calibration_set   – Manual calibration acknowledged
overlay_toggled   – Overlay state changed
"""

import base64
import csv
import io
import os
import threading
import time
import uuid
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from database import (
    clear_session_hits,
    create_session,
    delete_last_hit,
    get_session_hits,
    init_db,
    log_dart_hit,
)
from detector import DartDetector

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, template_folder=FRONTEND_DIR)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

init_db()

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
        socketio.emit("error", {"message": f"Cannot open camera {cam_idx}"})
        with _state_lock:
            _state["camera_running"] = False
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
# HTTP routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path: str):
    return send_from_directory(FRONTEND_DIR, path)


@app.route("/video_feed")
def video_feed():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Dart Detection Server")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)
