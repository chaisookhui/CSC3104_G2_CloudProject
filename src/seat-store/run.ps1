$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) { throw "Run setup.ps1 first." }
    & docker compose up -d --wait --wait-timeout 120 postgres
    if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop and check PostgreSQL logs." }
    & .\.venv\Scripts\python.exe manage.py init-db
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }
    & .\.venv\Scripts\python.exe app.py
    if ($LASTEXITCODE -ne 0) { throw "Seat store exited with an error." }
} finally { Pop-Location }

