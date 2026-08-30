$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previewDir = Join-Path $projectRoot '.preview'
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$tunnelExe = Join-Path $previewDir 'tools/cloudflared.exe'
$stateFile = Join-Path $previewDir 'processes.json'
$runner = Join-Path $projectRoot 'preview_server.py'
if (-not (Test-Path -LiteralPath $tunnelExe)) {
    throw 'Cloudflared is missing from .preview/tools/cloudflared.exe.'
}
if (Test-Path -LiteralPath $stateFile) {
    $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    foreach ($entry in $previous.processes) {
        $running = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq ([datetime]$entry.started).ToUniversalTime().Ticks) {
            throw 'Preview is already running. Use restart_site.ps1 to update the website while keeping its URL. Use stop_cloudflare.ps1 only to stop the tunnel too.'
        }
    }
}
if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8765 is already in use. No existing service was stopped.'
}

Push-Location $projectRoot
$tunnelProcess = $null
$serverProcess = $null
try {
    & $pythonExe $runner --prepare
    if ($LASTEXITCODE -ne 0) { throw 'Preview preparation failed.' }

    $tunnelLog = Join-Path $previewDir 'tunnel.stderr.log'
    $tunnelProcess = Start-Process -FilePath $tunnelExe -ArgumentList @(
        'tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8765',
        '--protocol', 'http2', '--metrics', '127.0.0.1:18765'
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $previewDir 'tunnel.stdout.log') `
        -RedirectStandardError $tunnelLog

    $deadline = (Get-Date).AddSeconds(45)
    $publicUrl = $null
    while ((Get-Date) -lt $deadline) {
        if ($tunnelProcess.HasExited) { throw 'Cloudflare exited; inspect .preview/tunnel.stderr.log.' }
        if (Test-Path -LiteralPath $tunnelLog) {
            $logText = Get-Content -LiteralPath $tunnelLog -Raw
            if ($logText -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
                $publicUrl = $Matches[0]
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $publicUrl) { throw 'Cloudflare did not return a URL within 45 seconds.' }
    [IO.File]::WriteAllText((Join-Path $previewDir 'url.txt'), $publicUrl)

    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList ('"' + $runner + '"') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $previewDir 'server.stdout.log') `
        -RedirectStandardError (Join-Path $previewDir 'server.stderr.log')

    $processRecords = @($tunnelProcess, $serverProcess) | ForEach-Object {
        @{id=$_.Id; started=$_.StartTime.ToUniversalTime().ToString('o')}
    }
    @{url=$publicUrl; processes=@($processRecords)} | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $stateFile -Encoding UTF8

    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($serverProcess.HasExited) { throw 'Preview server exited; inspect .preview/server.stderr.log.' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8765/health/' `
                -Headers @{'X-Forwarded-Proto'='https'} -TimeoutSec 3
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Preview health check failed.' }
    Write-Output "Preview URL: $publicUrl"
    Write-Output 'Keep this computer awake and online. Stop with stop_cloudflare.ps1.'
} catch {
    foreach ($process in @($serverProcess, $tunnelProcess)) {
        if ($process -and -not $process.HasExited) {
            & "$env:SystemRoot/System32/taskkill.exe" /PID $process.Id /T /F | Out-Null
        }
    }
    throw
} finally {
    Pop-Location
}
