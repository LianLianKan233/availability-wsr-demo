#!/usr/bin/env python3
"""Generate an Availability WSR HTML report from aggregated telemetry."""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PeriodMetrics:
    requests: int
    failures: int

    @property
    def availability(self) -> float:
        if self.requests <= 0:
            raise ValueError("requests must be greater than zero")
        if self.failures < 0 or self.failures > self.requests:
            raise ValueError("failures must be between zero and requests")
        return 100.0 * (self.requests - self.failures) / self.requests


@dataclass(frozen=True)
class RingAnalysis:
    name: str
    status: str
    target: float
    current: PeriodMetrics
    previous: PeriodMetrics
    daily_availability: tuple[float, ...]
    causes: tuple[dict[str, Any], ...]

    @property
    def delta_basis_points(self) -> float:
        return (self.current.availability - self.previous.availability) * 100.0


def determine_status(
    availability: float,
    target: float,
    delta_basis_points: float,
    warning_basis_points: float,
) -> str:
    if availability < target:
        return "RED"
    if delta_basis_points <= -warning_basis_points:
        return "AMBER"
    return "GREEN"


def analyze_ring(raw: dict[str, Any], warning_basis_points: float) -> RingAnalysis:
    name = required_string(raw, "name")
    target = required_number(raw, "target")
    current = parse_period(raw, "current")
    previous = parse_period(raw, "previous")
    daily = tuple(float(value) for value in raw.get("daily_availability", []))
    if not daily:
        raise ValueError(f"{name}: daily_availability must not be empty")
    if any(value < 0.0 or value > 100.0 for value in daily):
        raise ValueError(f"{name}: daily availability values must be between 0 and 100")

    causes = tuple(raw.get("causes", []))
    for cause in causes:
        required_string(cause, "api")
        required_string(cause, "error")
        count = required_integer(cause, "count")
        if count < 0:
            raise ValueError(f"{name}: cause count must not be negative")

    delta = (current.availability - previous.availability) * 100.0
    status = determine_status(
        current.availability, target, delta, warning_basis_points
    )
    return RingAnalysis(
        name=name,
        status=status,
        target=target,
        current=current,
        previous=previous,
        daily_availability=daily,
        causes=tuple(sorted(causes, key=lambda item: item["count"], reverse=True)),
    )


def parse_period(raw: dict[str, Any], key: str) -> PeriodMetrics:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return PeriodMetrics(
        requests=required_integer(value, "requests"),
        failures=required_integer(value, "failures"),
    )


def required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def required_number(raw: dict[str, Any], key: str) -> float:
    value = raw.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def required_integer(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def cause_explanation(ring: RingAnalysis) -> str:
    if not ring.causes:
        return "No categorized failures were supplied for this ring."

    total_categorized = sum(cause["count"] for cause in ring.causes)
    if total_categorized == 0:
        return "Categorized failure counts are all zero."

    primary = ring.causes[0]
    share = 100.0 * primary["count"] / total_categorized
    effect = (
        "is the most likely driver of the availability miss"
        if ring.status == "RED"
        else "is the largest observed failure category"
    )
    return (
        f"{primary['api']} — {primary['error']} {effect}, accounting for "
        f"{share:.1f}% of categorized failures."
    )


def render_sparkline(values: tuple[float, ...], target: float) -> str:
    width = 360
    height = 90
    padding = 8
    minimum = min(min(values), target) - 0.03
    maximum = max(max(values), target) + 0.03
    span = max(maximum - minimum, 0.01)

    def point(index: int, value: float) -> tuple[float, float]:
        x = padding + index * (width - 2 * padding) / max(len(values) - 1, 1)
        y = height - padding - (value - minimum) * (height - 2 * padding) / span
        return x, y

    points = " ".join(
        f"{x:.1f},{y:.1f}" for x, y in (point(i, value) for i, value in enumerate(values))
    )
    _, target_y = point(0, target)
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Daily availability trend">'
        f'<line x1="{padding}" y1="{target_y:.1f}" x2="{width-padding}" '
        f'y2="{target_y:.1f}" class="target-line"/>'
        f'<polyline points="{points}" class="trend-line"/>'
        "</svg>"
    )


def render_cause_rows(ring: RingAnalysis) -> str:
    if not ring.causes:
        return '<tr><td colspan="5">No categorized failures supplied.</td></tr>'

    total = sum(cause["count"] for cause in ring.causes)
    rows = []
    for cause in ring.causes[:5]:
        share = 100.0 * cause["count"] / total if total else 0.0
        rows.append(
            "<tr>"
            f"<td>{html.escape(cause['api'])}</td>"
            f"<td>{html.escape(cause['error'])}</td>"
            f"<td>{html.escape(str(cause.get('status_code', '—')))}</td>"
            f"<td>{cause['count']:,}</td>"
            f"<td>{share:.1f}%</td>"
            "</tr>"
        )
    return "".join(rows)


