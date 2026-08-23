#!/usr/bin/env bash
# setup.sh — bootstraps a local LinuxPilot AI dev environment.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> LinuxPilot AI setup"

# --- 1. Python backend ---
echo "--> Setting up backend virtualenv"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# --- 2. Env file ---
if [ ! -f .env ]; then
  echo "--> Creating .env from .env.example"
  cp .env.example .env
else
  echo "--> .env already exists, leaving it alone"
fi

# --- 3. Ollama model pull (assumes Ollama is installed/running locally) ---
if command -v ollama >/dev/null 2>&1; then
  echo "--> Pulling qwen2.5:7b-instruct via Ollama (this can take a while)"
  ollama pull qwen2.5:7b-instruct
else
  echo "!!  Ollama not found on PATH. Install from https://ollama.com and run:"
  echo "    ollama pull qwen2.5:7b-instruct"
fi

# --- 4. Frontend deps ---
if command -v npm >/dev/null 2>&1; then
  echo "--> Installing frontend dependencies"
  (cd frontend && npm install)
else
  echo "!!  npm not found on PATH. Install Node.js to build the frontend."
fi

echo "==> Setup complete."
echo "    Backend:  source .venv/bin/activate && uvicorn backend.main:app --reload"
echo "    Frontend: cd frontend && npm run tauri dev"
