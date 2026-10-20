param([switch]$SmokeOnly)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        throw "Run .\setup.ps1 -PythonOnly first."
    }
    & .\.venv\Scripts\python.exe -m pytest tests -q @args
    if ($LASTEXITCODE -ne 0) { throw "Foundation tests failed." }
    if (-not $SmokeOnly) {
        # Separate processes prevent the two existing app.py modules colliding.
        & .\src\seat-store\test.ps1 @args
    }
} finally { Pop-Location }
