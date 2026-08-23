#!/usr/bin/env bash
# run_dev.sh — starts the backend (and Ollama, if not already running)
# for local development, outside Docker.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! curl -s -o /dev/null http://localhost:11434/api/tags; then
  echo "--> Ollama not detected on :11434, starting it..."
  ollama serve &
  sleep 2
fi

source .venv/bin/activate
export $(grep -v '^#' .env | xargs) 2>/dev/null || true

echo "--> Starting FastAPI backend on http://localhost:8000 (docs at /docs)"
uvicorn backend.main:app --reload --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
