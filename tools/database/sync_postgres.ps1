[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("NativeToDocker", "DockerToNative")]
    [string]$Direction,

    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$environmentFile = Join-Path $projectRoot ".env"
$backupDirectory = Join-Path $projectRoot "runtime_data\database_backups"
$databaseName = "ethical_ui_auditor"
$databaseUser = "auditor"
$nativeHost = "127.0.0.1"
$nativePort = 5432
$postgresBin = "C:\Program Files\PostgreSQL\17\bin"
$nativeDump = Join-Path $postgresBin "pg_dump.exe"
$nativeRestore = Join-Path $postgresBin "pg_restore.exe"
$nativePsql = Join-Path $postgresBin "psql.exe"
$dockerExecutable = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"

function Get-EnvironmentValue {
    param([Parameter(Mandatory)][string]$Name)

    $line = Get-Content -LiteralPath $environmentFile |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -First 1
    if (-not $line) {
        throw "$Name is missing from $environmentFile"
    }
    return $line.Substring($Name.Length + 1).Trim().Trim('"').Trim("'")
}

function Invoke-NativeDump {
    param([Parameter(Mandatory)][string]$OutputPath)

    & $nativeDump -h $nativeHost -p $nativePort -U $databaseUser -d $databaseName `
        --format=custom --no-owner --no-acl --file=$OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Native PostgreSQL backup failed."
    }
}

function Start-DockerDatabase {
    Push-Location $projectRoot
    try {
        & $dockerExecutable compose up --detach --wait --wait-timeout 180 database
        if ($LASTEXITCODE -ne 0) {
            throw "Docker PostgreSQL did not become healthy."
        }
        $containerId = (& $dockerExecutable compose ps -q database | Out-String).Trim()
        if (-not $containerId) {
            throw "Docker PostgreSQL container was not found."
        }
        return $containerId
    } finally {
        Pop-Location
    }
}

function Invoke-DockerDump {
    param(
        [Parameter(Mandatory)][string]$ContainerId,
        [Parameter(Mandatory)][string]$OutputPath
    )

    $fileName = [IO.Path]::GetFileName($OutputPath)
    $containerPath = "/tmp/$fileName"
    & $dockerExecutable exec $ContainerId pg_dump -U $databaseUser -d $databaseName `
        --format=custom --no-owner --no-acl --file=$containerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Docker PostgreSQL backup failed."
    }
    & $dockerExecutable cp "${ContainerId}:$containerPath" $OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not copy the Docker PostgreSQL backup."
    }
}

function Restore-NativeDatabase {
    param([Parameter(Mandatory)][string]$InputPath)

    & $nativeRestore -h $nativeHost -p $nativePort -U $databaseUser -d $databaseName `
        --clean --if-exists --no-owner --no-privileges --exit-on-error $InputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Native PostgreSQL restore failed. Its pre-sync backup is in $backupDirectory."
    }
}

function Restore-DockerDatabase {
    param(
        [Parameter(Mandatory)][string]$ContainerId,
        [Parameter(Mandatory)][string]$InputPath
    )

    $fileName = [IO.Path]::GetFileName($InputPath)
    $containerPath = "/tmp/$fileName"
    & $dockerExecutable cp $InputPath "${ContainerId}:$containerPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not copy the native backup into Docker."
    }
    & $dockerExecutable exec $ContainerId pg_restore -U $databaseUser -d $databaseName `
        --clean --if-exists --no-owner --no-privileges --exit-on-error $containerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Docker PostgreSQL restore failed. Its pre-sync backup is in $backupDirectory."
    }
}

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw ".env is missing at $environmentFile"
}
if (-not (Test-Path -LiteralPath $nativeDump) -or
    -not (Test-Path -LiteralPath $nativeRestore) -or
    -not (Test-Path -LiteralPath $nativePsql)) {
    throw "Native PostgreSQL 17 command-line tools were not found in $postgresBin"
}
if (-not (Test-Path -LiteralPath $dockerExecutable)) {
    throw "Docker Desktop was not found at $dockerExecutable"
}

Write-Output "Direction: $Direction"
Write-Output "Source and destination: $databaseName"
Write-Output "Backup directory: $backupDirectory"
if (-not $Apply) {
    Write-Output "Dry run only. Re-run with -Apply to back up both sides and replace the destination database."
    exit 0
}

New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$databasePassword = Get-EnvironmentValue -Name "POSTGRES_PASSWORD"
if ($databasePassword.Length -lt 16) {
    throw "POSTGRES_PASSWORD must be at least 16 characters."
}
$env:PGPASSWORD = $databasePassword

try {
    $containerId = Start-DockerDatabase
    if ($Direction -eq "NativeToDocker") {
        $sourceBackup = Join-Path $backupDirectory "native-source-$timestamp.dump"
        $targetBackup = Join-Path $backupDirectory "docker-before-sync-$timestamp.dump"
        Invoke-NativeDump -OutputPath $sourceBackup
        Invoke-DockerDump -ContainerId $containerId -OutputPath $targetBackup

        Push-Location $projectRoot
        try {
            $apiContainerId = (& $dockerExecutable compose ps -q api | Out-String).Trim()
            $apiWasRunning = $false
            if ($apiContainerId) {
                $apiWasRunning = ((& $dockerExecutable inspect --format "{{.State.Running}}" $apiContainerId | Out-String).Trim() -eq "true")
            }
            if ($apiWasRunning) {
                & $dockerExecutable compose stop api
            }
            try {
                Restore-DockerDatabase -ContainerId $containerId -InputPath $sourceBackup
            } finally {
                if ($apiWasRunning) {
                    & $dockerExecutable compose up --detach --wait --wait-timeout 180 api
                }
            }
        } finally {
            Pop-Location
        }
    } else {
        $sourceBackup = Join-Path $backupDirectory "docker-source-$timestamp.dump"
        $targetBackup = Join-Path $backupDirectory "native-before-sync-$timestamp.dump"
        Invoke-DockerDump -ContainerId $containerId -OutputPath $sourceBackup
        Invoke-NativeDump -OutputPath $targetBackup
        Restore-NativeDatabase -InputPath $sourceBackup
    }

    $countSql = "SELECT 'users=' || count(*) FROM users UNION ALL SELECT 'scan_jobs=' || count(*) FROM scan_jobs UNION ALL SELECT 'finding_reviews=' || count(*) FROM finding_reviews ORDER BY 1;"
    Write-Output "Native row counts:"
    & $nativePsql -h $nativeHost -p $nativePort -U $databaseUser -d $databaseName -tAc $countSql
    Write-Output "Docker row counts:"
    & $dockerExecutable exec $containerId psql -U $databaseUser -d $databaseName -tAc $countSql
    Write-Output "Synchronization completed. Source and destination backups are in $backupDirectory."
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
