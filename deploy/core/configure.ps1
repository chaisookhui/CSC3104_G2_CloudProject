param([ValidateRange(1024, 65535)][int]$DatabasePort = 5432)
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "../../src/seat-store"
$envPath = Join-Path $modulePath ".env"
if (Test-Path -LiteralPath $envPath) {
    Write-Host "Keeping existing src/seat-store/.env. Use its original database passwords."
    return
}
$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $adminBytes = New-Object byte[] 24
    $appBytes = New-Object byte[] 24
    $generator.GetBytes($adminBytes)
    $generator.GetBytes($appBytes)
    $adminPassword = [BitConverter]::ToString($adminBytes).Replace("-", "").ToLowerInvariant()
    $appPassword = [BitConverter]::ToString($appBytes).Replace("-", "").ToLowerInvariant()
    $config = Get-Content -LiteralPath (Join-Path $modulePath ".env.example") -Raw
    $config = $config.Replace("POSTGRES_ADMIN_PASSWORD=replace_me", "POSTGRES_ADMIN_PASSWORD=$adminPassword")
    $config = $config.Replace("SEAT_STORE_DB_PASSWORD=replace_me", "SEAT_STORE_DB_PASSWORD=$appPassword")
    $config = $config.Replace("seat_store:replace_me@", "seat_store:${appPassword}@")
    $config = $config.Replace("POSTGRES_PORT=5432", "POSTGRES_PORT=$DatabasePort")
    $config = $config.Replace("127.0.0.1:5432/", "127.0.0.1:$DatabasePort/")
    [IO.File]::WriteAllText($envPath, $config, (New-Object Text.UTF8Encoding $false))
} finally { $generator.Dispose() }
Write-Host "Created ignored src/seat-store/.env with random local database passwords."
