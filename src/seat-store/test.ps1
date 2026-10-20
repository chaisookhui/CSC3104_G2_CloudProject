$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython)) { throw "Run the root setup.ps1 first." }
    & $projectPython -m pytest tests -q @args
    if ($LASTEXITCODE -ne 0) { throw "Module 3 tests failed." }
} finally { Pop-Location }

