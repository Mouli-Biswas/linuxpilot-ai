@echo off
title LinuxPilot AI Launcher
echo =========================================
echo   Launching LinuxPilot AI Full Stack
echo =========================================

set SCRIPT_DIR=%~dp0

start "LinuxPilot Backend" cmd /k "cd /d %SCRIPT_DIR% && .venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
start "LinuxPilot Frontend" cmd /k "cd /d %SCRIPT_DIR%frontend && npm run dev"

echo Backend (http://127.0.0.1:8000) and Frontend (http://localhost:1420) started!
pause
