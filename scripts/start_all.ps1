# start_all.ps1 - Launches both Backend and Frontend in separate terminal windows
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Launching LinuxPilot AI Full Stack     " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan

# Start Backend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start_backend.ps1")

# Start Frontend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start_frontend.ps1")

Write-Host "Both Backend (http://127.0.0.1:8000) and Frontend (http://localhost:1420) have been started!" -ForegroundColor Green
