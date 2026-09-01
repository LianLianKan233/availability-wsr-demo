#!/usr/bin/env python3
"""Serve the WSR report and create Azure DevOps bugs after user confirmation."""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ADO_ORGANIZATION = "https://o365exchange.visualstudio.com"
ADO_PROJECT = "O365 Core"
ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"
REPORT_PATH = Path("output/admin-api-availability-live.html")
MAX_REQUEST_BYTES = 32 * 1024
MAX_TITLE_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 10_000
DASHBOARD_URL = (
    "https://portal.microsoftgeneva.com/dashboard/M365_ESS/Availability/"
    "WSR%2520Availability/ESSAdminApiAvailability"
)
LOGGER = logging.getLogger("availability_wsr")


class RequestValidationError(ValueError):
    pass


def require_string(
    payload: dict[str, Any], field: str, maximum_length: int
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"{field} is required")
    value = value.strip()
    if len(value) > maximum_length:
        raise RequestValidationError(
            f"{field} must be at most {maximum_length} characters"
        )
    return value


def validate_bug_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestValidationError("Request body must be a JSON object")
    if payload.get("confirmed") is not True:
        raise RequestValidationError("Explicit confirmation is required")

    title = require_string(payload, "title", MAX_TITLE_LENGTH)
    notes = require_string(payload, "notes", MAX_DESCRIPTION_LENGTH)
    scenario = require_string(payload, "scenario", 200)
    report_date = require_string(payload, "date", 20)
    ring = require_string(payload, "ring", 20).upper()
    if ring != "SDFV2":
        raise RequestValidationError("Only SDFV2 bug creation is enabled")

    availability = payload.get("availability")
    if not isinstance(availability, (int, float)) or isinstance(availability, bool):
        raise RequestValidationError("availability must be numeric")
    if not math.isfinite(availability) or availability < 0 or availability > 100:
        raise RequestValidationError("availability must be between 0 and 100")

    total = payload.get("total")
    unsuccessful = payload.get("unsuccessful")
    for name, value in (("total", total), ("unsuccessful", unsuccessful)):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise RequestValidationError(f"{name} must be a non-negative number")
    if unsuccessful > total:
        raise RequestValidationError("unsuccessful cannot exceed total")

    top_status = str(payload.get("topStatus", "n/a")).strip()[:20]
    severity = payload.get("severity", "3 - Medium")
    allowed_severities = {
        "1 - Critical",
        "2 - High",
        "3 - Medium",
        "4 - Low",
    }
    if severity not in allowed_severities:
        raise RequestValidationError("severity is invalid")

    return {
        "title": title,
        "notes": notes,
        "scenario": scenario,
        "date": report_date,
        "ring": ring,
        "availability": float(availability),
        "total": round(float(total)),
        "unsuccessful": round(float(unsuccessful)),
        "topStatus": top_status,
        "severity": severity,
        "assignToMe": payload.get("assignToMe") is True,
    }


def build_description(data: dict[str, Any]) -> str:
    facts = (
        f"<li><strong>Ring:</strong> {html.escape(data['ring'])}</li>"
        f"<li><strong>API:</strong> {html.escape(data['scenario'])}</li>"
        f"<li><strong>Date:</strong> {html.escape(data['date'])} (UTC+8)</li>"
        f"<li><strong>Availability:</strong> {data['availability']:.2f}%</li>"
        f"<li><strong>Total samples:</strong> {data['total']:,}</li>"
        f"<li><strong>Unsuccessful samples:</strong> "
        f"{data['unsuccessful']:,}</li>"
        f"<li><strong>Dominant unsuccessful status:</strong> HTTP "
        f"{html.escape(data['topStatus'])}</li>"
    )
    notes = html.escape(data["notes"]).replace("\n", "<br>")
    return (
        "<h3>WSR availability regression</h3>"
        f"<ul>{facts}</ul>"
        f"<p><strong>Investigation notes</strong><br>{notes}</p>"
        f'<p><a href="{DASHBOARD_URL}">Open ESS Admin API Availability '
        "dashboard</a></p>"
        "<p><em>Created from the automated Programming Model WSR report.</em></p>"
    )


