# ESS Availability WSR skill

This folder contains everything needed to generate and review the ESS
Programming Model SDFV2 Admin API availability WSR:

- the reusable Copilot skill instructions;
- the captured Jarvis dashboard definition;
- live Geneva query and report-generation scripts;
- the interactive HTML template;
- the local Azure DevOps bug-creation backend;
- startup, shutdown, and refresh PowerShell scripts;
- sample input and unit tests.

The Python virtual environment, generated reports, and authentication tokens
are deliberately excluded.

## Install as a Copilot skill

Copy the entire `generate-availability-wsr` folder to:

```text
<repository>\.github\skills\generate-availability-wsr
```

Open Copilot CLI from that repository and use `/skills` to confirm that
`generate-availability-wsr` is available. Example requests:

```text
Generate the Admin API availability WSR for the last 14 days.
Refresh the availability WSR and start the interactive report.
Explain the key lowlights in this WSR.
```

The folder can also run as a standalone application without Copilot.

## One-time setup

Requirements:

- Windows
- Python 3.10 or later
- Azure CLI
- access to the internal Microsoft Cloud Metrics Python client
- Geneva access to the `M365_ESS` monitoring account

Sign in:

```powershell
az login
```

Create the environment and install the Geneva client:

```powershell
.\setup.ps1 `
  -MetricsClientPath C:\path\to\microsoft_cloud_metrics_client
```

For a standard Sigs checkout, the package is under:

```text
Sigs\sources\dev\MomentsService\Tools\microsoft_cloud_metrics_client
```

## Generate and open the report

```powershell
.\refresh_admin_api_report.ps1
.\start_report_server.ps1
```

Open `http://127.0.0.1:8765/`. Degraded heatmap cells and key lowlights can
prefill an Azure DevOps Bug. Creation remains disabled until the user reviews
the content and checks the explicit confirmation box.

Stop the server:

```powershell
.\stop_report_server.ps1
```

## File inventory

| File | Purpose |
|---|---|
| `SKILL.md` | Copilot workflow, rules, and activation description |
| `jarvis-dashboard.json` | Captured source dashboard definition |
| `fetch_geneva.py` | Fetches live daily Count aggregates |
| `generate_admin_api_report.py` | Applies the Jarvis formula and lowlight selection |
| `admin-api-availability.html` | Heatmap and bug-creation UI template |
| `ado_bug_server.py` | Local server and Azure DevOps integration |
| `refresh_admin_api_report.ps1` | Fetches data and regenerates HTML |
| `start_report_server.ps1` | Starts the local server and opens the browser |
| `stop_report_server.ps1` | Stops the local server |
| `setup.ps1` | Creates `.venv` and installs the Geneva client |
| `sample-data.json` | Generic report-generator example |
| `generate_report.py` | Generic non-Geneva availability report demo |
| `tests\test_generate_report.py` | Calculation, rendering, and backend tests |

## Generated files

The following are local artifacts and should not be shared as source:

```text
.venv\
output\
__pycache__\
*.pyc
```

The dashboard JSON and organization URLs are internal. Share this package only
through an approved private or internal channel.
