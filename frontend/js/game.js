/**
 * game.js — Game overlay logic for index.html
 *
 * Activated when the URL contains ?gameId=<id>.
 * Links the camera session to the game so detected darts are routed to it,
 * and keeps the game scoreboard / turn indicator in sync.
 */

"use strict";

(function () {
  // ── Read gameId from URL ─────────────────────────────────────────────────
  const params  = new URLSearchParams(window.location.search);
  const gameId  = params.get("gameId");

  if (!gameId) return;  // no game — leave the page in standalone detection mode

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const gameBanner          = document.getElementById("game-banner");
  const currentPlayerName   = document.getElementById("current-player-name");
  const currentPlayerScore  = document.getElementById("current-player-score");
  const gameCodeBadge       = document.getElementById("game-code-badge");
  const gameScoreboardBox   = document.getElementById("game-scoreboard-box");
  const scoreboardBody      = document.getElementById("scoreboard-body");
  const gameModeLbl         = document.getElementById("game-mode-label");
  const btnEndTurn          = document.getElementById("btn-end-turn");
  const btnGameUndo         = document.getElementById("btn-game-undo");
  const modalWinner         = document.getElementById("modal-winner");
  const winnerTitle         = document.getElementById("winner-title");
  const winnerBody          = document.getElementById("winner-body");

  let gameState = null;
  let linkedToCamera = false;

  // ── Fetch initial game state ─────────────────────────────────────────────
  fetch(`/api/games/${encodeURIComponent(gameId)}`)
    .then(r => {
      if (!r.ok) throw new Error("Game not found");
      return r.json();
    })
    .then(game => {
      applyGameState(game);
      showGameUI();
      // Link camera once Socket.IO is connected
      if (window.socket && window.socket.connected) {
        linkCamera();
      }
    })
    .catch(err => {
      console.warn("[game.js] Could not load game:", err.message);
    });

  // ── Socket.IO integration ─────────────────────────────────────────────────
  // Wait for socket to be initialised by app.js, then hook in
  function hookSocket() {
    const s = window.socket;
    if (!s) { setTimeout(hookSocket, 100); return; }

    s.on("connect", () => {
      if (!linkedToCamera) linkCamera();
    });

    s.on("game_updated", data => {
      if (data.game && data.game.id === gameId) {
        applyGameState(data.game);
        if (data.throw_result && data.throw_result.message) {
          showGameToast(data.throw_result.message,
            data.throw_result.bust ? "warn" : "success");
        }
      }
    });

    s.on("game_won", data => {
      if (data.game_id === gameId) {
        showWinnerModal(data.winner_name);
      }
    });

    s.on("game_linked", data => {
      linkedToCamera = true;
      console.log("[game.js] Camera linked to game", data.game_id);
    });
  }
  hookSocket();

  // ── Link camera to this game ─────────────────────────────────────────────
  function linkCamera() {
    const s = window.socket;
    if (!s || !s.connected) return;
    s.emit("link_game", { game_id: gameId });
  }

  // ── End Turn button ──────────────────────────────────────────────────────
  btnEndTurn && btnEndTurn.addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/games/${encodeURIComponent(gameId)}/end-turn`, { method: "POST" });
      const data = await res.json();
      if (data.game) applyGameState(data.game);
    } catch (e) {
      console.error("[game.js] end-turn error:", e);
    }
  });

  // ── Undo button ──────────────────────────────────────────────────────────
  btnGameUndo && btnGameUndo.addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/games/${encodeURIComponent(gameId)}/undo`, { method: "POST" });
      const data = await res.json();
      if (data.game) applyGameState(data.game);
      else showGameToast("Nothing to undo.", "warn");
    } catch (e) {
      console.error("[game.js] undo error:", e);
    }
  });

  // ── State rendering ──────────────────────────────────────────────────────
  function applyGameState(game) {
    gameState = game;

    const players = game.players || [];
    const idx     = game.current_player_index || 0;
    const current = players[idx];
    const rows    = game.scoreboard || players;

    // Current player indicator
    if (current) {
      currentPlayerName.textContent  = current.name;
      const scoreRow = rows.find(r => r.id === current.id);
      currentPlayerScore.textContent = scoreRow ? `→ ${scoreRow.display}` : "";
    }

    // Game code badge
    if (game.short_code) {
      gameCodeBadge.textContent = `🔑 ${game.short_code}`;
    }

    // Mode label
    gameModeLbl.textContent = game.mode || "";

    // Scoreboard table
    scoreboardBody.innerHTML = "";
    rows.forEach((row, i) => {
      const tr = document.createElement("tr");
      const isActive = i === idx && game.status === "active";
      if (isActive) tr.classList.add("scoreboard-active-row");

      tr.innerHTML = `
        <td>${isActive ? "▶ " : ""}${escapeHtml(row.name)}</td>
        <td class="score-cell">${escapeHtml(String(row.display || ""))}</td>
        <td class="extra-cell" style="font-size:0.78rem;color:var(--text-muted,#9e9e9e)">${escapeHtml(String(row.extra || ""))}</td>
      `;
      scoreboardBody.appendChild(tr);
    });

    // If game finished, show winner modal
    if (game.status === "finished" && game.winner_id && !modalWinner.classList.contains("modal-shown")) {
      const winner = players.find(p => p.id === game.winner_id);
      if (winner) showWinnerModal(winner.name);
    }
  }

  function showGameUI() {
    gameBanner && gameBanner.classList.remove("hidden");
    gameScoreboardBox && gameScoreboardBox.classList.remove("hidden");
  }

  function showWinnerModal(name) {
    if (!modalWinner) return;
    winnerTitle.textContent = "🏆 Winner!";
    winnerBody.textContent  = `${name} wins! 🎉`;
    modalWinner.classList.remove("hidden");
    modalWinner.classList.add("modal-shown");
  }

  function showGameToast(msg, type) {
    // Re-use the showToast function from app.js if available
    if (typeof window.showToast === "function") {
      window.showToast(msg, type, 3500);
    }
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

}());
