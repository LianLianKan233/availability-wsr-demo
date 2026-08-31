$ErrorActionPreference = "Stop"
$pidFile = Join-Path $PSScriptRoot "output\report-server.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "No report server PID file was found."
    return
}

$serverPid = [int](Get-Content $pidFile)
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($process) {
    $childProcesses = Get-CimInstance Win32_Process |
        Where-Object { $_.ParentProcessId -eq $serverPid }
    foreach ($childProcess in $childProcesses) {
        Stop-Process -Id $childProcess.ProcessId -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $serverPid
    Write-Host "Stopped report server PID $serverPid."
}
else {
    Write-Host "Report server PID $serverPid was not running."
}
Remove-Item $pidFile
