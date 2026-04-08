"""Google Sheets integration for exporting audit reports.

Uses OAuth 2.0 Desktop flow so files are created under the user's own
Google account (no Workspace or service account quota needed).

First run opens a browser for consent; the refresh token is persisted
to google_token.json so subsequent runs are fully automated.
"""

import json
from pathlib import Path
from typing import Any

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.core.logger import get_logger

logger = get_logger("hub.core.google_sheets")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_credentials(oauth_creds_path: Path, token_path: Path) -> Credentials:
    """Load or create OAuth 2.0 credentials with persistent token storage."""
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google OAuth token")
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    logger.info("No valid token found — launching browser for Google sign-in")
    flow = InstalledAppFlow.from_client_secrets_file(str(oauth_creds_path), _SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Google OAuth token saved to %s", token_path)
    return creds


class SheetsExporter:
    def __init__(self, oauth_creds_path: str | Path, folder_id: str = "",
                 token_path: str | Path | None = None) -> None:
        self.folder_id = folder_id
        oauth_creds_path = Path(oauth_creds_path)

        if token_path is None:
            token_path = oauth_creds_path.parent / "google_token.json"
        else:
            token_path = Path(token_path)

        creds = _load_credentials(oauth_creds_path, token_path)
        self.gc = gspread.authorize(creds)
        logger.info("Google Sheets client authorized via OAuth")

    def export_audit_report(
        self,
        audit_json_path: str | Path,
        run_summary: dict | None = None,
    ) -> str:
        """Create a Google Sheet from an audit report JSON file.

        Returns the URL of the created spreadsheet.
        """
        with open(audit_json_path, "r", encoding="utf-8") as f:
            report = json.load(f)

        run_id = report.get("run_id", "unknown")[:8]
        run_date = report.get("run_date", "")[:10]
        title = f"QAT Audit Report — {run_date} ({run_id})"

        sh = self.gc.create(title)
        logger.info("Created Google Sheet: %s", sh.url)

        if self.folder_id:
            self.gc.http_client.request(
                "patch",
                f"https://www.googleapis.com/drive/v3/files/{sh.id}?addParents={self.folder_id}&removeParents=root",
            )
            logger.info("Moved sheet to folder %s", self.folder_id)

        summary = report.get("summary", {})
        issues = report.get("issues", {})
        total = report.get("total_deals_scanned", 0)
        succeeded = report.get("successfully_processed", 0)
        pct = lambda v: f"{v / max(total, 1) * 100:.0f}%"

        # --- Sheet 1: Summary ---
        ws = sh.sheet1
        ws.update_title("Summary")
        ws.update(range_name="A1", values=[
            ["QAT Operations Hub — Audit Report"],
            [],
            ["Run Date", run_date],
            ["Run ID", report.get("run_id", "")],
            ["Total Deals Scanned", total],
            ["Successfully Processed", succeeded],
            ["Failed / Skipped", total - succeeded],
            [],
            ["COMPLIANCE FLAGS", "Count", "% of Total"],
            ["Missing DMV Paperwork", summary.get("missing_dmv_paperwork", 0),
             pct(summary.get("missing_dmv_paperwork", 0))],
            ["Missing Reg/Registration File", summary.get("missing_reg_file", 0),
             pct(summary.get("missing_reg_file", 0))],
            ["No Attachments At All", summary.get("no_attachment", 0),
             pct(summary.get("no_attachment", 0))],
            [],
            ["DATA QUALITY", "Count", "% of Total"],
            ["OCR Failed", summary.get("ocr_failed", 0),
             pct(summary.get("ocr_failed", 0))],
            ["PERM Registration (manual)", summary.get("perm_registration", 0),
             pct(summary.get("perm_registration", 0))],
            ["Invalid VIN", summary.get("invalid_vin", 0),
             pct(summary.get("invalid_vin", 0))],
            ["Orphan Deal (no contact/account)", summary.get("orphan_deal", 0),
             pct(summary.get("orphan_deal", 0))],
            ["Missing Email", summary.get("missing_email", 0),
             pct(summary.get("missing_email", 0))],
            [],
            ["SERVICE TYPE", "Count", "% of Total"],
            ["Excluded Service Types", summary.get("excluded_service_type", 0),
             pct(summary.get("excluded_service_type", 0))],
        ])

        ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
        ws.format("A9:C9", {"textFormat": {"bold": True},
                             "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.92}})
        ws.format("A14:C14", {"textFormat": {"bold": True},
                              "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.92}})
        ws.format("A22:C22", {"textFormat": {"bold": True},
                              "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.92}})

        # --- Issue sheets ---
        hdrs = ["Deal ID", "Deal Name", "Contact", "Files On Record", "Follow-Up Status", "Notes"]
        self._add_issue_sheet(sh, "Missing DMV Paperwork", issues.get("missing_dmv_paperwork", []), hdrs)
        self._add_issue_sheet(sh, "Missing Reg File", issues.get("missing_reg_file", []), hdrs)
        self._add_issue_sheet(sh, "No Attachments", issues.get("no_attachment", []), hdrs)
        self._add_issue_sheet(sh, "OCR Failed", issues.get("ocr_failed", []),
                              ["Deal ID", "Deal Name", "Contact", "Error Details", "Follow-Up Status", "Notes"])
        self._add_issue_sheet(sh, "PERM Registration", issues.get("perm_registration", []),
                              ["Deal ID", "Deal Name", "Contact", "Details", "Follow-Up Status", "Notes"])
        self._add_issue_sheet(sh, "Orphan Deals", issues.get("orphan_deal", []),
                              ["Deal ID", "Deal Name", "Contact", "Details", "Follow-Up Status", "Notes"])
        self._add_issue_sheet(sh, "Excluded Service Types", issues.get("excluded_service_type", []),
                              ["Deal ID", "Deal Name", "Contact", "Service Type", "Follow-Up Status", "Notes"])

        logger.info("All sheets populated. URL: %s", sh.url)
        return sh.url

    def _add_issue_sheet(self, spreadsheet: Any, name: str, issue_list: list[dict],
                         headers: list[str]) -> None:
        num_data_rows = len(issue_list)
        ws = spreadsheet.add_worksheet(
            title=name, rows=max(num_data_rows + 2, 10), cols=len(headers),
        )
        status_col_idx = headers.index("Follow-Up Status") + 1 if "Follow-Up Status" in headers else None
        status_col_letter = chr(64 + status_col_idx) if status_col_idx else None

        rows = [headers]
        for item in issue_list:
            rows.append([
                item.get("deal_id", ""),
                item.get("deal_name", ""),
                item.get("contact_name", ""),
                item.get("issue_details", ""),
                "Not Addressed",
                "",
            ])
        ws.update(range_name="A1", values=rows)

        ws.format("A1:F1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.92},
        })

        if num_data_rows > 0 and status_col_letter:
            end_row = num_data_rows + 1
            status_range = f"{status_col_letter}2:{status_col_letter}{end_row}"

            try:
                ws.set_data_validation(
                    status_range,
                    condition_type="ONE_OF_LIST",
                    condition_values=["Not Addressed", "Fixed", "Reviewed - No Issue"],
                    strict=True,
                    input_message="Select a status",
                )
            except Exception:
                logger.debug("Data validation not supported — skipping dropdown for %s", name)

            try:
                requests_body = []
                color_rules = [
                    ("Not Addressed", {"red": 0.96, "green": 0.80, "blue": 0.80}),
                    ("Fixed", {"red": 0.80, "green": 0.94, "blue": 0.80}),
                    ("Reviewed - No Issue", {"red": 1.0, "green": 0.95, "blue": 0.70}),
                ]
                for value, bg in color_rules:
                    requests_body.append({
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [{
                                    "sheetId": ws.id,
                                    "startRowIndex": 1,
                                    "endRowIndex": end_row,
                                    "startColumnIndex": status_col_idx - 1,
                                    "endColumnIndex": status_col_idx,
                                }],
                                "booleanRule": {
                                    "condition": {
                                        "type": "TEXT_EQ",
                                        "values": [{"userEnteredValue": value}],
                                    },
                                    "format": {"backgroundColor": bg},
                                },
                            },
                            "index": 0,
                        }
                    })
                spreadsheet.batch_update({"requests": requests_body})
            except Exception:
                logger.debug("Conditional formatting not supported — skipping for %s", name)
