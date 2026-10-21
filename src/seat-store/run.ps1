$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython)) { throw "Run the root setup.ps1 first." }
    $expectedVersion = (Get-Content (Join-Path $PSScriptRoot "..\..\.python-version") -Raw).Trim()
    $actualVersion = & $projectPython -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $expectedVersion) {
        throw "Run root setup.ps1 with Python $expectedVersion before starting seat-store."
    }
    # Send Python code on stdin so Windows PowerShell preserves its string quotes.
    $backend = 'import os; from dotenv import load_dotenv; load_dotenv(".env"); print(os.getenv("POSTGRES_BACKEND", "docker"))' | & $projectPython -
    if ($LASTEXITCODE -ne 0) { throw "Could not read POSTGRES_BACKEND from local configuration." }
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

