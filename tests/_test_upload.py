"""Debug: test uploading a tiny file to Google Drive."""
import sys, json
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
headers = {"Authorization": f"Bearer {creds.token}"}

# Try creating a simple text file in the folder
metadata = {"name": "test.txt", "parents": [FOLDER_ID]}
resp = requests.post(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
    headers=headers,
    files={
        "metadata": ("metadata", json.dumps(metadata), "application/json"),
        "file": ("test.txt", b"hello world", "text/plain"),
    },
)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")

if resp.status_code == 200:
    file_id = resp.json().get("id")
    print(f"\nFile created! ID: {file_id}")
    # Clean up
    del_resp = requests.delete(f"https://www.googleapis.com/drive/v3/files/{file_id}", headers=headers)
    print(f"Cleanup: {del_resp.status_code}")
