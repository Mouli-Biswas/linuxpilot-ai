#!/usr/bin/env bash
# ==============================================================================
# LinuxPilot AI — Stop Script
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
NC="\033[0m"

echo -e "${BOLD}${CYAN}--> Stopping LinuxPilot AI services...${NC}"

stop_pid() {
  local pid_file="$1"
  local name="$2"

  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo -e "--> Stopping $name (PID: $pid)..."
      kill -15 "$pid" 2>/dev/null || true
      for i in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
          break
        fi
        sleep 0.2
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo -e "${YELLOW}Force killing $name (PID: $pid)...${NC}"
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo -e "${GREEN}✓ $name stopped.${NC}"
    else
      echo -e "--> $name was not running."
    fi
    rm -f "$pid_file"
  else
    echo -e "--> No active PID file found for $name."
  fi
}

stop_pid ".pids/backend.pid" "Backend (FastAPI)"
stop_pid ".pids/frontend.pid" "Frontend (Vite/Node)"

echo -e "\n${BOLD}${GREEN}✓ All LinuxPilot AI services stopped successfully.${NC}\n"
