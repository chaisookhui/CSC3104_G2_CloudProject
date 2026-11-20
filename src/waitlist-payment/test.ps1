$ErrorActionPreference = 'Stop'
$paymentPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
& $paymentPython -m pytest (Join-Path $PSScriptRoot 'tests') -q @args
if ($LASTEXITCODE -ne 0) { throw 'Payment tests failed.' }
