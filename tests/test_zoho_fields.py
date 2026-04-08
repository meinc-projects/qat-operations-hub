"""Validate that required CRM field API names exist in the Deals module.

Usage::

    python tests/test_zoho_fields.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config
from src.core.zoho_auth import ZohoAuthManager


def main() -> None:
    config = load_config()

    zoho = ZohoAuthManager(
        client_id=config.zoho.client_id,
        client_secret=config.zoho.client_secret,
        refresh_token=config.zoho.refresh_token,
        accounts_domain=config.zoho.accounts_domain,
        api_domain=config.zoho.api_domain,
    )

    base = config.zoho.api_domain.rstrip("/") + "/crm/v8"
    resp = zoho.make_request("GET", f"{base}/settings/fields", params={"module": "Deals"})
    resp.raise_for_status()
    all_fields = resp.json().get("fields", [])
    api_names = {f.get("api_name") for f in all_fields}

    fields = config.crm_fields
    required = {
        "Expiration_Date": fields.expiration_date,
        "VIN": fields.vin,
        "Stage": fields.stage,
        "Contact_Name": fields.contact,
        "Closing_Date": fields.closing_date,
    }
    optional = {
        "Amount": fields.amount,
        "Vehicle_YMM": fields.vehicle_ymm,
    }

    errors = 0
    for label, api_name in required.items():
        if api_name in api_names:
            print(f"[OK]   {label} → {api_name}")
        else:
            print(f"[FAIL] {label} → {api_name} NOT FOUND")
            errors += 1

    for label, api_name in optional.items():
        if api_name in api_names:
            print(f"[OK]   {label} → {api_name}")
        else:
            print(f"[WARN] {label} → {api_name} not found (optional)")

    if errors:
        print(f"\n{errors} required field(s) missing. Listing all Deals fields:")
        for f in sorted(all_fields, key=lambda x: x.get("api_name", "")):
            print(f"  {f.get('api_name')} ({f.get('display_label')})")
        sys.exit(1)
    else:
        print("\nAll required fields found.")


if __name__ == "__main__":
    main()
