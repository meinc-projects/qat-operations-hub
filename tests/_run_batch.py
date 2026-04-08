"""Run the full enrichment pipeline LIVE on specific deals from the dry run."""
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

# 10 deals that succeeded in the dry run (excluding the one we already did)
DEAL_IDS = [
    "3945403000073903263",  # Title Transfer - AVRS - 3N1CN7AP2CL898758
    "3945403000073907135",  # AZ Bus Transfer - 1BAKGCPA1EF296813
    "3945403000073907188",  # Fleetflo (AVRS) - 3C7WRMFL8LG175205
    "3945403000073909188",  # AZ Bus Transfer - 1GB6G5BGXB1163270
    "3945403000073911336",  # AZ Bus Transfer - 1BAKGCPA2DF293580
    "3945403000073913277",  # CARB Account Creation - JHHKDM2H9KK001367
    "3945403000073917111",  # Reg Renewal - AVRS - 2C3CDXGJ5LH188656
    "3945403000073919328",  # Fleetflo (AVRS) - JALC4W165F7001926
    "3945403000073919379",  # Fleetflo (AVRS) - 1FTEW1EP7MKD08387
    "3945403000073920291",  # AZ Bus Transfer - 1GB3G3BG9F1168358
]

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
base = config.zoho.api_domain.rstrip("/") + "/crm/v8"

results = []

for i, deal_id in enumerate(DEAL_IDS, 1):
    print(f"\n{'='*70}")
    print(f"Deal {i}/10: {deal_id}")

    try:
        # Fetch deal
        resp = zoho.make_request("GET", f"{base}/Deals/{deal_id}")
        resp.raise_for_status()
        deal = resp.json().get("data", [{}])[0]
        deal_name = deal.get("Deal_Name", "")
        vin = deal.get(f.vin, "") or ""
        print(f"  Name: {deal_name}")
        print(f"  VIN: {vin}")

        # Attachments
        attachments = crm.list_attachments(deal_id)
        reg_att = pick_registration_attachment(attachments)
        if not reg_att:
            print(f"  SKIP: No suitable attachment")
            results.append({"deal": deal_name, "vin": vin, "status": "NO ATTACHMENT"})
            continue

        # Download & OCR
        att_id = reg_att.get("id", "")
        filename = reg_att.get("File_Name", "unknown")
        file_bytes, content_type = crm.download_attachment(deal_id, att_id)
        media_type = detect_media_type(filename, content_type)

        if not (is_image(media_type) or is_pdf(media_type)):
            print(f"  SKIP: Unsupported file type {media_type}")
            results.append({"deal": deal_name, "vin": vin, "status": f"BAD TYPE: {media_type}"})
            continue

        ocr_result = ocr_registration_card(claude, file_bytes, media_type)
        if not ocr_result["success"]:
            print(f"  FAIL: OCR — {ocr_result.get('reason')}")
            results.append({"deal": deal_name, "vin": vin, "status": f"OCR FAIL: {ocr_result.get('reason')}"})
            continue

        expiration_date = ocr_result["expiration_date"]
        print(f"  Expiration: {ocr_result.get('raw_date')} -> {expiration_date}")

        # VIN decode
        vehicle_info = None
        if vin:
            vin_result = vin_decoder.decode_single(vin)
            if vin_result["success"]:
                vehicle_info = vin_result
                ymm = f"{vin_result.get('year')} {vin_result.get('make')} {vin_result.get('model')}"
                print(f"  YMM: {ymm}")
            else:
                print(f"  VIN decode failed: {vin_result.get('error_text', '')[:80]}")

        # LIVE WRITE
        result = enricher.enrich(deal_id, deal_name, expiration_date, vehicle_info, dry_run=False)
        if result.get("success"):
            ymm_str = f"{vehicle_info['year']} {vehicle_info['make']} {vehicle_info['model']}" if vehicle_info else "(no VIN data)"
            print(f"  WRITTEN: Exp={expiration_date}, YMM={ymm_str}")
            results.append({"deal": deal_name, "vin": vin, "status": "SUCCESS", "expiration": expiration_date, "ymm": ymm_str})
        else:
            print(f"  WRITE FAILED: {result}")
            results.append({"deal": deal_name, "vin": vin, "status": f"WRITE FAIL: {result.get('error')}"})

    except Exception as exc:
        print(f"  ERROR: {exc}")
        results.append({"deal": deal_id, "vin": "", "status": f"ERROR: {exc}"})

# Final report
print(f"\n{'='*70}")
print(f"RESULTS REPORT")
print(f"{'='*70}")
print(f"{'#':<4} {'Status':<12} {'Expiration':<13} {'YMM':<30} {'Deal Name'}")
print("-" * 110)
for i, r in enumerate(results, 1):
    status = r.get("status", "?")[:10]
    exp = r.get("expiration", "")
    ymm = r.get("ymm", "")[:28]
    deal = r.get("deal", "")[:45]
    print(f"{i:<4} {status:<12} {exp:<13} {ymm:<30} {deal}")

success_count = sum(1 for r in results if r.get("status") == "SUCCESS")
print(f"\nTotal: {len(results)} | Success: {success_count} | Failed: {len(results) - success_count}")
