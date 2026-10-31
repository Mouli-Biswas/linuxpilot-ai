# start_backend.ps1 - Starts the FastAPI Backend
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Starting LinuxPilot AI Backend...      " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Virtual environment not found at $VenvPython" -ForegroundColor Red
    exit 1
}

Write-Host "Backend running on http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "Swagger Docs available at http://127.0.0.1:8000/docs" -ForegroundColor Yellow

& $VenvPython -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
