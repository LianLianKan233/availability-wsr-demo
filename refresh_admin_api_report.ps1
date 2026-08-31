$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Geneva environment not found. Create .venv and install microsoft-cloud-metrics-client first."
}

Push-Location $PSScriptRoot
try {
    & $python ".\fetch_geneva.py" --days 14
    if ($LASTEXITCODE -ne 0) {
        throw "Geneva query failed with exit code $LASTEXITCODE."
    }

    & $python ".\generate_admin_api_report.py"
    if ($LASTEXITCODE -ne 0) {
        throw "HTML generation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
