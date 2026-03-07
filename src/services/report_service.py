"""Report service for PDF generation and scheduled reports."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone


class ReportService:
    """Generates CSV and text-based reports. PDF requires reportlab (optional)."""

    def generate_cost_report_csv(self, data: dict) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Report Generated", datetime.now(timezone.utc).isoformat()])
        writer.writerow([])
        writer.writerow(["Category", "Current Cost", "Potential Savings"])

        for item in data.get("items", []):
            writer.writerow([item.get("category", ""), item.get("cost", 0), item.get("savings", 0)])

        writer.writerow([])
        writer.writerow(["Total", data.get("total_cost", 0), data.get("total_savings", 0)])
        return output.getvalue()

    def generate_compliance_report_csv(self, frameworks: list[dict]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Framework", "Version", "Score", "Passed", "Failed"])

        for fw in frameworks:
            writer.writerow([
                fw.get("framework", ""), fw.get("version", ""),
                fw.get("score", 0), fw.get("passed", 0), fw.get("failed", 0),
            ])

        return output.getvalue()

    def generate_security_report_csv(self, alerts: list[dict]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Severity", "Category", "Title", "Status", "Resource", "Detected At"])

        for alert in alerts:
            writer.writerow([
                alert.get("severity", ""), alert.get("category", ""),
                alert.get("title", ""), alert.get("status", ""),
                alert.get("resource_id", ""), alert.get("detected_at", ""),
            ])

        return output.getvalue()
