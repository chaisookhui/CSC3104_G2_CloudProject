$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & .\.venv\Scripts\python.exe -m pytest tests -q @args
    if ($LASTEXITCODE -ne 0) { throw "Module 3 tests failed." }
} finally { Pop-Location }

