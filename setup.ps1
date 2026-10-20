param(
    [string]$Python = "python",
    [switch]$PythonOnly,
    [switch]$NativePostgres,
    [ValidateRange(1024, 65535)][int]$DatabasePort = 5432
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
try {
    $expectedVersion = (Get-Content -LiteralPath ".python-version" -Raw).Trim()
    $actualVersion = & $Python -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $expectedVersion) {
        throw "Use Python $expectedVersion. Pass -Python with its executable path if needed."
    }
    # Keep temporary installer files inside the ignored project environment.
    New-Item -ItemType Directory -Force ".venv\tmp" | Out-Null
    $env:TEMP = Join-Path $PSScriptRoot ".venv\tmp"
    $env:TMP = $env:TEMP
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
    }
    $environmentVersion = & .\.venv\Scripts\python.exe -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $environmentVersion -ne $expectedVersion) {
        throw "Existing .venv uses another Python version. Preserve it elsewhere and recreate it with Python $expectedVersion."
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    & .\.venv\Scripts\python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed." }
    if (-not $PythonOnly) {
        & .\src\seat-store\setup.ps1 -SkipPythonSetup -DatabasePort $DatabasePort -NativePostgres:$NativePostgres
    }
    Write-Host "Setup complete. See README.md for startup and test commands."
} finally {
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
    Pop-Location
}
