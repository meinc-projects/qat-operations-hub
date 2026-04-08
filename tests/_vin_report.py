"""Quick report: list VINs for the first 25 target deals."""
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
f = config.crm_fields

all_deals = []
offset = 0
while True:
    query = (
        f"select id, Deal_Name, {f.vin}, {f.closing_date}, {f.expiration_date} "
        f"from Deals "
        f"where {f.closing_date} between '2025-01-01' and '2025-01-31' "
        f"and {f.expiration_date} is null "
        f"limit 200 offset {offset}"
    )
    resp = zoho.make_request("POST", f"{base}/coql", json={"select_query": query})
    resp.raise_for_status()
    page = resp.json().get("data", [])
    all_deals.extend(page)
    if len(page) < 200:
        break
    offset += 200

deals = all_deals[:25]
print(f"{'#':<4} {'Deal Name':<55} {'VIN':<20} {'Closing Date'}")
print("-" * 110)
for i, d in enumerate(deals, 1):
    name = d.get("Deal_Name", "")[:53]
    vin = d.get(f.vin) or "(empty)"
    closing = d.get(f.closing_date, "")
    print(f"{i:<4} {name:<55} {vin:<20} {closing}")

has_vin = sum(1 for d in deals if d.get(f.vin))
no_vin = len(deals) - has_vin
print(f"\nTotal: {len(deals)} deals  |  With VIN: {has_vin}  |  No VIN: {no_vin}")
print(f"(Out of {len(all_deals)} total deals matching query)")
