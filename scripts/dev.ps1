# Start the JobPilot AI service and Go gateway for local development.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# Then open http://localhost:8090  (Ctrl+C in each window to stop)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Start-Process powershell -WorkingDirectory $root -ArgumentList "-NoExit", "-Command",
    "& '$python' -m uvicorn ai_service.app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -WorkingDirectory (Join-Path $root "backend") -ArgumentList "-NoExit", "-Command",
    "go run ./cmd/server"

Write-Host "AI service: http://localhost:8000/docs"
Write-Host "JobPilot UI: http://localhost:8090"
