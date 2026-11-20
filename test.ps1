param([switch]$SmokeOnly)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        throw "Run .\setup.ps1 -PythonOnly first."
    }
    $expectedVersion = (Get-Content -LiteralPath ".python-version" -Raw).Trim()
    $actualVersion = & .\.venv\Scripts\python.exe -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $expectedVersion) {
        throw "Recreate the project environment with Python $expectedVersion before testing."
    }
    & .\.venv\Scripts\python.exe -m pytest tests/test_health.py -q @args
    if ($LASTEXITCODE -ne 0) { throw "Foundation tests failed." }
    if (-not $SmokeOnly) {
        # Separate processes prevent the two existing app.py modules colliding.
        & .\src\seat-store\test.ps1 @args
    }
} finally { Pop-Location }
