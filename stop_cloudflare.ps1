$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $PSScriptRoot '.preview/processes.json'
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Output 'No preview process record found.'
    exit 0
}
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
foreach ($entry in $state.processes) {
    $running = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    # PID reuse must never stop an unrelated application.
    if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq ([datetime]$entry.started).ToUniversalTime().Ticks) {
        # The Windows virtualenv launcher owns a child Python server process.
        & "$env:SystemRoot/System32/taskkill.exe" /PID $running.Id /T /F | Out-Null
    }
}
Write-Output 'Cloudflare preview stopped. Test data was preserved in .preview/.'
