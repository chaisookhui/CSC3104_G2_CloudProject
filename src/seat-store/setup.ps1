param(
    [string]$Python = "python",
    [switch]$SkipPythonSetup,
    [switch]$NativePostgres,
    [ValidateRange(1024, 65535)][int]$DatabasePort = 5432
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    if (-not $SkipPythonSetup) {
        & (Join-Path $PSScriptRoot "..\..\setup.ps1") -Python $Python -PythonOnly
    }
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
            if ($NativePostgres) { $config = $config.Replace("POSTGRES_BACKEND=docker", "POSTGRES_BACKEND=native") }
            [IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $config, (New-Object Text.UTF8Encoding $false))
        } finally { $generator.Dispose() }
        Write-Host "Created ignored .env with random local passwords."
    }
    $projectPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython)) { throw "Run the root setup.ps1 first." }
    # Send Python code on stdin so Windows PowerShell preserves its string quotes.
    $backend = 'import os; from dotenv import load_dotenv; load_dotenv(".env"); print(os.getenv("POSTGRES_BACKEND", "docker"))' | & $projectPython -
    if ($LASTEXITCODE -ne 0) { throw "Could not read POSTGRES_BACKEND from local configuration." }
    if ($NativePostgres -and $backend -ne "native") { throw "Existing .env uses Docker. Preserve it and coordinate a backend change before continuing." }
    if ($backend -eq "native") {
        & $projectPython native_db.py setup
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL setup failed." }
    } elseif ($backend -eq "docker") {
        & docker info --format '{{.ServerVersion}}'
        if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop, or use the documented native PostgreSQL setup." }
        & docker compose up -d --wait --wait-timeout 120 postgres
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start. Check docker compose logs postgres." }
    } else { throw "POSTGRES_BACKEND must be docker or native." }
    & $projectPython manage.py init-db
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }
    Write-Host "Setup complete. Start Module 3 with: .\run.ps1"
} finally { Pop-Location }

