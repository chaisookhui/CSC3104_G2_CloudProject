$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $projectPython)) { throw "Run the root setup.ps1 first." }
    $expectedVersion = (Get-Content (Join-Path $PSScriptRoot "..\..\.python-version") -Raw).Trim()
    $actualVersion = & $projectPython -c 'import platform; print(platform.python_version())'
    if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $expectedVersion) {
        throw "Run root setup.ps1 with Python $expectedVersion before testing seat-store."
    }
    & $projectPython -m pytest tests -q @args
    if ($LASTEXITCODE -ne 0) { throw "Module 3 tests failed." }
} finally { Pop-Location }

