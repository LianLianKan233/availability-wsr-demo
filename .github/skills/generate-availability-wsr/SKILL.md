---
name: generate-availability-wsr
description: Generate the ESS Programming Model Admin API availability WSR from live Geneva metrics, explain deterministic lowlights, serve an interactive HTML report, and create confirmed Azure DevOps bugs. Use for "generate WSR", "refresh availability report", "Admin API availability", or "create WSR bug".
metadata:
  author: ESS Programming Model
  version: "1.0"
compatibility: Windows, Python 3.10+, Azure CLI authentication, and the internal Microsoft Cloud Metrics Python client.
---

# Generate Availability WSR

Use the files in this skill directory as a self-contained report application.
Do not search for or depend on another copy of the demo unless the user asks to
update the application itself.

## Required inputs

- Report lookback, defaulting to 14 days.
- An Azure CLI identity with read access to the `M365_ESS` monitoring account.
- For bug creation, access to create Bugs in the `O365 Core` Azure DevOps
  project.
- A local checkout or package path for `microsoft_cloud_metrics_client` when
  `.venv` has not been created.

## Fixed metric semantics

Preserve these settings unless the user provides a newer Jarvis definition:

| Setting | Value |
|---|---|
| Monitoring account | `M365_ESS` |
| Namespace | `ESSAvailabilityR9` |
| Metric | `RequestAvailability` |
| Preaggregation | `EssAdmin Availibility Alert` |
| Sampling type | `Count` |
| Component | `EssAdminApi` |
| Ring | `SDFV2` |
| Formula | `successful Count * 100 / total Count` |
| Day boundary | UTC+8 calendar day |
| Scenario filter | Include when any daily total is greater than 120 |

The successful HTTP status allowlist is:

```text
200, 201, 202, 400, 401, 403, 404,
408, 409, 410, 412, 422, 423, 429
```

Do not substitute conventional HTTP success semantics. In particular, this
Jarvis widget treats `408`, `423`, and `429` as successful.

Heatmap thresholds:

- `>= 99.99`: green
- `99.00-99.98`: yellow
- `98.00-98.99`: orange
- `< 98.00`: red

`jarvis-dashboard.json` is the captured source definition used to verify these
settings.

## Workflow

1. Work on Windows and set the current directory to this skill directory.
2. Confirm Azure CLI authentication with `az account show`. If authentication
   is missing, ask the user to run `az login`; never request or store a token.
3. If `.venv\Scripts\python.exe` is absent, locate the internal
   `microsoft_cloud_metrics_client` package and run:

   ```powershell
   .\setup.ps1 -MetricsClientPath <path-to-microsoft_cloud_metrics_client>
   ```

4. Generate fresh data and HTML:

   ```powershell
   .\refresh_admin_api_report.ps1
   ```

5. Confirm these artifacts exist:
   - `output\geneva-request-availability.json`
   - `output\admin-api-availability-live.html`
6. Run the tests:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s .\tests -v
   ```

7. Start the interactive report:

   ```powershell
   .\start_report_server.ps1
   ```

8. Give the user the local URL `http://127.0.0.1:8765/`.

Use `.\start_report_server.ps1 -Refresh` when the user explicitly wants refresh
and startup combined.

## Key lowlights algorithm

Generate lowlights deterministically:

1. Aggregate `Count` by SDFV2 API, UTC+8 report day, and status code.
2. Calculate each API-day availability with the fixed successful-status
   allowlist.
3. Remove APIs whose daily total never exceeds 120.
4. Sort API-day cells by ascending availability. For equal availability,
   prefer the cell with more traffic.
5. Select the three worst cells from three distinct APIs.
6. Report date, availability, unsuccessful count, total count, and the most
   frequent unsuccessful HTTP status.

Describe the dominant status as a correlation or investigation lead, not as a
confirmed root cause.

## Azure DevOps bug creation

The browser sends bug requests only to the local backend. The backend acquires
a short-lived Azure DevOps token through Azure CLI and must never return or log
that token.

Use these server-controlled defaults:

| Field | Value |
|---|---|
| Project | `O365 Core` |
| Work item type | `Bug` |
| Area | `O365 Core\ESS` |
| Iteration | Current month, such as `O365 Core\Monthly\CY26-Q3\CY26-08` |
| Priority | `2` |
| Severity | User-selected, default `3 - Medium` |
| Tags | `Programming Model; WSR` |
| PS Database | `OfficeMain` |
| Triage | `Not Triaged` |

Never create a work item automatically. Require the user to review the title
and notes and select the explicit real-bug confirmation checkbox.

When changing the ADO payload, validate it without saving:

```text
POST .../_apis/wit/workitems/$Bug?validateOnly=true&api-version=7.1
```

## Adapting another Jarvis availability widget

Do not copy the existing formula blindly. Ask for the dashboard JSON, then:

1. Identify account, namespace, metric, preaggregation, dimensions, sampling
   type, filters, formula, timezone, traffic threshold, and color boundaries.
2. Update the query and calculation constants.
3. Add fixture data that exercises the revised status and threshold rules.
4. Compare several generated cells with the visible Jarvis values before
   claiming equivalence.
5. Keep report detection deterministic; language-model wording may summarize
   evidence but must not decide availability values.

## Safety and sharing

- Bind the report server only to `127.0.0.1`.
- Never commit `.venv`, `output`, tokens, credentials, or connection strings.
- Treat dashboard definitions and organization URLs as internal information;
  share the folder only through an approved private or internal channel.
- Do not create a disposable real bug for testing. Use mocked tests and the
  ADO `validateOnly=true` option.
- Stop the server with `.\stop_report_server.ps1`.

## Human documentation

See `README.md` in this directory for setup, standalone use, and a file
inventory.
