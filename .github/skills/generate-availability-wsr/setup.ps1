param(
    [string]$MetricsClientPath = $env:GENEVA_METRICS_CLIENT_PATH
)

$ErrorActionPreference = "Stop"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not $MetricsClientPath) {
    $repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
    $workspaceRoot = Split-Path $repositoryRoot -Parent
    $candidate = Join-Path $workspaceRoot `
        "Sigs\sources\dev\MomentsService\Tools\microsoft_cloud_metrics_client"
    if (Test-Path $candidate) {
        $MetricsClientPath = $candidate
    }
}

if (-not $MetricsClientPath -or -not (Test-Path $MetricsClientPath)) {
    throw @"
The Microsoft Cloud Metrics client path was not found.
Pass it explicitly:
  .\setup.ps1 -MetricsClientPath C:\path\to\microsoft_cloud_metrics_client
"@
}

if (-not (Test-Path (Join-Path $MetricsClientPath "pyproject.toml"))) {
    throw "MetricsClientPath must contain pyproject.toml."
}

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path $venvPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the Python virtual environment."
        }
    }

    & $venvPython -m pip install $MetricsClientPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the Microsoft Cloud Metrics client."
    }

    & $venvPython -m unittest discover -s .\tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Skill tests failed."
    }

    Write-Host "Availability WSR skill setup is complete."
}
finally {
    Pop-Location
}
