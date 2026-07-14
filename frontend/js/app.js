/**
 * Darts-V2 – Frontend Application
 *
 * Communicates with the Python backend via Socket.IO (real-time events)
 * and a standard HTTP MJPEG stream for the video feed.
 */

"use strict";

// ---------------------------------------------------------------------------
// Socket.IO connection
// ---------------------------------------------------------------------------

const socket = io();
// Expose globally so game.js can access it
window.socket = socket;

// ---------------------------------------------------------------------------
// Offline banner
// ---------------------------------------------------------------------------

const offlineBanner = document.getElementById("offline-banner");

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const elConnectionStatus  = document.getElementById("connection-status");
const elVideoFeed         = document.getElementById("video-feed");
const elNoCameraOverlay   = document.getElementById("no-camera-overlay");
const elBoardStatus       = document.getElementById("board-status");
const elDetectStatus      = document.getElementById("detect-status");
const elFpsDisplay        = document.getElementById("fps-display");
const elOverlayStatus     = document.getElementById("overlay-status");

const elTotalScore        = document.getElementById("total-score");
const elDartCount         = document.getElementById("dart-count");
const elLastDartSummary   = document.getElementById("last-dart-summary");
const elLastDartScore     = document.getElementById("last-dart-score");
const elConfidenceFill    = document.getElementById("confidence-fill");
const elConfidencePct     = document.getElementById("confidence-pct");
const elHistoryList       = document.getElementById("history-list");

const btnCamera           = document.getElementById("btn-camera");
const btnDetect           = document.getElementById("btn-detect");
const btnOverlay          = document.getElementById("btn-overlay");
const btnUndo             = document.getElementById("btn-undo");
const btnClear            = document.getElementById("btn-clear");
const btnManual           = document.getElementById("btn-manual");
const btnCalibrate        = document.getElementById("btn-calibrate");
const btnSettings         = document.getElementById("btn-settings");
const btnExportJson       = document.getElementById("btn-export-json");
const btnExportCsv        = document.getElementById("btn-export-csv");

// Modal triggers / buttons
const btnManualConfirm    = document.getElementById("btn-manual-confirm");
const btnCalibApply       = document.getElementById("btn-calib-apply");
const btnCalibInteractive = document.getElementById("btn-calib-interactive");
const btnSettingsApply    = document.getElementById("btn-settings-apply");

const modalManual         = document.getElementById("modal-manual");
const modalCalibrate      = document.getElementById("modal-calibrate");
const modalSettings       = document.getElementById("modal-settings");

const calibCanvas         = document.getElementById("calib-canvas");

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------

let state = {
  cameraRunning:    false,
  detectionActive:  false,
  overlayEnabled:   true,
  boardCalibrated:  false,
  totalScore:       0,
  dartHistory:      [],     // [{id, timestamp, number, zone, multiplier, score, confidence, manual}]
};

let calibClickCount = 0;
let calibPoints     = [];   // [{x, y}]  – for interactive calibration

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function showToast(msg, type = "info", duration = 3000) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration);
}
// Expose globally so game.js can call showToast
window.showToast = showToast;

function openModal(modal) {
  modal.classList.remove("hidden");
}

function closeModal(modal) {
  modal.classList.add("hidden");
}

// Generic close buttons inside modals
document.querySelectorAll(".modal-close").forEach(btn => {
  btn.addEventListener("click", () => {
    const modalId = btn.dataset.modal;
    const modal = document.getElementById(modalId);
    if (modal) closeModal(modal);
  });
});

// Close modal when clicking backdrop
document.querySelectorAll(".modal").forEach(modal => {
  modal.addEventListener("click", e => {
    if (e.target === modal) closeModal(modal);
  });
});

function zoneClass(zone) {
  const map = {
    Double: "zone-double",
    Treble: "zone-treble",
    Bull:   "zone-bull",
    Bullseye: "zone-bullseye",
  };
  return map[zone] || "";
}

function formatDartLabel(dart) {
  if (dart.zone === "Bullseye") return "Bullseye";
  if (dart.zone === "Bull")     return "Bull (25)";
  if (dart.zone === "Miss")     return "Miss";
  const prefix = dart.multiplier > 1 ? dart.zone + " " : "";
  return `${prefix}${dart.number}`;
}

