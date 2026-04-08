"""List all picklist values for the Service_Types field."""
import sys, os, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

url = os.getenv("ZOHO_CRM_ACCOUNTS_DOMAIN") + "/oauth/v2/token"
resp = requests.post(url, params={
    "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN"),
    "client_id": os.getenv("ZOHO_CLIENT_ID"),
    "client_secret": os.getenv("ZOHO_CLIENT_SECRET"),
    "grant_type": "refresh_token",
}, timeout=30)
token = resp.json().get("access_token", "")

base = os.getenv("ZOHO_CRM_API_DOMAIN").rstrip("/") + "/crm/v8"
resp2 = requests.get(
    f"{base}/settings/fields", params={"module": "Deals"},
    headers={"Authorization": f"Zoho-oauthtoken {token}"}, timeout=30,
)
fields = resp2.json().get("fields", [])
for f in fields:
    if f.get("api_name") == "Service_Types":
        print(f"Field: {f.get('api_name')} | {f.get('display_label')}")
        print(f"Data type: {f.get('data_type')}")
        for pv in f.get("pick_list_values", []):
            dv = pv.get("display_value", "")
            av = pv.get("actual_value", "")
            print(f"  - {dv}  (actual: {av})")
        break
