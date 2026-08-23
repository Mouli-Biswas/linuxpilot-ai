#!/usr/bin/env bash
# ==============================================================================
# LinuxPilot AI — Automated Linux Installation Script
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

echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}  LinuxPilot AI — System Setup & Installation${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"

# --- 1. OS Check ---
OS_NAME="$(uname -s)"
if [ "$OS_NAME" != "Linux" ]; then
  echo -e "${YELLOW}⚠️  Notice: Operating system is $OS_NAME (Linux is the primary target for systemd/journalctl integration).${NC}"
else
  echo -e "${GREEN}✓ Linux OS detected ($OS_NAME).${NC}"
fi

# --- 2. Python 3 Check ---
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${RED}❌ Error: python3 is not installed or not found on PATH.${NC}"
  echo -e "Please install Python 3.10+ using your package manager:"
  echo -e "  ${BOLD}Ubuntu/Debian:${NC} sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  echo -e "  ${BOLD}Fedora:${NC}        sudo dnf install -y python3 python3-pip"
  echo -e "  ${BOLD}Arch Linux:${NC}    sudo pacman -S python python-pip"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')"
if [ "$PY_OK" != "1" ]; then
  echo -e "${RED}❌ Error: Python 3.10 or higher is required (found Python $PY_VER).${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Python $PY_VER detected.${NC}"

# --- 3. Check python3-venv ---
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo -e "${RED}❌ Error: python3-venv is missing.${NC}"
  echo -e "Install it using:"
  echo -e "  ${BOLD}Ubuntu/Debian:${NC} sudo apt install -y python3-venv"
  exit 1
fi
echo -e "${GREEN}✓ python3-venv available.${NC}"

# --- 4. Check Node.js and npm ---
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo -e "${RED}❌ Error: Node.js and/or npm not found.${NC}"
  echo -e "Please install Node.js 18+ and npm:"
  echo -e "  ${BOLD}Ubuntu/Debian:${NC} sudo apt update && sudo apt install -y nodejs npm"
  echo -e "  ${BOLD}Fedora:${NC}        sudo dnf install -y nodejs npm"
  echo -e "  ${BOLD}NodeSource:${NC}    https://github.com/nodesource/distributions"
  exit 1
fi
NODE_VER="$(node -v)"
echo -e "${GREEN}✓ Node.js ($NODE_VER) and npm ($(npm -v)) detected.${NC}"

# --- 5. Python Virtual Environment Setup ---
if [ ! -d ".venv" ]; then
  echo -e "--> Creating Python virtual environment in .venv..."
  python3 -m venv .venv
else
  echo -e "--> Python virtual environment (.venv) already exists."
fi

echo -e "--> Installing/updating Python backend dependencies..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r backend/requirements.txt --quiet
echo -e "${GREEN}✓ Python backend dependencies installed successfully.${NC}"

# --- 6. Configuration (.env) Setup ---
if [ ! -f .env ]; then
  echo -e "--> Creating .env configuration from .env.example..."
  cp .env.example .env
fi
echo -e "${GREEN}✓ Environment configuration ready (.env).${NC}"

# --- 7. Runtime Directories ---
mkdir -p .pids logs
echo -e "${GREEN}✓ Runtime directories created (.pids, logs).${NC}"

# --- 8. Frontend Dependencies Setup ---
echo -e "--> Installing frontend dependencies with npm..."
(cd frontend && npm install --silent)
echo -e "${GREEN}✓ Frontend dependencies installed successfully.${NC}"

# --- 9. Database Initialization ---
echo -e "--> Initializing SQLite database schema..."
.venv/bin/python -c "from backend.database.db import init_db; init_db()"
echo -e "${GREEN}✓ SQLite database initialized (linuxpilot.db).${NC}"

# --- 10. Make Scripts Executable ---
chmod +x scripts/*.sh 2>/dev/null || true

echo -e "\n${BOLD}${GREEN}======================================================${NC}"
echo -e "${BOLD}${GREEN}  ✓ LinuxPilot AI Installation Complete!${NC}"
echo -e "${BOLD}${GREEN}======================================================${NC}"
echo -e "To start LinuxPilot AI, simply run:"
echo -e "  ${BOLD}${CYAN}./scripts/start.sh${NC}\n"
