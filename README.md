# Darts-V2

Real-time dart detection application — uses a webcam pointed at a dartboard to
detect where darts have landed, calculate scores (Single / Double / Treble /
Bull / Bullseye), and log the results.

---

## Features

| Feature | Status |
|---|---|
| Live MJPEG camera feed with dartboard overlay | ✅ |
| Automatic dartboard detection (HoughCircles) | ✅ |
| Interactive / manual board calibration | ✅ |
| Dart detection via frame differencing | ✅ |
| Score calculation (1-20 · Single/Double/Treble · Bull · Bullseye) | ✅ |
| Session history with undo & clear | ✅ |
| Manual score entry / correction | ✅ |
| SQLite persistent logging | ✅ |
| CSV & JSON export | ✅ |
| Real-time WebSocket UI updates | ✅ |
| Dark-theme responsive web UI | ✅ |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+ · Flask · Flask-SocketIO · OpenCV · NumPy |
| Frontend | HTML5 · CSS3 · Vanilla JS · Socket.IO (CDN) |
| Database | SQLite (via Python `sqlite3`) |
| Video streaming | MJPEG over HTTP |

---

## Quick Start

### Prerequisites

* Python 3.10 or later
* A webcam (USB or built-in)
* The camera pointing at a dartboard, in good lighting

### Linux / macOS

```bash
# Clone (or unzip) the repository
cd Darts-V2

# Make the launch script executable and run it
chmod +x start.sh
./start.sh
```

### Windows

Double-click **`start.bat`**, or run it from a command prompt:

```bat
start.bat
```

The script:
1. Creates a Python virtual environment (`.venv/`) on first run.
2. Installs all dependencies from `requirements.txt`.
3. Starts the Flask server at **http://localhost:5000**.

### Manual startup

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in a browser.

---

## Usage Guide

### 1. Start the camera

Click **Start Camera**. The live feed will appear and the board-detection
algorithm will attempt to locate the dartboard automatically (green circle
overlay).

### 2. Calibrate (if auto-detection fails)

Click **Calibrate Board** → **Click on Video**, then:
1. Click the **centre** of the dartboard.
2. Click any point on the **outer double ring**.

Or enter pixel values manually in the calibration dialog.

### 3. Start Detection

Click **Start Detection**. The application now monitors for new objects
appearing on the board (i.e. thrown darts).

Whenever a new dart is detected, the score is:
* Calculated from the dart-tip position relative to the calibrated board.
* Displayed in the **Last Dart** card.
* Added to the **Total Score**.
* Appended to the **Session History**.

### 4. Controls

| Button | Action |
|---|---|
| **Start / Stop Camera** | Open or close the camera |
| **Start / Stop Detection** | Enable or disable auto-detection |
| **Toggle Overlay** | Show/hide the board geometry overlay |
| **Undo** | Remove the most recently logged dart |
| **Clear Scores** | Reset the current session |
| **Manual Entry** | Add a score by hand (e.g. after a missed detection) |
| **Calibrate Board** | Adjust board centre / radius |
| **⚙ Settings** | Select camera index |
| **⬇ JSON / CSV** | Export the session results |

### 5. Manual Entry

If a dart is not detected automatically, click **Manual Entry**, select the
number and zone, and click **Add**.

---

## Project Structure

```
Darts-V2/
├── backend/
│   ├── app.py          ← Flask + Socket.IO server, MJPEG stream, API
│   ├── detector.py     ← OpenCV dart & dartboard detection
│   ├── dartboard.py    ← Scoring geometry (segments, rings, score calc)
│   ├── database.py     ← SQLite persistence (sessions, dart_hits)
│   └── requirements.txt
├── frontend/
│   ├── index.html      ← Single-page UI
│   ├── css/style.css   ← Dark sports-app theme
│   └── js/app.js       ← Socket.IO client, controls, history rendering
├── requirements.txt    ← (same as backend/requirements.txt, for convenience)
├── start.sh            ← Linux/macOS launch script
├── start.bat           ← Windows launch script
└── README.md
```

---

## Configuration / Tuning

All runtime parameters can be adjusted in the **⚙ Settings** panel:

| Setting | Effect |
|---|---|
| Camera Index | Which camera to use (0 = default) |
| Detection Cooldown | Minimum seconds between two detections (prevents duplicates) |
| Diff Threshold | Pixel-difference sensitivity (lower = more sensitive) |

For best results:
* Use good, even lighting on the dartboard.
* Avoid backlighting or strong shadows.
* Mount the camera 1–2 m from the board, roughly centred.
* Capture a fresh baseline with **Reset Reference** after each throw.

---

## Database Schema

```sql
sessions (
    id          TEXT PRIMARY KEY,
    started_at  TEXT,
    ended_at    TEXT,
    total_score INTEGER
)

dart_hits (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT,
    timestamp   TEXT,
    number      INTEGER,   -- 0 for Bull/Bullseye
    zone        TEXT,      -- Single | Double | Treble | Bull | Bullseye | Miss
    multiplier  INTEGER,
    score       INTEGER,
    confidence  REAL,
    x_pos       REAL,
    y_pos       REAL,
    manual      INTEGER    -- 1 if entered manually
)
```

---

## License

MIT © 2026 Aleksandar Ilicic
