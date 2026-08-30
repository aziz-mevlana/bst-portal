# Restart the website while keeping the existing Cloudflare Quick Tunnel alive.
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previewDir = Join-Path $projectRoot '.preview'
$stateFile = Join-Path $previewDir 'processes.json'
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$tunnelExe = Join-Path $previewDir 'tools/cloudflared.exe'
$runner = Join-Path $projectRoot 'preview_server.py'

function Get-RecordedProcess($entry) {
    $running = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq ([datetime]$entry.started).ToUniversalTime().Ticks) {
        return $running
    }
    return $null
}

if (-not (Test-Path -LiteralPath $stateFile)) { throw 'No preview record. Use start_cloudflare.ps1.' }
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$publicUrl = (Get-Content -LiteralPath (Join-Path $previewDir 'url.txt') -Raw).Trim()
if ($publicUrl -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$' -or $state.url -ne $publicUrl) {
    throw 'URL records do not match. Nothing was stopped.'
}
$tunnelRecord = $null
$serverRecord = $null
$serverProcess = $null
foreach ($entry in $state.processes) {
    $running = Get-RecordedProcess $entry
    if (-not $running) { continue }
    if ($running.Path -eq $tunnelExe) {
        if ($tunnelRecord) { throw 'Multiple tunnels recorded. Nothing was stopped.' }
        $tunnelRecord = $entry
    } elseif ($running.Path -eq $pythonExe) {
        if ($serverRecord) { throw 'Multiple servers recorded. Nothing was stopped.' }
        $serverRecord = $entry
        $serverProcess = $running
    } else { throw 'Unexpected recorded process. Nothing was stopped.' }
}
if (-not $tunnelRecord) { throw 'The original tunnel is not running; its temporary URL cannot be reused.' }
foreach ($listener in @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if (-not $serverProcess -or ($owner.ProcessId -ne $serverProcess.Id -and $owner.ParentProcessId -ne $serverProcess.Id)) {
        throw 'Port 8765 belongs to another process. Nothing was stopped.'
    }
}
Write-Output "Cloudflare stays running. Same URL: $publicUrl"
if (-not $PSCmdlet.ShouldProcess($publicUrl, 'Restart only the website and apply updates (brief interruption)')) { return }

$restartLock = [IO.File]::Open((Join-Path $previewDir 'restart.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
Push-Location $projectRoot
try {
    & $pythonExe manage.py check --settings=bst_portal.preview_settings
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed. The website was not stopped.' }
    if (-not (Get-RecordedProcess $tunnelRecord)) { throw 'Cloudflare is no longer running.' }
    if ($serverRecord) {
        $verifiedServer = Get-RecordedProcess $serverRecord
        if ($verifiedServer) {
            # Stop the venv launcher and its child, never cloudflared.
            & "$env:SystemRoot/System32/taskkill.exe" /PID $verifiedServer.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not stop the recorded website.' }
        }
    }
    $deadline = (Get-Date).AddSeconds(10)
    while (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
        if ((Get-Date) -ge $deadline) { throw 'Port 8765 did not close. Cloudflare was left running.' }
        Start-Sleep -Milliseconds 200
    }
    $databasePath = Join-Path $previewDir 'db.sqlite3'
    if (Test-Path -LiteralPath $databasePath) {
        $backupDir = Join-Path $previewDir 'backups'
        [IO.Directory]::CreateDirectory($backupDir) | Out-Null
        $backupPath = Join-Path $backupDir ('before-restart-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.sqlite3')
        & $pythonExe -c 'import sqlite3, sys; source = sqlite3.connect(sys.argv[1]); target = sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()' $databasePath $backupPath
        if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Cloudflare was left running.' }
    }
    & $pythonExe $runner --prepare
    if ($LASTEXITCODE -ne 0) { throw 'Preparation failed. Fix the error and rerun restart_site.ps1; Cloudflare is still running.' }
    if (-not (Get-RecordedProcess $tunnelRecord)) { throw 'Cloudflare stopped during preparation.' }
    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList ('"' + $runner + '"') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $previewDir 'server.stdout.log') `
        -RedirectStandardError (Join-Path $previewDir 'server.stderr.log')
    $newServerRecord = @{id = $serverProcess.Id; started = $serverProcess.StartTime.ToUniversalTime().ToString('o')}
    @{url = $publicUrl; processes = @($tunnelRecord, $newServerRecord)} |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($serverProcess.HasExited) { throw 'Website exited. Check .preview/server.stderr.log; Cloudflare was left running.' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8765/health/' -Headers @{'X-Forwarded-Proto' = 'https'} -TimeoutSec 3
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Website health check timed out. Cloudflare was left running.' }
    Write-Output "Website updated. Share the same link: $publicUrl"
} finally {
    Pop-Location
    $restartLock.Dispose()
}