function updateUI() {
  elTotalScore.textContent = state.totalScore;
  elDartCount.textContent  = `${state.dartHistory.length} dart${state.dartHistory.length !== 1 ? "s" : ""}`;

  btnUndo.disabled  = state.dartHistory.length === 0;
  btnClear.disabled = state.dartHistory.length === 0;

  // History list
  if (state.dartHistory.length === 0) {
    elHistoryList.innerHTML = '<li class="history-empty">No darts logged yet.</li>';
  } else {
    elHistoryList.innerHTML = "";
    // Show newest first
    [...state.dartHistory].reverse().forEach(dart => {
      const li = document.createElement("li");
      li.className = "history-item";
      li.innerHTML = `
        <span class="hi-num">${dart.number || "●"}</span>
        <span class="hi-zone ${zoneClass(dart.zone)}">${dart.zone}</span>
        <span class="hi-score">${dart.score}</span>
        ${dart.manual ? '<span class="hi-manual">manual</span>' : ""}
      `;
      elHistoryList.appendChild(li);
    });
  }
}

function updateLastDart(dart) {
  elLastDartSummary.textContent = formatDartLabel(dart);
  elLastDartScore.textContent   = `${dart.score} pts`;
  const pct = Math.round(dart.confidence * 100);
  elConfidenceFill.style.width  = `${pct}%`;
  elConfidencePct.textContent   = `${pct}%`;
}

function setConnected(connected) {
  if (connected) {
    elConnectionStatus.textContent = "Online";
    elConnectionStatus.className   = "badge badge-online";
  } else {
    elConnectionStatus.textContent = "Offline";
    elConnectionStatus.className   = "badge badge-offline";
  }
}

function setCameraRunning(running) {
  state.cameraRunning = running;
  btnCamera.textContent = running ? "Stop Camera" : "Start Camera";
  btnCamera.className   = running ? "btn btn-danger" : "btn btn-primary";
  btnDetect.disabled    = !running;
  elNoCameraOverlay.style.display = running ? "none" : "flex";
}

function setDetectionActive(active) {
  state.detectionActive = active;
  btnDetect.textContent  = active ? "Stop Detection" : "Start Detection";
  btnDetect.className    = active ? "btn btn-warning" : "btn btn-success";
  elDetectStatus.textContent = active ? "Detection: on" : "Detection: off";
  elDetectStatus.className   = active ? "status-chip chip-active" : "status-chip chip-inactive";
}

function setBoardCalibrated(calibrated) {
  state.boardCalibrated = calibrated;
  if (calibrated) {
    elBoardStatus.textContent = "Board: detected ✓";
    elBoardStatus.className   = "status-chip chip-active";
  } else {
    elBoardStatus.textContent = "Board: searching…";
    elBoardStatus.className   = "status-chip chip-warning";
  }
}

// ---------------------------------------------------------------------------
// Socket.IO event handlers
// ---------------------------------------------------------------------------

socket.on("connect", () => {
  setConnected(true);
  offlineBanner && offlineBanner.classList.add("hidden");
});

socket.on("disconnect", () => {
  setConnected(false);
  offlineBanner && offlineBanner.classList.remove("hidden");
});

socket.on("status", data => {
  setCameraRunning(data.camera_running);
  setDetectionActive(data.detection_active);
  setBoardCalibrated(data.calibrated);

  elOverlayStatus.textContent = data.overlay_enabled ? "Overlay: on" : "Overlay: off";
  elOverlayStatus.className   = data.overlay_enabled ? "status-chip chip-active" : "status-chip chip-inactive";

  state.overlayEnabled = data.overlay_enabled;
  state.totalScore     = data.total_score;
  state.dartHistory    = data.dart_history || [];

  if (state.dartHistory.length > 0) {
    updateLastDart(state.dartHistory[state.dartHistory.length - 1]);
  }
  updateUI();
});

socket.on("camera_started", data => {
  if (data.success) setCameraRunning(true);
});

socket.on("camera_stopped", data => {
  setCameraRunning(false);
  setDetectionActive(false);
  if (data && data.error) showToast(data.error, "error");
});

socket.on("detection_started", () => setDetectionActive(true));
socket.on("detection_stopped", () => setDetectionActive(false));

socket.on("board_detected", data => {
  setBoardCalibrated(true);
  showToast(`Dartboard detected (r=${Math.round(data.radius)}px)`, "success");
});

socket.on("dart_detected", data => {
  const dart = data.dart;
  state.dartHistory.push(dart);
  state.totalScore = data.total_score;
  updateLastDart(dart);
  updateUI();

  // Flash the last-dart box
  document.getElementById("last-dart-box").classList.add("flash");
  setTimeout(() => document.getElementById("last-dart-box").classList.remove("flash"), 600);

  const label = formatDartLabel(dart);
  showToast(`🎯 ${label} = ${dart.score} pts`, "success", 4000);
});

