"""Quick COQL syntax debugger."""
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
base = config.zoho.api_domain.rstrip("/") + "/crm/v8"

queries = [
    # Two conditions: Stage + is null
    "select id from Deals where Stage = 'Closed Won' and Reg_Expiration is null limit 3",
    # Two conditions: date range + is null
    "select id from Deals where Closing_Date between '2025-01-01' and '2025-12-31' and Reg_Expiration is null limit 3",
    # Two conditions: Stage + date range (known working)
    "select id from Deals where Stage = 'Closed Won' and Closing_Date between '2025-01-01' and '2025-12-31' limit 3",
    # Three with >= <= instead of between
    "select id from Deals where Stage = 'Closed Won' and Closing_Date >= '2025-01-01' and Reg_Expiration is null limit 3",
]

for i, q in enumerate(queries, 1):
    resp = zoho.make_request("POST", f"{base}/coql", json={"select_query": q})
    if resp.status_code == 200:
        count = len(resp.json().get("data", []))
        print(f"[PASS] Test {i}: {count} results")
    else:
        err = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
        print(f"[FAIL] Test {i}: {resp.status_code} — {err}")
    print(f"       Query: {q}\n")
