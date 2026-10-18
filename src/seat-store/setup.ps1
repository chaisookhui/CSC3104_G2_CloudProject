param(
    [string]$Python = "python",
    [ValidateRange(1024, 65535)][int]$DatabasePort = 5432
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    & docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop and wait for its engine, then rerun setup.ps1." }
    if (-not (Test-Path -LiteralPath ".env")) {
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $adminBytes = New-Object byte[] 24
            $appBytes = New-Object byte[] 24
            $generator.GetBytes($adminBytes)
            $generator.GetBytes($appBytes)
            $adminPassword = [BitConverter]::ToString($adminBytes).Replace("-", "").ToLowerInvariant()
            $appPassword = [BitConverter]::ToString($appBytes).Replace("-", "").ToLowerInvariant()
            $config = Get-Content -LiteralPath ".env.example" -Raw
            $config = $config.Replace("POSTGRES_ADMIN_PASSWORD=replace_me", "POSTGRES_ADMIN_PASSWORD=$adminPassword")
            $config = $config.Replace("SEAT_STORE_DB_PASSWORD=replace_me", "SEAT_STORE_DB_PASSWORD=$appPassword")
            $config = $config.Replace("seat_store:replace_me@", "seat_store:${appPassword}@")
            $config = $config.Replace("POSTGRES_PORT=5432", "POSTGRES_PORT=$DatabasePort")
            $config = $config.Replace("127.0.0.1:5432/", "127.0.0.1:$DatabasePort/")
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $config, (New-Object Text.UTF8Encoding $false))
        } finally { $generator.Dispose() }
        Write-Host "Created ignored .env with random local passwords."
    }
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or later is required." }
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & docker compose up -d --wait --wait-timeout 120 postgres
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start. Check docker compose logs postgres." }
    & .\.venv\Scripts\python.exe manage.py init-db
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }
    Write-Host "Setup complete. Start Module 3 with: .\run.ps1"
} finally { Pop-Location }

