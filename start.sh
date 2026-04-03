#!/usr/bin/env bash
# start.sh – Launch the Darts-V2 server
# Usage:  ./start.sh [port]

set -e

PORT=${1:-5000}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "  Darts-V2 – Real-Time Dart Detection"
echo "=================================================="

# ---- Check Python -----------------------------------------------------------
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 is not installed or not on PATH."
  exit 1
fi

# ---- Virtual environment / dependencies -------------------------------------
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

echo "Installing / verifying dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ---- Start server -----------------------------------------------------------
echo ""
echo "Starting server on http://localhost:${PORT}"
echo "Press Ctrl+C to stop."
echo ""

cd "$SCRIPT_DIR/backend"
FLASK_ENV=production python app.py
