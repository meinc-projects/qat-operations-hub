"""Check service account Drive access and quota."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
import requests

SA_PATH = Path(__file__).resolve().parent.parent / "service_account.json"
FOLDER_ID = "1dmXUCxl1fUtuTURwvTvYp5JEz2EKPP9a"

creds = Credentials.from_service_account_file(
    str(SA_PATH),
    scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"],
)
creds.refresh(Request())
print(f"Service account email: {creds.service_account_email}")
print(f"Token obtained: OK")

headers = {"Authorization": f"Bearer {creds.token}"}

# Check quota
resp = requests.get("https://www.googleapis.com/drive/v3/about?fields=storageQuota,user", headers=headers)
if resp.status_code == 200:
    data = resp.json()
    user = data.get("user", {})
    quota = data.get("storageQuota", {})
    print(f"\nUser: {user.get('displayName', '?')} ({user.get('emailAddress', '?')})")
    limit = int(quota.get("limit", 0))
    usage = int(quota.get("usage", 0))
    print(f"Storage limit: {limit / 1e9:.2f} GB")
    print(f"Storage used:  {usage / 1e9:.2f} GB")
    print(f"Storage free:  {(limit - usage) / 1e9:.2f} GB")
else:
    print(f"About API error: {resp.status_code} — {resp.text[:300]}")

# Check folder access
print(f"\nChecking folder access ({FOLDER_ID})...")
resp2 = requests.get(f"https://www.googleapis.com/drive/v3/files/{FOLDER_ID}?fields=name,ownedByMe,capabilities", headers=headers)
if resp2.status_code == 200:
    folder = resp2.json()
    print(f"Folder: {folder.get('name')}")
    print(f"Owned by service account: {folder.get('ownedByMe', False)}")
    caps = folder.get("capabilities", {})
    print(f"Can add children: {caps.get('canAddChildren', False)}")
    print(f"Can edit: {caps.get('canEdit', False)}")
elif resp2.status_code == 404:
    print("ERROR: Folder not found or not shared with service account.")
    print(f"Share the folder with: {creds.service_account_email}")
else:
    print(f"Folder check error: {resp2.status_code} — {resp2.text[:300]}")
