param([ValidateSet('init-db','serve','worker','work-status','retry-work')][string]$Command = 'serve',
      [string]$WorkId)
$ErrorActionPreference = 'Stop'
$paymentPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $paymentPython)) { throw 'Run root setup.ps1 first.' }
$expectedVersion = (Get-Content (Join-Path $PSScriptRoot '..\..\.python-version') -Raw).Trim()
$actualVersion = & $paymentPython -c 'import platform; print(platform.python_version())'
if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $expectedVersion) { throw "Use project Python $expectedVersion." }
$paymentArguments = @((Join-Path $PSScriptRoot 'service.py'), $Command)
if ($WorkId) { $paymentArguments += @('--work-id', $WorkId) }
& $paymentPython @paymentArguments
if ($LASTEXITCODE -ne 0) { throw 'Payment command failed.' }
