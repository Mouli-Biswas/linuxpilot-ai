#!/usr/bin/env bash
# ==============================================================================
# LinuxPilot AI — Status Script
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

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}  LinuxPilot AI — System Status${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"

# 1. Environment status
if [ -d ".venv" ]; then
  ENV_STATUS="${GREEN}READY (.venv)${NC}"
else
  ENV_STATUS="${RED}MISSING (Run ./scripts/install.sh)${NC}"
fi

# 2. Database status
if [ -f "linuxpilot.db" ]; then
  DB_STATUS="${GREEN}READY (./linuxpilot.db)${NC}"
else
  DB_STATUS="${YELLOW}NOT INITIALIZED${NC}"
fi

# 3. Backend status
BACKEND_PID=""
BACKEND_STATUS="${RED}STOPPED${NC}"
if [ -f ".pids/backend.pid" ]; then
  BACKEND_PID="$(cat .pids/backend.pid 2>/dev/null || true)"
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    HEALTH_STR=""
    if command -v curl >/dev/null 2>&1; then
      if curl -s http://127.0.0.1:8000/api/health | grep -q '"status":"ok"'; then
        HEALTH_STR=", Health: OK"
      fi
    fi
    BACKEND_STATUS="${GREEN}RUNNING (PID: $BACKEND_PID, Port: 8000$HEALTH_STR)${NC}"
  fi
fi

# 4. Frontend status
FRONTEND_PID=""
FRONTEND_STATUS="${RED}STOPPED${NC}"
if [ -f ".pids/frontend.pid" ]; then
  FRONTEND_PID="$(cat .pids/frontend.pid 2>/dev/null || true)"
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    FRONTEND_STATUS="${GREEN}RUNNING (PID: $FRONTEND_PID, Port: 1420)${NC}"
  fi
fi

echo -e "  ${BOLD}Environment:${NC}  $ENV_STATUS"
echo -e "  ${BOLD}Database:${NC}     $DB_STATUS"
echo -e "  ${BOLD}Backend:${NC}      $BACKEND_STATUS"
echo -e "  ${BOLD}Frontend:${NC}     $FRONTEND_STATUS"
echo -e "------------------------------------------------------"
echo -e "  ${BOLD}Dashboard URL:${NC} ${CYAN}http://localhost:1420${NC}"
echo -e "  ${BOLD}Backend API:${NC}   ${CYAN}http://127.0.0.1:8000${NC}"
echo -e "  ${BOLD}Swagger Docs:${NC}  ${CYAN}http://127.0.0.1:8000/docs${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"
