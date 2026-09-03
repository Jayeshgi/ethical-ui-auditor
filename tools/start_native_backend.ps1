[CmdletBinding()]
param(
    [string]$BindAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendDirectory = Join-Path $projectRoot "backend"
$environmentFile = Join-Path $projectRoot ".env"
$alembicConfig = Join-Path $projectRoot "alembic.ini"

$existingListener = Get-NetTCPConnection -LocalAddress $BindAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existingListener) {
    $owner = Get-Process -Id $existingListener.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($owner) { $owner.ProcessName } else { "unknown process" }
    $endpoint = "{0}:{1}" -f $BindAddress, $Port
    throw @"
Port $endpoint is already in use by PID $($existingListener.OwningProcess) ($ownerName).
If FlowLens is already open, use the running backend instead of starting a second copy.
To load new code, stop its original PowerShell window with Ctrl+C and run this script again.
For a temporary side-by-side instance, run:
  & '.\tools\start_native_backend.ps1' -Port 8001
"@
}

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Python environment not found at $pythonExecutable. Create it and install requirements.txt first."
}
if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw ".env is missing. Copy .env.example to .env and replace the placeholder secrets."
}

$env:PYTHONPATH = $backendDirectory
Push-Location $projectRoot
try {
    Write-Host "Applying PostgreSQL migrations..."
    & $pythonExecutable -m alembic -c $alembicConfig upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

Push-Location $backendDirectory
try {
    & $pythonExecutable -m uvicorn app.main:app --host $BindAddress --port $Port
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
