import sys
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_report import (  # noqa: E402
    PeriodMetrics,
    analyze_ring,
    cause_explanation,
    determine_status,
    render_report,
)
from generate_admin_api_report import (  # noqa: E402
    build_report_data,
    is_success_status,
    render as render_admin_report,
)
from ado_bug_server import (  # noqa: E402
    RequestValidationError,
    build_description,
    build_patch,
    create_bug,
    current_iteration_path,
    validate_bug_request,
)


class AvailabilityReportTests(unittest.TestCase):
    def test_period_availability(self):
        metrics = PeriodMetrics(requests=10_000, failures=10)
        self.assertAlmostEqual(99.9, metrics.availability)

    def test_status_is_red_below_target(self):
        self.assertEqual("RED", determine_status(99.89, 99.9, -1.0, 5.0))

    def test_status_is_amber_for_large_regression(self):
        self.assertEqual("AMBER", determine_status(99.95, 99.9, -8.0, 5.0))

    def test_primary_cause_is_ranked_and_explained(self):
        ring = analyze_ring(
            {
                "name": "WW",
                "target": 99.9,
                "current": {"requests": 10000, "failures": 20},
                "previous": {"requests": 10000, "failures": 5},
                "daily_availability": [99.8, 99.9],
                "causes": [
                    {"api": "B", "error": "secondary", "count": 5},
                    {"api": "A", "error": "primary", "count": 15},
                ],
            },
            warning_basis_points=5.0,
        )
        self.assertEqual("A", ring.causes[0]["api"])
        self.assertIn("75.0%", cause_explanation(ring))

    def test_report_contains_ring_and_dashboard_link(self):
        payload = {
            "report": {
                "title": "Availability",
                "current_period": "current",
                "previous_period": "previous",
                "dashboard_url": "https://example.test/dashboard",
                "warning_basis_points": 5,
            },
            "rings": [
                {
                    "name": "MSIT",
                    "target": 99.9,
                    "current": {"requests": 1000, "failures": 0},
                    "previous": {"requests": 1000, "failures": 0},
                    "daily_availability": [100, 100],
                    "causes": [],
                }
            ],
        }
        output = render_report(payload)
        self.assertIn("MSIT", output)
        self.assertIn("https://example.test/dashboard", output)
        self.assertIn("GREEN", output)

    def test_admin_api_page_contains_all_rings_and_source_link(self):
        page = (
            Path(__file__).resolve().parents[1] / "admin-api-availability.html"
        ).read_text(encoding="utf-8")
        self.assertIn("ESS – Admin API Availability", page)
        self.assertIn("ESSAdminApiAvailability", page)
        for ring in ("SDFV2", "MSIT", "SIP", "WW"):
            self.assertIn(f'name: "{ring}"', page)

    def test_admin_success_status_rule(self):
        for status in (
            "200", "201", "202", "400", "401", "403", "404",
            "408", "409", "410", "412", "422", "423", "429",
        ):
            self.assertTrue(is_success_status(status))
        for status in ("500", "503", "504"):
            self.assertFalse(is_success_status(status))

    def test_live_admin_report_uses_geneva_volumes(self):
        payload = {
            "source": {
                "account": "M365_ESS",
                "namespace": "ESSAvailabilityR9",
                "metric": "RequestAvailability",
            },
            "rows": [
                {
                    "timestamp_utc": "2026-08-24T08:00:00+00:00",
                    "deployring": "SDFV2",
                    "scenario": "DeleteStamp",
                    "statuscode": "202",
                    "totalcount": 990,
                },
                {
                    "timestamp_utc": "2026-08-24T08:00:00+00:00",
                    "deployring": "SDFV2",
                    "scenario": "DeleteStamp",
                    "statuscode": "500",
                    "totalcount": 10,
                },
            ],
        }
        report = build_report_data(payload)
        sdfv2 = next(ring for ring in report["rings"] if ring["name"] == "SDFV2")
        self.assertEqual([99.0], sdfv2["rows"]["DeleteStamp"])
        detail = sdfv2["details"]["DeleteStamp"][0]
        self.assertEqual("2026-08-24", detail["date"])
        self.assertEqual(10, detail["unsuccessful"])
        self.assertEqual("500", detail["topStatus"])
        template = (
            Path(__file__).resolve().parents[1] / "admin-api-availability.html"
        ).read_text(encoding="utf-8")
        output = render_admin_report(template, report)
        self.assertIn("Live Geneva: M365_ESS", output)
        self.assertIn("99.0", output)
        self.assertIn("Create Azure DevOps bug", output)

    def test_admin_lowlights_use_distinct_apis(self):
        rows = []
        for day, scenario, success, failed in (
            ("2026-08-16T16:00:00+00:00", "ApiA", 80, 20),
            ("2026-08-17T16:00:00+00:00", "ApiA", 70, 30),
            ("2026-08-16T16:00:00+00:00", "ApiB", 90, 10),
            ("2026-08-16T16:00:00+00:00", "ApiC", 95, 5),
        ):
            rows.extend(
                [
                    {
                        "timestamp_utc": day,
                        "deployring": "SDFV2",
                        "scenario": scenario,
                        "statuscode": "200",
                        "totalcount": success * 2,
                    },
                    {
                        "timestamp_utc": day,
                        "deployring": "SDFV2",
                        "scenario": scenario,
                        "statuscode": "500",
                        "totalcount": failed * 2,
                    },
                ]
            )
        report = build_report_data(
            {
                "source": {
                    "account": "M365_ESS",
                    "namespace": "ESSAvailabilityR9",
                    "metric": "RequestAvailability",
                },
                "rows": rows,
            }
        )
        titles = [item["title"] for item in report["lowlights"]]
        self.assertEqual(3, len(titles))
        self.assertEqual(3, len(set(titles)))

    def test_bug_request_requires_explicit_confirmation(self):
        payload = self.valid_bug_request()
        payload["confirmed"] = False
        with self.assertRaises(RequestValidationError):
            validate_bug_request(payload)

    def test_bug_patch_uses_team_defaults_and_escapes_notes(self):
        data = validate_bug_request(self.valid_bug_request())
        description = build_description(data)
        self.assertIn("&lt;script&gt;", description)
        self.assertNotIn("<script>", description)

        patch_document = build_patch(data, "engineer@example.com")
        fields = {operation["path"]: operation["value"] for operation in patch_document}
        self.assertEqual(r"O365 Core\ESS", fields["/fields/System.AreaPath"])
        self.assertEqual(2, fields["/fields/Microsoft.VSTS.Common.Priority"])
        self.assertEqual(
            "Programming Model; WSR", fields["/fields/System.Tags"]
        )
        self.assertTrue(
            fields["/fields/System.IterationPath"].startswith(
                r"O365 Core\Monthly\CY"
            )
        )
        self.assertEqual(
            "engineer@example.com", fields["/fields/System.AssignedTo"]
        )

    def test_current_iteration_uses_calendar_month_and_quarter(self):
        self.assertEqual(
            r"O365 Core\Monthly\CY26-Q3\CY26-08",
            current_iteration_path(datetime(2026, 8, 31)),
        )
        self.assertEqual(
            r"O365 Core\Monthly\CY27-Q1\CY27-01",
            current_iteration_path(datetime(2027, 1, 1)),
        )

    @patch("ado_bug_server.get_signed_in_user", return_value="engineer@example.com")
    @patch("ado_bug_server.get_ado_token", return_value="not-a-real-token")
    @patch("ado_bug_server.urllib.request.urlopen")
    def test_bug_creation_posts_json_patch(
        self, mock_urlopen, _mock_token, _mock_user
    ):
        response = BytesIO(
            b'{"id":7663000,"fields":{"System.Title":"Generated bug"}}'
        )
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        mock_urlopen.return_value = response

        result = create_bug(validate_bug_request(self.valid_bug_request()))

        self.assertEqual(7663000, result["id"])
        request = mock_urlopen.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertEqual(
            "application/json-patch+json",
            request.headers["Content-type"],
        )
        self.assertEqual(
            "Bearer not-a-real-token",
            request.headers["Authorization"],
        )
        self.assertNotIn("not-a-real-token", result["url"])

    @staticmethod
    def valid_bug_request():
        return {
            "title": "ESS - DeleteStamp availability low",
            "notes": "Investigate <script>alert(1)</script>",
            "scenario": "DeleteStamp",
            "date": "2026-08-24",
            "ring": "SDFV2",
            "availability": 97.5,
            "total": 1000,
            "unsuccessful": 25,
            "topStatus": "500",
            "severity": "3 - Medium",
            "assignToMe": True,
            "confirmed": True,
        }


if __name__ == "__main__":
    unittest.main()
