$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython)) { throw "Run the root setup.ps1 first." }
    $backend = & $projectPython -c 'import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv("POSTGRES_BACKEND", "docker"))'
    if ($backend -eq "native") {
        & $projectPython native_db.py start
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL startup failed." }
    } elseif ($backend -eq "docker") {
        & docker compose up -d --wait --wait-timeout 120 postgres
        if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop and check PostgreSQL logs." }
    } else { throw "POSTGRES_BACKEND must be docker or native." }
    & $projectPython manage.py init-db
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }
    & $projectPython app.py
    if ($LASTEXITCODE -ne 0) { throw "Seat store exited with an error." }
} finally { Pop-Location }

