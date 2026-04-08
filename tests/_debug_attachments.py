"""Debug: test attachment endpoint with a single deal."""
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

deal_id = "3945403000073903263"

for version in ["v8", "v7", "v6", "v5", "v2"]:
    base = config.zoho.api_domain.rstrip("/") + f"/crm/{version}"
    url = f"{base}/Deals/{deal_id}/Attachments"
    print(f"\nTrying {version}: {url}")
    resp = zoho.make_request("GET", url)
    print(f"  Status: {resp.status_code}")
    print(f"  Body: {resp.text[:500]}")
    if resp.status_code in (200, 204):
        print("  >>> WORKS!")
        break
