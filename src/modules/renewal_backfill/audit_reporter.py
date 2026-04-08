"""Data quality audit report generator for the Renewal Backfill module."""

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.audit_reporter")

ISSUE_CODES = (
    "no_attachment",
    "no_reg_attachment",
    "missing_reg_file",
    "missing_dmv_paperwork",
    "ocr_failed",
    "perm_registration",
    "excluded_service_type",
    "missing_vin",
    "invalid_vin",
    "orphan_deal",
    "missing_phone",
    "missing_email",
    "duplicate_contact",
    "renewal_exists",
)


class AuditReporter:
    """Collects data-quality issues during processing and writes reports."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._issues: dict[str, list[dict]] = defaultdict(list)
        self._phones_seen: dict[str, list[str]] = defaultdict(list)

    def record_issue(
        self,
        issue_code: str,
        deal_id: str,
        deal_name: str = "",
        contact_name: str = "",
        details: str = "",
    ) -> None:
        self._issues[issue_code].append({
            "deal_id": deal_id,
            "deal_name": deal_name,
            "contact_name": contact_name,
            "issue_details": details,
        })

    def track_phone(self, phone: str, contact_id: str) -> None:
        """Track phone numbers to detect duplicate contacts."""
        if phone:
            normalized = phone.strip().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
            if normalized:
                self._phones_seen[normalized].append(contact_id)

    def flag_duplicate_contacts(self) -> None:
        """After processing, flag contacts that share a phone number."""
        for phone, contact_ids in self._phones_seen.items():
            if len(contact_ids) > 1:
                unique = list(set(contact_ids))
                if len(unique) > 1:
                    self.record_issue(
                        "duplicate_contact",
                        deal_id="",
                        details=f"Phone {phone} shared by contacts: {', '.join(unique)}",
                    )

    def generate(
        self,
        run_id: str,
        total_deals: int,
        successfully_processed: int,
    ) -> dict:
        """Generate JSON and CSV audit reports. Returns the summary dict."""
        self.flag_duplicate_contacts()

        summary = {code: len(self._issues.get(code, [])) for code in ISSUE_CODES}
        run_date = datetime.now(timezone.utc).isoformat()

        report = {
            "run_id": run_id,
            "run_date": run_date,
            "total_deals_scanned": total_deals,
            "successfully_processed": successfully_processed,
            "issues": dict(self._issues),
            "summary": summary,
        }

        json_path = self.data_dir / f"audit_report_{run_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Audit report (JSON) written to %s", json_path)

        csv_path = self.data_dir / f"audit_report_{run_id}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["deal_id", "deal_name", "contact_name", "issue_code", "issue_details", "deal_url"])
            for code, items in self._issues.items():
                for item in items:
                    deal_id = item.get("deal_id", "")
                    deal_url = f"https://crm.zoho.com/crm/org*/tab/Potentials/{deal_id}" if deal_id else ""
                    writer.writerow([
                        deal_id,
                        item.get("deal_name", ""),
                        item.get("contact_name", ""),
                        code,
                        item.get("issue_details", ""),
                        deal_url,
                    ])
        logger.info("Audit report (CSV) written to %s", csv_path)

        return summary
