# start_frontend.ps1 - Starts the Vite Frontend
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $ProjectRoot "frontend"
Set-Location $FrontendDir

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Starting LinuxPilot AI Frontend...     " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Frontend running on http://localhost:1420" -ForegroundColor Yellow

npm run dev
