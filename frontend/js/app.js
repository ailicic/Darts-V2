/**
 * Darts – Frontend Application
 *
 * Communicates with the Python backend via Socket.IO (real-time events).
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

const elTotalScore        = document.getElementById("total-score");
const elDartCount         = document.getElementById("dart-count");
const elLastDartSummary   = document.getElementById("last-dart-summary");
const elLastDartScore     = document.getElementById("last-dart-score");
const elHistoryList       = document.getElementById("history-list");

const btnUndo             = document.getElementById("btn-undo");
const btnClear            = document.getElementById("btn-clear");
const btnManual           = document.getElementById("btn-manual");
const btnExportJson       = document.getElementById("btn-export-json");
const btnExportCsv        = document.getElementById("btn-export-csv");

// Modal triggers / buttons
const btnManualConfirm    = document.getElementById("btn-manual-confirm");

const modalManual         = document.getElementById("modal-manual");

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------

let state = {
  totalScore:   0,
  dartHistory:  [],   // [{id, timestamp, number, zone, multiplier, score, manual}]
};

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
  state.totalScore  = data.total_score;
  state.dartHistory = data.dart_history || [];

  if (state.dartHistory.length > 0) {
    updateLastDart(state.dartHistory[state.dartHistory.length - 1]);
  }
  updateUI();
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
  updateUI();
  showToast("Scores cleared.", "info");
});

socket.on("error", data => {
  showToast(`Error: ${data.message}`, "error", 5000);
});

// ---------------------------------------------------------------------------
// Control bar button handlers
// ---------------------------------------------------------------------------

btnUndo.addEventListener("click", () => {
  socket.emit("undo_last");
});

btnClear.addEventListener("click", () => {
  if (confirm("Clear all scores for this session?")) {
    socket.emit("clear_scores");
  }
});

btnManual.addEventListener("click", () => openModal(modalManual));

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
// CSS flash animation
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
