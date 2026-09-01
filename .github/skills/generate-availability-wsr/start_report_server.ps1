param(
    [int]$Port = 8765,
    [switch]$Refresh
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pidFile = Join-Path $PSScriptRoot "output\report-server.pid"

if (-not (Test-Path $python)) {
    throw "Python environment not found at $python."
}

Push-Location $PSScriptRoot
try {
    if ($Refresh) {
        & ".\refresh_admin_api_report.ps1"
    }

    if (Test-Path $pidFile) {
        $existingPid = [int](Get-Content $pidFile)
        if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
            Start-Process "http://127.0.0.1:$Port/"
            Write-Host "Report server is already running with PID $existingPid."
            return
        }
        Remove-Item $pidFile
    }

    $process = Start-Process $python `
        -ArgumentList ".\ado_bug_server.py", "--port", $Port `
        -WorkingDirectory $PSScriptRoot `
        -PassThru
    $process.Id | Set-Content $pidFile
    Start-Sleep -Seconds 1

    try {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/health" | Out-Null
    }
    catch {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        throw "Report server failed to start."
    }

    Start-Process "http://127.0.0.1:$Port/"
    Write-Host "Report server started at http://127.0.0.1:$Port/ (PID $($process.Id))."
}
finally {
    Pop-Location
}
