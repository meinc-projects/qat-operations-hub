"""Quick check: list attachment filenames for the skipped deals."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import load_config
from src.core.zoho_auth import ZohoAuthManager

config = load_config()
zoho = ZohoAuthManager(
    client_id=config.zoho.client_id,
    client_secret=config.zoho.client_secret,
    refresh_token=config.zoho.refresh_token,
    accounts_domain=config.zoho.accounts_domain,
    api_domain=config.zoho.api_domain,
)

base_v2 = config.zoho.api_domain.rstrip("/") + "/crm/v2"

skipped_ids = [
    "3945403000073911266",
    "3945403000073914383",
    "3945403000073916353",
    "3945403000073919430",
    "3945403000073920344",
    "3945403000073921434",
    "3945403000073921485",
    "3945403000073922163",
    "3945403000073927164",
]

for deal_id in skipped_ids:
    resp = zoho.make_request("GET", f"{base_v2}/Deals/{deal_id}/Attachments")
    if resp.status_code == 204:
        print(f"Deal {deal_id}: NO ATTACHMENTS")
        continue
    atts = resp.json().get("data", [])
    names = [a.get("File_Name", "?") for a in atts]
    print(f"Deal {deal_id}: {names}")
