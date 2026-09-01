#!/usr/bin/env python3
"""Fetch ESS Admin API availability from Geneva Metrics."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from microsoft_cloud_metrics_client import (
    connection_info,
    metrics_reader_factory,
    metrics_reader_sync,
)


ACCOUNT = "M365_ESS"
NAMESPACE = "ESSAvailabilityR9"
METRIC = "RequestAvailability"
PREAGGREGATE = "EssAdmin Availibility Alert"
RING = "SDFV2"
REPORT_TIMEZONE = timezone(timedelta(hours=8))


def utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps must include a UTC offset or Z")
    return parsed.astimezone(timezone.utc)


def build_query() -> str:
    return (
        f"metricNamespace('{NAMESPACE}').metric('{METRIC}')"
        f".preaggregate('{PREAGGREGATE}')"
        ".samplingTypes('Count')\n"
        f"| where Component == 'EssAdminApi' and DeployRing == '{RING}'\n"
        "| zoom TotalCount = sum(Count) by 1d"
    )


def normalize_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def fetch(start: datetime, end: datetime) -> list[dict[str, Any]]:
    reader = metrics_reader_sync.MetricsReaderSync(
        metrics_reader_factory.create_metrics_reader_env(
            "availability-wsr-demo", connection_info.MdmEnvironment.Production
        )
    )
    try:
        frame = reader.execute_kqlm_query(
            ACCOUNT,
            build_query(),
            start,
            end,
        )
    finally:
        reader.close()

    rows = []
    for row in frame.to_dict(orient="records"):
        normalized = {key: normalize_value(value) for key, value in row.items()}
        total_count = normalized.get("totalcount")
        timestamp = datetime.fromisoformat(normalized["timestamp_utc"])
        if (
            start <= timestamp < end
            and isinstance(total_count, (int, float))
            and not math.isnan(total_count)
            and total_count > 0
        ):
            rows.append(normalized)
    return rows


def floor_to_report_day(value: datetime) -> datetime:
    local = value.astimezone(REPORT_TIMEZONE)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def main() -> None:
    default_end = datetime.now(timezone.utc)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=utc_datetime)
    parser.add_argument("--end", type=utc_datetime, default=default_end)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--output", type=Path, default=Path("output/geneva-request-availability.json")
    )
    args = parser.parse_args()

    if args.days <= 0:
        parser.error("--days must be greater than zero")
    selected_start = args.start or args.end - timedelta(days=args.days)
    if selected_start >= args.end:
        parser.error("--start must be earlier than --end")
    query_start = floor_to_report_day(selected_start)

    rows = fetch(query_start, args.end)
    result = {
        "source": {
            "account": ACCOUNT,
            "namespace": NAMESPACE,
            "metric": METRIC,
            "preaggregate": PREAGGREGATE,
            "query": build_query(),
            "selected_start_utc": selected_start.isoformat(),
            "query_start_utc": query_start.isoformat(),
            "end_utc": args.end.isoformat(),
            "report_timezone": "UTC+08:00",
            "ring": RING,
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(f"Fetched {len(rows):,} rows to {args.output.resolve()}")


if __name__ == "__main__":
    main()
