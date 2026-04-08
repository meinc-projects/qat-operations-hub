"""Quick one-off: list all Deals fields in Zoho CRM."""
import sys, os, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

url = os.getenv("ZOHO_CRM_ACCOUNTS_DOMAIN", "https://accounts.zoho.com") + "/oauth/v2/token"
resp = requests.post(url, params={
    "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN"),
    "client_id": os.getenv("ZOHO_CLIENT_ID"),
    "client_secret": os.getenv("ZOHO_CLIENT_SECRET"),
    "grant_type": "refresh_token",
}, timeout=30)
print("Token status:", resp.status_code)
if resp.status_code >= 400:
    print("Error:", resp.text[:500])
    sys.exit(1)
token = resp.json().get("access_token", "")

base = os.getenv("ZOHO_CRM_API_DOMAIN", "https://www.zohoapis.com").rstrip("/") + "/crm/v8"
resp2 = requests.get(
    f"{base}/settings/fields",
    params={"module": "Deals"},
    headers={"Authorization": f"Zoho-oauthtoken {token}"},
    timeout=30,
)
resp2.raise_for_status()
fields = resp2.json().get("fields", [])
for f in sorted(fields, key=lambda x: x.get("api_name", "")):
    api = f.get("api_name", "")
    label = f.get("display_label", "")
    dtype = f.get("data_type", "")
    print(f"  {api}  ({label})  [{dtype}]")
print(f"\nTotal: {len(fields)} fields")
