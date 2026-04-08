"""Run the full enrichment pipeline on a single deal (LIVE)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import load_config
from src.core.zoho_auth import ZohoAuthManager
from src.core.claude_client import ClaudeClient
from src.core.metrics import MetricsCollector
from src.modules.renewal_backfill.crm_queries import CRMQueries
from src.modules.renewal_backfill.attachment_handler import pick_registration_attachment, detect_media_type, is_image, is_pdf
from src.modules.renewal_backfill.ocr_processor import ocr_registration_card
from src.modules.renewal_backfill import vin_decoder
from src.modules.renewal_backfill.deal_enricher import DealEnricher

DEAL_ID = "3945403000073907086"

config = load_config()
zoho = ZohoAuthManager(
    client_id=config.zoho.client_id,
    client_secret=config.zoho.client_secret,
    refresh_token=config.zoho.refresh_token,
    accounts_domain=config.zoho.accounts_domain,
    api_domain=config.zoho.api_domain,
)
metrics = MetricsCollector(data_dir=config.project_root / "data")
claude = ClaudeClient(api_key=config.anthropic_api_key, metrics_collector=metrics)
crm = CRMQueries(zoho, config.zoho.api_domain, config.crm_fields)
enricher = DealEnricher(crm, config.crm_fields, vehicle_fields_exist=True)
f = config.crm_fields

# 1. Fetch deal
print(f"Fetching deal {DEAL_ID}...")
base = config.zoho.api_domain.rstrip("/") + "/crm/v8"
resp = zoho.make_request("GET", f"{base}/Deals/{DEAL_ID}")
resp.raise_for_status()
deal = resp.json().get("data", [{}])[0]
deal_name = deal.get("Deal_Name", "")
vin = deal.get(f.vin, "")
print(f"  Deal: {deal_name}")
print(f"  VIN: {vin}")
print(f"  Current Expiration: {deal.get(f.expiration_date, '(empty)')}")
print(f"  Current YMM: {deal.get(f.vehicle_ymm, '(empty)')}")

# 2. Get attachments
print("\nListing attachments...")
attachments = crm.list_attachments(DEAL_ID)
print(f"  Found {len(attachments)} attachments")
for a in attachments:
    print(f"    - {a.get('File_Name')}")

reg_att = pick_registration_attachment(attachments)
if not reg_att:
    print("  ERROR: No suitable attachment found!")
    sys.exit(1)
print(f"  Selected: {reg_att.get('File_Name')}")

# 3. Download & OCR
att_id = reg_att.get("id", "")
filename = reg_att.get("File_Name", "unknown")
print(f"\nDownloading {filename}...")
file_bytes, content_type = crm.download_attachment(DEAL_ID, att_id)
media_type = detect_media_type(filename, content_type)
print(f"  Size: {len(file_bytes)} bytes, type: {media_type}")

print("Running OCR with Claude...")
ocr_result = ocr_registration_card(claude, file_bytes, media_type)
if not ocr_result["success"]:
    print(f"  ERROR: OCR failed — {ocr_result.get('reason')}")
    sys.exit(1)
expiration_date = ocr_result["expiration_date"]
print(f"  Expiration date extracted: {ocr_result.get('raw_date')} -> {expiration_date}")

# 4. VIN decode
print(f"\nDecoding VIN: {vin}...")
vin_result = vin_decoder.decode_single(vin)
vehicle_info = vin_result if vin_result["success"] else None
if vehicle_info:
    print(f"  Year: {vehicle_info.get('year')}")
    print(f"  Make: {vehicle_info.get('make')}")
    print(f"  Model: {vehicle_info.get('model')}")
else:
    print(f"  VIN decode failed: {vin_result.get('error_text', '')}")

# 5. LIVE WRITE
print(f"\n*** WRITING TO CRM (LIVE) ***")
result = enricher.enrich(DEAL_ID, deal_name, expiration_date, vehicle_info, dry_run=False)
print(f"  Result: {result}")

# 6. Verify
print("\nVerifying write...")
resp2 = zoho.make_request("GET", f"{base}/Deals/{DEAL_ID}")
resp2.raise_for_status()
updated = resp2.json().get("data", [{}])[0]
print(f"  Expiration: {updated.get(f.expiration_date, '(empty)')}")
print(f"  YMM: {updated.get(f.vehicle_ymm, '(empty)')}")
print("\nDone!")
