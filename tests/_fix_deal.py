"""Fix the incorrect expiration date on the test deal."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import load_config
from src.core.zoho_auth import ZohoAuthManager

DEAL_ID = "3945403000073907086"
CORRECT_EXPIRATION = "2025-11-30"

config = load_config()
zoho = ZohoAuthManager(
    client_id=config.zoho.client_id,
    client_secret=config.zoho.client_secret,
    refresh_token=config.zoho.refresh_token,
    accounts_domain=config.zoho.accounts_domain,
    api_domain=config.zoho.api_domain,
)

base = config.zoho.api_domain.rstrip("/") + "/crm/v8"
payload = {"data": [{"id": DEAL_ID, config.crm_fields.expiration_date: CORRECT_EXPIRATION}]}
resp = zoho.make_request("PUT", f"{base}/Deals/{DEAL_ID}", json=payload)
resp.raise_for_status()
print(f"Updated deal {DEAL_ID}: Reg_Expiration = {CORRECT_EXPIRATION}")
print(f"Response: {resp.json()}")