socket.on("dart_undone", data => {
  state.dartHistory = state.dartHistory.filter(d => d.id !== data.removed.id);
  state.totalScore  = data.total_score;
  updateUI();
  showToast(`Removed: ${formatDartLabel(data.removed)}`, "warn");
});

socket.on("scores_cleared", () => {
  state.dartHistory = [];
  state.totalScore  = 0;
  elLastDartSummary.textContent = "–";
  elLastDartScore.textContent   = "–";
  elConfidenceFill.style.width  = "0%";
  elConfidencePct.textContent   = "0%";
  updateUI();
  showToast("Scores cleared.", "info");
});

socket.on("overlay_toggled", data => {
  state.overlayEnabled = data.enabled;
  elOverlayStatus.textContent = data.enabled ? "Overlay: on" : "Overlay: off";
  elOverlayStatus.className   = data.enabled ? "status-chip chip-active" : "status-chip chip-inactive";
});

socket.on("calibration_set", () => {
  setBoardCalibrated(true);
  showToast("Calibration applied.", "success");
});

socket.on("reference_reset", () => {
  showToast("Baseline frame captured.", "info");
});

socket.on("error", data => {
  showToast(`Error: ${data.message}`, "error", 5000);
});

// FPS polling from video feed (we read it from status periodically)
setInterval(() => {
  fetch("/api/status")
    .then(r => r.json())
    .then(s => {
      elFpsDisplay.textContent = `FPS: ${s.fps || "–"}`;
    })
    .catch(() => {});
}, 2000);

// ---------------------------------------------------------------------------
// Control bar button handlers
// ---------------------------------------------------------------------------

btnCamera.addEventListener("click", () => {
  if (!state.cameraRunning) {
    const camIdx = parseInt(document.getElementById("settings-camera").value, 10) || 0;
    socket.emit("start_camera", { camera_index: camIdx });
  } else {
    socket.emit("stop_camera");
  }
});

btnDetect.addEventListener("click", () => {
  if (!state.detectionActive) {
    socket.emit("start_detection");
  } else {
    socket.emit("stop_detection");
  }
});

btnOverlay.addEventListener("click", () => {
  socket.emit("toggle_overlay");
});

btnUndo.addEventListener("click", () => {
  socket.emit("undo_last");
});

btnClear.addEventListener("click", () => {
  if (confirm("Clear all scores for this session?")) {
    socket.emit("clear_scores");
  }
});

btnManual.addEventListener("click", () => openModal(modalManual));

btnCalibrate.addEventListener("click", () => openModal(modalCalibrate));

btnSettings.addEventListener("click", () => {
  loadCameraList();
  openModal(modalSettings);
});

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

btnExportJson.addEventListener("click", () => {
  window.location.href = "/api/export/json";
});

btnExportCsv.addEventListener("click", () => {
  window.location.href = "/api/export/csv";
});

// ---------------------------------------------------------------------------
// Manual entry modal
// ---------------------------------------------------------------------------

btnManualConfirm.addEventListener("click", () => {
  const number = parseInt(document.getElementById("manual-number").value, 10);
  const zone   = document.getElementById("manual-zone").value;

  // Sync zone select for bull entries
  let finalNumber = number;
  let finalZone   = zone;
  if (number === 0 && zone === "Single") {
    finalZone = "Bull";
  }

  socket.emit("manual_correction", { number: finalNumber, zone: finalZone });
  closeModal(modalManual);
});

// ---------------------------------------------------------------------------
// Calibration modal
// ---------------------------------------------------------------------------

btnCalibApply.addEventListener("click", () => {
  const cx = parseFloat(document.getElementById("calib-cx").value);
  const cy = parseFloat(document.getElementById("calib-cy").value);
  const r  = parseFloat(document.getElementById("calib-r").value);

  if (isNaN(cx) || isNaN(cy) || isNaN(r) || r <= 0) {
    showToast("Please fill in all calibration fields correctly.", "error");
    return;
  }
  socket.emit("set_calibration", { center_x: cx, center_y: cy, radius: r });
  closeModal(modalCalibrate);
});

btnCalibInteractive.addEventListener("click", () => {
  closeModal(modalCalibrate);
  startInteractiveCalibration();
});