def get_azure_cli_value(arguments: list[str]) -> str:
    azure_cli = (
        shutil.which("az.cmd")
        or shutil.which("az.exe")
        or shutil.which("az")
    )
    if not azure_cli:
        raise RuntimeError(
            "Azure CLI was not found. Install it or add it to PATH."
        )
    result = subprocess.run(
        [azure_cli, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "Azure CLI command failed"
        raise RuntimeError(message)
    value = result.stdout.strip()
    if not value:
        raise RuntimeError("Azure CLI returned an empty value")
    return value


def get_ado_token() -> str:
    return get_azure_cli_value(
        [
            "account",
            "get-access-token",
            "--resource",
            ADO_RESOURCE,
            "--query",
            "accessToken",
            "--output",
            "tsv",
        ]
    )


def get_signed_in_user() -> str:
    return get_azure_cli_value(
        ["account", "show", "--query", "user.name", "--output", "tsv"]
    )


def current_iteration_path(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    short_year = current.strftime("%y")
    quarter = ((current.month - 1) // 3) + 1
    return (
        rf"O365 Core\Monthly\CY{short_year}-Q{quarter}"
        rf"\CY{short_year}-{current.month:02d}"
    )


def build_patch(data: dict[str, Any], assigned_to: str | None) -> list[dict[str, Any]]:
    fields: list[tuple[str, Any]] = [
        ("System.Title", data["title"]),
        ("System.Description", build_description(data)),
        ("System.AreaPath", r"O365 Core\ESS"),
        ("System.IterationPath", current_iteration_path()),
        ("Microsoft.VSTS.Common.Priority", 2),
        ("Microsoft.VSTS.Common.Severity", data["severity"]),
        ("Microsoft.VSTS.Common.ValueArea", "Business"),
        ("Microsoft.VSTS.Common.Triage", "Not Triaged"),
        ("Office.ProductStudio.PSDatabase", "OfficeMain"),
        ("O365.Security.Impact", False),
        ("O365.Is.Exception", False),
        ("System.Tags", "Programming Model; WSR"),
    ]
    if assigned_to:
        fields.append(("System.AssignedTo", assigned_to))
    return [
        {"op": "add", "path": f"/fields/{name}", "value": value}
        for name, value in fields
    ]


def create_bug(data: dict[str, Any]) -> dict[str, Any]:
    token = get_ado_token()
    assigned_to = get_signed_in_user() if data["assignToMe"] else None
    project = urllib.parse.quote(ADO_PROJECT, safe="")
    url = (
        f"{ADO_ORGANIZATION}/{project}/_apis/wit/workitems/$Bug"
        "?api-version=7.1"
    )
    body = json.dumps(build_patch(data, assigned_to)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json-patch+json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            try:
                result = json.load(response)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    "Azure DevOps returned an invalid JSON response"
                ) from error
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            parsed_detail = json.loads(detail)
            message = (
                parsed_detail.get("message", detail)
                if isinstance(parsed_detail, dict)
                else detail
            )
        except json.JSONDecodeError:
            message = detail
        raise RuntimeError(
            f"Azure DevOps rejected the bug: {str(message)[:2000]}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach Azure DevOps: {error.reason}"
        ) from error

    bug_id = result.get("id")
    if not bug_id:
        raise RuntimeError("Azure DevOps response did not include a work item ID")
    return {
        "id": bug_id,
        "url": f"{ADO_ORGANIZATION}/{project}/_workitems/edit/{bug_id}",
        "title": result.get("fields", {}).get("System.Title", data["title"]),
    }


class ReportHandler(BaseHTTPRequestHandler):
    server_version = "AvailabilityWsrDemo/1.0"

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/report"):
            self.send_report()
            return
        if path == "/api/health":
            self.send_json(
                HTTPStatus.OK,
                {"status": "ok", "bugCreationEnabled": True},
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/api/bugs":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.is_same_origin():
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid request origin"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Content-Length must be numeric"},
            )
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self.send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "Request body is empty or too large"},
            )
            return
        if "application/json" not in self.headers.get("Content-Type", ""):
            self.send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "Content-Type must be application/json"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            data = validate_bug_request(payload)
            bug = create_bug(data)
        except (json.JSONDecodeError, RequestValidationError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except (RuntimeError, subprocess.SubprocessError) as error:
            LOGGER.warning("Bug creation failed: %s", error)
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return
        except Exception:
            LOGGER.exception("Unexpected error while creating an Azure DevOps bug")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": (
                        "The local backend encountered an unexpected error. "
                        "See output/report-server.log for details."
                    )
                },
            )
            return

        LOGGER.info("Created Azure DevOps bug %s", bug["id"])
        self.send_json(HTTPStatus.CREATED, bug)

    def is_same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        expected = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        return origin in expected

    def send_report(self) -> None:
        report_path = Path.cwd() / REPORT_PATH
        if not report_path.exists():
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "Report not found. Run refresh_admin_api_report.ps1 first."},
            )
            return
        content = report_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    log_path = Path("output/report-server.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    server = ThreadingHTTPServer((args.host, args.port), ReportHandler)
    print(f"WSR report server: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