def render_report(payload: dict[str, Any]) -> str:
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("report must be an object")

    title = required_string(report, "title")
    current_label = required_string(report, "current_period")
    previous_label = required_string(report, "previous_period")
    dashboard_url = required_string(report, "dashboard_url")
    warning_basis_points = required_number(report, "warning_basis_points")
    rings_raw = payload.get("rings")
    if not isinstance(rings_raw, list) or not rings_raw:
        raise ValueError("rings must be a non-empty array")

    rings = tuple(analyze_ring(ring, warning_basis_points) for ring in rings_raw)
    overall_status = (
        "RED"
        if any(ring.status == "RED" for ring in rings)
        else "AMBER"
        if any(ring.status == "AMBER" for ring in rings)
        else "GREEN"
    )
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    summary_rows = "".join(
        "<tr>"
        f'<td><span class="status {ring.status.lower()}">{ring.status}</span></td>'
        f"<td>{html.escape(ring.name)}</td>"
        f"<td>{ring.current.availability:.4f}%</td>"
        f"<td>{ring.target:.4f}%</td>"
        f"<td>{ring.previous.availability:.4f}%</td>"
        f"<td>{ring.delta_basis_points:+.1f} bp</td>"
        f"<td>{ring.current.failures:,}</td>"
        "</tr>"
        for ring in rings
    )

    ring_sections = "".join(
        f"""
        <section class="ring-card">
          <div class="ring-heading">
            <div>
              <span class="status {ring.status.lower()}">{ring.status}</span>
              <h2>{html.escape(ring.name)}</h2>
            </div>
            <div class="metric">{ring.current.availability:.4f}%</div>
          </div>
          <p class="explanation">{html.escape(cause_explanation(ring))}</p>
          {render_sparkline(ring.daily_availability, ring.target)}
          <p class="chart-note">Daily availability; dashed line is the {ring.target:.4f}% target.</p>
          <table>
            <thead><tr><th>API</th><th>Error</th><th>Status</th><th>Count</th><th>Share</th></tr></thead>
            <tbody>{render_cause_rows(ring)}</tbody>
          </table>
        </section>
        """
        for ring in rings
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: "Segoe UI", Arial, sans-serif; }}
    body {{ margin: 0; background: #f4f6f8; color: #1f2937; }}
    main {{ max-width: 1180px; margin: auto; padding: 28px; }}
    header, .ring-card {{ background: white; border: 1px solid #dbe1e8; border-radius: 10px; }}
    header {{ padding: 24px; margin-bottom: 20px; }}
    h1 {{ margin: 8px 0; font-size: 28px; }}
    h2 {{ display: inline; margin-left: 8px; font-size: 20px; }}
    .meta, .chart-note {{ color: #64748b; font-size: 13px; }}
    .overall {{ display: flex; align-items: center; gap: 12px; }}
    .status {{ border-radius: 999px; color: white; display: inline-block; font-weight: 700;
      font-size: 12px; padding: 4px 9px; }}
    .red {{ background: #c62828; }} .amber {{ background: #b26a00; }} .green {{ background: #147d3f; }}
    table {{ width: 100%; border-collapse: collapse; background: white; margin: 18px 0; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
    th {{ background: #eef2f6; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 18px; }}
    .ring-card {{ padding: 20px; overflow: hidden; }}
    .ring-heading {{ display: flex; align-items: center; justify-content: space-between; }}
    .metric {{ font-size: 25px; font-weight: 700; }}
    .explanation {{ min-height: 45px; line-height: 1.45; }}
    .sparkline {{ display: block; width: 100%; height: 105px; background: #fafafa; }}
    .trend-line {{ fill: none; stroke: #2563eb; stroke-width: 3; }}
    .target-line {{ stroke: #c62828; stroke-width: 1.5; stroke-dasharray: 6 4; }}
    a {{ color: #075ea8; }}
    @media (max-width: 600px) {{ main {{ padding: 12px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="overall"><span class="status {overall_status.lower()}">{overall_status}</span>
      <h1>{html.escape(title)}</h1></div>
    <p>{html.escape(current_label)} compared with {html.escape(previous_label)}</p>
    <p class="meta">Generated {html.escape(generated_at)} ·
      <a href="{html.escape(dashboard_url, quote=True)}">Open Jarvis availability dashboard</a></p>
  </header>
  <section>
    <h2>Ring summary</h2>
    <table>
      <thead><tr><th>Status</th><th>Ring</th><th>Availability</th><th>Target</th>
        <th>Previous</th><th>Change</th><th>Failures</th></tr></thead>
      <tbody>{summary_rows}</tbody>
    </table>
  </section>
  <div class="grid">{ring_sections}</div>
</main>
</body>
</html>
"""


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("input root must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("sample-data.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("output/availability-report.html")
    )
    args = parser.parse_args()

    report_html = render_report(load_payload(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report_html, encoding="utf-8")
    print(f"Generated {args.output.resolve()}")


if __name__ == "__main__":
    main()