function startInteractiveCalibration() {
  calibClickCount = 0;
  calibPoints     = [];

  // Size canvas to match displayed image
  const rect = elVideoFeed.getBoundingClientRect();
  calibCanvas.width  = rect.width;
  calibCanvas.height = rect.height;
  calibCanvas.classList.remove("hidden");

  const ctx = calibCanvas.getContext("2d");
  ctx.clearRect(0, 0, calibCanvas.width, calibCanvas.height);

  // Instruction overlay
  drawCalibInstruction(ctx, "Click 1/2: Board CENTRE");

  calibCanvas.addEventListener("click", onCalibClick);
  showToast("Interactive calibration: click the board centre.", "info", 5000);
}

function drawCalibInstruction(ctx, msg) {
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, 0, calibCanvas.width, 40);
  ctx.fillStyle = "#00d4ff";
  ctx.font      = "bold 16px Segoe UI, sans-serif";
  ctx.fillText(msg, 12, 26);
}

function onCalibClick(e) {
  const rect = calibCanvas.getBoundingClientRect();
  // Map click coordinates from the displayed size to natural frame size
  const scaleX = elVideoFeed.naturalWidth  / rect.width  || 1;
  const scaleY = elVideoFeed.naturalHeight / rect.height || 1;

  const px = (e.clientX - rect.left) * scaleX;
  const py = (e.clientY - rect.top)  * scaleY;

  const ctx = calibCanvas.getContext("2d");

  calibClickCount++;
  calibPoints.push({ x: px, y: py });

  // Draw crosshair
  const dispX = e.clientX - rect.left;
  const dispY = e.clientY - rect.top;
  ctx.strokeStyle = calibClickCount === 1 ? "#00d4ff" : "#ff6d00";
  ctx.lineWidth   = 2;
  ctx.beginPath();
  ctx.moveTo(dispX - 10, dispY); ctx.lineTo(dispX + 10, dispY);
  ctx.moveTo(dispX, dispY - 10); ctx.lineTo(dispX, dispY + 10);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(dispX, dispY, 6, 0, Math.PI * 2);
  ctx.stroke();

  if (calibClickCount === 1) {
    drawCalibInstruction(ctx, "Click 2/2: any point on the DOUBLE ring");
    showToast("Now click any point on the outer double ring.", "info", 5000);
  } else if (calibClickCount === 2) {
    calibCanvas.removeEventListener("click", onCalibClick);
    calibCanvas.classList.add("hidden");

    const cx = calibPoints[0].x;
    const cy = calibPoints[0].y;
    const r  = Math.sqrt(
      Math.pow(calibPoints[1].x - cx, 2) + Math.pow(calibPoints[1].y - cy, 2),
    );

    socket.emit("set_calibration", { center_x: cx, center_y: cy, radius: r });
    showToast(`Calibrated: centre (${Math.round(cx)},${Math.round(cy)}), r=${Math.round(r)}px`, "success");
  }
}

// ---------------------------------------------------------------------------
// Settings modal
// ---------------------------------------------------------------------------

function loadCameraList() {
  fetch("/api/cameras")
    .then(r => r.json())
    .then(cameras => {
      const sel = document.getElementById("settings-camera");
      sel.innerHTML = "";
      cameras.forEach(cam => {
        const opt = document.createElement("option");
        opt.value       = cam.index;
        opt.textContent = cam.name;
        sel.appendChild(opt);
      });
      if (cameras.length === 0) {
        sel.innerHTML = '<option value="0">No cameras found</option>';
      }
    })
    .catch(() => {
      // Silently ignore if backend not yet available
    });
}

btnSettingsApply.addEventListener("click", () => {
  // Settings are read at start_camera / start_detection time
  // (cooldown / diff-threshold require backend support - noted for future extension)
  closeModal(modalSettings);
  showToast("Settings saved. Restart camera to apply camera index change.", "info");
});

// ---------------------------------------------------------------------------
// CSS flash animation (inject dynamically so it's not in the static sheet)
// ---------------------------------------------------------------------------
(function injectFlashStyle() {
  const style = document.createElement("style");
  style.textContent = `
    @keyframes dartFlash {
      0%   { box-shadow: 0 0 0   0   rgba(0,230,118,0.0); }
      30%  { box-shadow: 0 0 18px 6px rgba(0,230,118,0.8); }
      100% { box-shadow: 0 0 0   0   rgba(0,230,118,0.0); }
    }
    .flash { animation: dartFlash 0.6s ease; }
  `;
  document.head.appendChild(style);
}());
