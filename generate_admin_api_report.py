#!/usr/bin/env python3
"""Generate the Admin API availability HTML from Geneva query results."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


RING = "SDFV2"
REPORT_TIMEZONE = timezone(timedelta(hours=8))
SUCCESS_STATUS_CODES = {
    200,
    201,
    202,
    400,
    401,
    403,
    404,
    408,
    409,
    410,
    412,
    422,
    423,
    429,
}
MINIMUM_DAILY_COUNT = 120


def is_success_status(status_code: str) -> bool:
    return int(status_code) in SUCCESS_STATUS_CODES


def report_day(timestamp: str) -> str:
    return (
        datetime.fromisoformat(timestamp)
        .astimezone(REPORT_TIMEZONE)
        .date()
        .isoformat()
    )


def date_label(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return f"{parsed.day} {parsed.strftime('%b')}"


def build_report_data(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source")
    rows = payload.get("rows")
    if not isinstance(source, dict) or not isinstance(rows, list) or not rows:
        raise ValueError("Geneva input must contain non-empty source and rows fields")

    count_by_cell: dict[tuple[str, str], float] = defaultdict(float)
    success_by_cell: dict[tuple[str, str], float] = defaultdict(float)
    failure_status_by_cell: dict[
        tuple[str, str], dict[str, float]
    ] = defaultdict(lambda: defaultdict(float))
    failures_by_status_api: dict[tuple[str, str], float] = defaultdict(float)

    for row in rows:
        ring = str(row["deployring"]).upper()
        if ring != RING:
            continue
        scenario = str(row["scenario"])
        day = report_day(str(row["timestamp_utc"]))
        status = str(row["statuscode"])
        count = float(row["totalcount"])
        cell = (scenario, day)
        count_by_cell[cell] += count
        if is_success_status(status):
            success_by_cell[cell] += count
        else:
            failure_status_by_cell[cell][status] += count
            failures_by_status_api[(status, scenario)] += count

    dates = sorted({day for _, day in count_by_cell})
    if not dates:
        raise ValueError("No SDFV2 data was found in the Geneva result")

    scenarios = sorted({scenario for scenario, _ in count_by_cell})
    scenarios = [
        scenario
        for scenario in scenarios
        if any(count_by_cell.get((scenario, day), 0.0) > MINIMUM_DAILY_COUNT for day in dates)
    ]
    ring_rows: dict[str, list[float | None]] = {}
    ring_details: dict[str, list[dict[str, Any] | None]] = {}
    lowlights = []
    candidates = []
    for scenario in scenarios:
        values = []
        details = []
        for day in dates:
            cell = (scenario, day)
            total = count_by_cell.get(cell, 0.0)
            success = success_by_cell.get(cell, 0.0)
            availability = 100.0 * success / total if total else None
            values.append(round(availability, 2) if availability is not None else None)
            statuses = failure_status_by_cell[cell]
            top_status, top_count = (
                max(statuses.items(), key=lambda item: item[1])
                if statuses
                else ("n/a", 0.0)
            )
            details.append(
                {
                    "ring": RING,
                    "scenario": scenario,
                    "date": day,
                    "availability": round(availability, 2),
                    "total": round(total),
                    "unsuccessful": round(total - success),
                    "topStatus": top_status,
                    "topStatusCount": round(top_count),
                }
                if availability is not None
                else None
            )
            if availability is not None:
                candidates.append((availability, -total, scenario, day, total, total - success))
        ring_rows[scenario] = values
        ring_details[scenario] = details

    selected_candidates = []
    selected_scenarios = set()
    for candidate in sorted(candidates):
        scenario = candidate[2]
        if scenario in selected_scenarios:
            continue
        selected_candidates.append(candidate)
        selected_scenarios.add(scenario)
        if len(selected_candidates) == 3:
            break

    for availability, _, scenario, day, total, failed in selected_candidates:
        statuses = failure_status_by_cell[(scenario, day)]
        top_status, top_count = (
            max(statuses.items(), key=lambda item: item[1])
            if statuses
            else ("n/a", 0.0)
        )
        lowlights.append(
            {
                "title": f"{RING} · {scenario}",
                "text": (
                    f"Lowest daily availability was {availability:.2f}% on "
                    f"{date_label(day)} ({failed:,.0f} unsuccessful of "
                    f"{total:,.0f} samples). HTTP {top_status} contributed "
                    f"{top_count:,.0f} unsuccessful samples."
                ),
                "tag": f"HTTP {top_status}",
                "ring": RING,
                "scenario": scenario,
                "date": day,
                "availability": round(availability, 2),
                "total": round(total),
                "unsuccessful": round(failed),
                "topStatus": top_status,
                "topStatusCount": round(top_count),
            }
        )

    top_causes = []
    status_totals: dict[str, float] = defaultdict(float)
    for (status, _), count in failures_by_status_api.items():
        status_totals[status] += count
    for status, count in sorted(
        status_totals.items(), key=lambda item: item[1], reverse=True
    )[:4]:
        api_counts = sorted(
            (
                (api, api_count)
                for (item_status, api), api_count in failures_by_status_api.items()
                if item_status == status
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        top_causes.append(
            {
                "label": f"{RING} / HTTP {status}",
                "count": round(count),
                "apis": [api for api, _ in api_counts[:5]],
            }
        )

    return {
        "metadata": {
            "source": (
                f"Live Geneva: {source['account']} / {source['namespace']} / "
                f"{source['metric']}"
            ),
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "rule": (
                "Jarvis formula: successful Count / total Count; successful "
                "status codes are 200, 201, 202, 400, 401, 403, 404, 408, "
                "409, 410, 412, 422, 423, and 429"
            ),
        },
        "dates": [date_label(day) for day in dates],
        "rings": [{"name": RING, "rows": ring_rows, "details": ring_details}],
        "lowlights": lowlights,
        "topCauses": top_causes,
    }


def render(template: str, report: dict[str, Any]) -> str:
    data_block = "\n".join(
        (
            "    // DATA_START",
            "    const reportMetadata = "
            + json.dumps(report["metadata"], ensure_ascii=True, indent=2)
            + ";",
            "    const dates = "
            + json.dumps(report["dates"], ensure_ascii=True, indent=2)
            + ";",
            "    const rings = "
            + json.dumps(report["rings"], ensure_ascii=True, indent=2)
            + ";",
            "    const lowlights = "
            + json.dumps(report["lowlights"], ensure_ascii=True, indent=2)
            + ";",
            "    const topCauses = "
            + json.dumps(report["topCauses"], ensure_ascii=True, indent=2)
            + ";",
            "    // DATA_END",
        )
    )
    output, replacements = re.subn(
        r"    // DATA_START.*?    // DATA_END",
        lambda _: data_block,
        template,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise ValueError("HTML template does not contain one data block")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/geneva-request-availability.json"),
    )
    parser.add_argument(
        "--template", type=Path, default=Path("admin-api-availability.html")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/admin-api-availability-live.html"),
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    template = args.template.read_text(encoding="utf-8")
    report = build_report_data(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(template, report), encoding="utf-8")
    print(f"Generated live report at {args.output.resolve()}")


if __name__ == "__main__":
    main()
