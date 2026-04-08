"""Pull all distinct Service_Types values from CRM deals."""
import sys, os, requests
from pathlib import Path
from collections import Counter
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
headers = {"Authorization": f"Zoho-oauthtoken {token}"}

counts = Counter()
offset = 0
while True:
    query = (
        f"select Service_Types from Deals "
        f"where Closing_Date between '2025-01-01' and '2025-12-31' "
        f"and Service_Types is not null "
        f"limit 200 offset {offset}"
    )
    r = requests.post(f"{base}/coql", json={"select_query": query}, headers=headers, timeout=30)
    if r.status_code >= 400:
        print(f"Error at offset {offset}: {r.status_code} {r.text[:200]}")
        break
    data = r.json().get("data", [])
    for d in data:
        val = d.get("Service_Types", "")
        if val:
            counts[val] += 1
    print(f"  offset={offset}, page={len(data)}, unique so far={len(counts)}")
    if len(data) < 200:
        break
    offset += 200

print(f"\n{'='*60}")
print(f"Total distinct Service_Types values: {len(counts)}")
print(f"{'='*60}\n")
for val, cnt in counts.most_common():
    print(f"  {cnt:5d}  {val}")
