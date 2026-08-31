# Availability WSR demo

A dependency-free demo that turns aggregated availability telemetry into a
shareable HTML service-review report.

The report:

- calculates availability and change from the previous period;
- evaluates each ring against its own target;
- ranks error categories and explains the most likely cause per ring;
- includes daily trend charts and a link to the Jarvis dashboard.

The included data is illustrative. It is shaped after the ESS Programming Model
section of `WSR20260826.pptx`; it is not live production telemetry.

## Admin API slide replacement

`admin-api-availability.html` is a standalone replacement for the current
Admin API Availability slide. It includes four ring heatmaps, computed ring
summaries, lowlights, top causes, investments, and a link to the source Jarvis
dashboard.

Open it directly:

```powershell
Start-Process .\admin-api-availability.html
```

## Run

Python 3.10 or later is recommended.

```powershell
python .\generate_report.py
Start-Process .\output\availability-report.html
```

Use another telemetry export:

```powershell
python .\generate_report.py --input .\my-availability-data.json `
  --output .\output\availability-report.html
```

Run tests:

```powershell
python -m unittest discover -s .\tests -v
```

## Input contract

`sample-data.json` is the executable example. Each ring requires:

| Field | Meaning |
|---|---|
| `target` | Availability objective for the ring |
| `current` | Total requests and failures in the report window |
| `previous` | Totals in the comparison window |
| `daily_availability` | Daily percentages used by the trend chart |
| `causes` | Aggregated failures by API, error, and optional status code |

The MDM/Kusto integration only needs to produce this JSON shape. Query execution
is deliberately outside the demo because unattended Geneva authentication and
the backing metric dimensions must be confirmed with the dashboard owner.

## Fetch confirmed Geneva metric

The Admin API dashboard uses:

- account: `M365_ESS`
- namespace: `ESSAvailabilityR9`
- metric: `RequestAvailability`
- preaggregation: `EssAdmin Availibility Alert`

`fetch_geneva.py` queries that signal with Azure Identity and writes the raw,
timestamped rows to JSON:

```powershell
.\.venv\Scripts\python.exe .\fetch_geneva.py --days 14
```

The signed-in identity needs read access to the monitoring account. No
credential or access token is written to the output.

Refresh both the data and HTML:

```powershell
.\refresh_admin_api_report.ps1
Start-Process .\output\admin-api-availability-live.html
```

## Create Azure DevOps bugs from the report

Start the local same-origin report server:

```powershell
.\start_report_server.ps1
```

Use `-Refresh` to fetch Geneva data before opening the page. Click any degraded
heatmap cell or a **Create bug** button under Key lowlights. The dialog lets you
review and edit the title, investigation notes, and severity before explicitly
confirming creation of a real work item.

The backend creates a Bug in `O365 Core` with area `O365 Core\ESS`, priority 2,
the current monthly iteration, tags `Programming Model; WSR`, and PS Database
`OfficeMain`. It obtains a short-lived Azure DevOps bearer token from the
existing Azure CLI sign-in; the token is kept server-side and is never returned
to browser JavaScript or written to the report.

Stop the local server:

```powershell
.\stop_report_server.ps1
```

The SDFV2 report reproduces the Jarvis widget formula:

```text
successful Count * 100 / total Count
```

Successful status codes are `200`, `201`, `202`, `400`, `401`, `403`, `404`,
`408`, `409`, `410`, `412`, `422`, `423`, and `429`. Days are aligned to
UTC+8 calendar boundaries, and scenarios are retained when any daily total is
greater than 120, matching the SDFV2 widget configuration.

## Replace the sample with MDM/Kusto data

1. Identify the backing query for each Jarvis availability panel.
2. Aggregate request and failure counts by ring for the current and previous
   periods.
3. Aggregate current-period failures by ring, API, status code, and exception.
4. Export the results in the `sample-data.json` shape.
5. Run this generator from a scheduled Azure DevOps pipeline or Azure Function.

Keep detection deterministic. A language model may improve the wording later,
but availability status and cause ranking should continue to come from the
query results and configured rules.
