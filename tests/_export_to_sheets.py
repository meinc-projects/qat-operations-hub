"""Export an existing audit report JSON to Google Sheets.

Usage:
    python tests/_export_to_sheets.py [data/audit_report_XXXXX.json]

First run opens a browser for Google sign-in.
Subsequent runs are fully automated.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import load_config
from src.core.google_sheets import SheetsExporter

if len(sys.argv) < 2:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    reports = sorted(data_dir.glob("audit_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("No audit reports found. Run the module first.")
        sys.exit(1)
    report_path = reports[0]
    print(f"Using most recent report: {report_path.name}")
else:
    report_path = Path(sys.argv[1])

config = load_config()
oauth_path = config.project_root / os.getenv("GOOGLE_OAUTH_CREDENTIALS", "oauth_credentials.json")
folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

if not oauth_path.exists():
    print(f"OAuth credentials not found: {oauth_path}")
    print("Download from Google Cloud Console > Credentials > OAuth 2.0 Client IDs")
    sys.exit(1)

exporter = SheetsExporter(oauth_path, folder_id=folder_id)
url = exporter.export_audit_report(report_path)
print(f"\nGoogle Sheet created: {url}")
