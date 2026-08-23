#!/usr/bin/env bash
# ==============================================================================
# LinuxPilot AI — Startup Script
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

mkdir -p .pids logs

# --- 1. Verify Prerequisites ---
if [ ! -d ".venv" ] || [ ! -d "frontend/node_modules" ]; then
  echo -e "${YELLOW}⚠️  Prerequisites not found. Running installer first...${NC}"
  ./scripts/install.sh
fi

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

# --- 2. Check If Already Running ---
if [ -f ".pids/backend.pid" ]; then
  OLD_PID="$(cat .pids/backend.pid 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  LinuxPilot AI backend is already running (PID: $OLD_PID).${NC}"
  fi
fi

if [ -f ".pids/frontend.pid" ]; then
  OLD_FPID="$(cat .pids/frontend.pid 2>/dev/null || true)"
  if [ -n "$OLD_FPID" ] && kill -0 "$OLD_FPID" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  LinuxPilot AI frontend is already running (PID: $OLD_FPID).${NC}"
  fi
fi

# --- 3. Port Conflict Checks ---
check_port() {
  local port="$1"
  local name="$2"
  if command -v lsof >/dev/null 2>&1; then
    if lsof -i :"$port" >/dev/null 2>&1; then
      echo -e "${RED}❌ Error: Port $port is already in use by another application ($name).${NC}"
      lsof -i :"$port"
      exit 1
    fi
  elif command -v ss >/dev/null 2>&1; then
    if ss -tuln | grep -q ":$port "; then
      echo -e "${RED}❌ Error: Port $port is already occupied ($name).${NC}"
      exit 1
    fi
  fi
}

# Only check if PID is not currently our own active process
if [ ! -f ".pids/backend.pid" ] || ! kill -0 "$(cat .pids/backend.pid 2>/dev/null)" 2>/dev/null; then
  check_port 8000 "Backend"
fi

if [ ! -f ".pids/frontend.pid" ] || ! kill -0 "$(cat .pids/frontend.pid 2>/dev/null)" 2>/dev/null; then
  check_port 1420 "Frontend"
fi

# --- 4. Start FastAPI Backend ---
echo -e "--> Starting FastAPI backend on 127.0.0.1:8000..."
nohup "$VENV_PYTHON" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > .pids/backend.pid

# --- 5. Start Frontend Dev Server ---
echo -e "--> Starting React/Vite frontend..."
(
  cd frontend
  nohup npm run dev > ../logs/frontend.log 2>&1 &
  echo $! > ../.pids/frontend.pid
)

# --- 6. Health & Readiness Verification ---
echo -e "--> Waiting for services to initialize..."
sleep 2

BACKEND_OK=0
for i in {1..10}; do
  if command -v curl >/dev/null 2>&1; then
    if curl -s http://127.0.0.1:8000/api/health | grep -q '"status":"ok"'; then
      BACKEND_OK=1
      break
    fi
  else
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
      BACKEND_OK=1
      break
    fi
  fi
  sleep 0.5
done

if [ "$BACKEND_OK" -eq 1 ]; then
  echo -e "${GREEN}✓ Backend healthy.${NC}"
else
  echo -e "${RED}❌ Backend failed to start. Check logs/backend.log for details.${NC}"
fi

FPID="$(cat .pids/frontend.pid 2>/dev/null || true)"
if [ -n "$FPID" ] && kill -0 "$FPID" 2>/dev/null; then
  echo -e "${GREEN}✓ Frontend started.${NC}"
else
  echo -e "${RED}❌ Frontend failed to start. Check logs/frontend.log for details.${NC}"
fi

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}  🚀 LinuxPilot AI is Running!${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "  ${BOLD}Dashboard UI:${NC}    ${GREEN}http://localhost:1420${NC}"
echo -e "  ${BOLD}Backend API:${NC}     ${GREEN}http://127.0.0.1:8000${NC}"
echo -e "  ${BOLD}Swagger Docs:${NC}    ${GREEN}http://127.0.0.1:8000/docs${NC}"
echo -e "------------------------------------------------------"
echo -e "  ${BOLD}Log Files:${NC}"
echo -e "    Backend:  tail -f logs/backend.log"
echo -e "    Frontend: tail -f logs/frontend.log"
echo -e "------------------------------------------------------"
echo -e "  ${BOLD}Management Commands:${NC}"
echo -e "    Check Status: ${CYAN}./scripts/status.sh${NC}"
echo -e "    Stop Server:  ${CYAN}./scripts/stop.sh${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"
