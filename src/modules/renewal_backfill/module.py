"""Renewal Backfill module — orchestrates the full pipeline."""

import time
from typing import Any

from src.core.logger import get_logger
from src.core.module_registry import BaseModule, HubContext
from src.modules.renewal_backfill.attachment_handler import (
    audit_attachments,
    detect_media_type,
    is_image,
    is_pdf,
    pick_registration_attachment,
)
from src.modules.renewal_backfill.audit_reporter import AuditReporter
from src.modules.renewal_backfill.crm_queries import CRMQueries
from src.modules.renewal_backfill.deal_enricher import DealEnricher
from src.modules.renewal_backfill.ocr_processor import ocr_registration_card
from src.modules.renewal_backfill.renewal_creator import RenewalCreator
from src.modules.renewal_backfill import vin_decoder

logger = get_logger("hub.modules.renewal_backfill.module")

PROGRESS_INTERVAL = 50

_EXCLUDED_SERVICE_TYPES = {"VIN Verification", "Suspended Registration", "Release of Liability", "Lien Sale"}
_NO_DMV_PAPERWORK_TYPES = {"VIN Verification", "Release of Liability"}
_EXCLUDED_EXPIRATION = "2099-12-31"


class RenewalBackfillModule(BaseModule):
    def __init__(self, hub_context: HubContext) -> None:
        super().__init__(hub_context)
        cfg = self.ctx.config
        self.crm = CRMQueries(self.ctx.zoho_auth, cfg.zoho.api_domain, cfg.crm_fields)
        self.vehicle_fields_exist = True  # may be set False at startup
        self.available_fields: set[str] | None = None  # populated at run time
        self._skip_renewals = cfg.backfill.skip_renewals
        self.enricher = DealEnricher(self.crm, cfg.crm_fields, self.vehicle_fields_exist)
        self.creator = RenewalCreator(self.crm, cfg.crm_fields, cfg)

    def name(self) -> str:
        return "renewal_backfill"

    def get_status(self) -> dict:
        status = self.ctx.metrics.get_module_status(self.name())
        if status is None:
            return {"status": "never_run"}
        return status

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def run(self, **kwargs: Any) -> dict:
        cfg = self.ctx.config
        dry_run = kwargs.get("dry_run", cfg.backfill.dry_run)
        max_deals = kwargs.get("max_deals", 0)  # 0 = no limit
        self._skip_renewals = kwargs.get("skip_renewals", cfg.backfill.skip_renewals)
        start_date = cfg.backfill.start_date
        end_date = cfg.backfill.end_date

        run_id = self.ctx.metrics.start_run(self.name())
        start_time = time.time()
        auditor = AuditReporter(cfg.project_root / "data")

        succeeded = 0
        failed = 0
        skipped = 0

        try:
            self._check_vehicle_fields()

            logger.info(
                "=== Renewal Backfill starting (dry_run=%s, range=%s to %s, skip_renewals=%s) ===",
                dry_run, start_date, end_date, self._skip_renewals,
            )

            deals = self.crm.fetch_target_deals(start_date, end_date, available_fields=self.available_fields)
            if max_deals > 0:
                deals = deals[:max_deals]
                logger.info("Limited to %d deals (max_deals=%d)", len(deals), max_deals)
            total = len(deals)
            logger.info("Found %d deals to process", total)
            self.ctx.metrics.update_run_counts(run_id, total_items=total)

            for idx, deal in enumerate(deals, 1):
                deal_id = deal.get("id", "")
                deal_name = deal.get("Deal_Name", "")

                try:
                    result = self._process_deal(deal, run_id, auditor, dry_run=dry_run)
                    if result == "success":
                        succeeded += 1
                    elif result == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                except Exception as exc:
                    logger.error("Unhandled error processing deal %s (%s): %s", deal_id, deal_name, exc)
                    failed += 1
                    self.ctx.metrics.record_event(
                        run_id, self.name(), "failed", deal_id, deal_name, {"error": str(exc)}
                    )

                if idx % PROGRESS_INTERVAL == 0 or idx == total:
                    pct = (idx / total * 100) if total else 0
                    logger.info("Processed %d/%d deals (%.1f%%)", idx, total, pct)
                    self.ctx.metrics.update_run_counts(
                        run_id, processed=idx, succeeded=succeeded, failed=failed, skipped=skipped
                    )

            # Generate audit report
            audit_json_path = cfg.project_root / "data" / f"audit_report_{run_id}.json"
            error_summary = auditor.generate(run_id, total, succeeded)

            # Export to Google Sheets if configured
            self._export_to_sheets(audit_json_path)

            duration = int(time.time() - start_time)
            self.ctx.metrics.complete_run(run_id, "completed", error_summary)

            # Teams notification
            self.ctx.notifications.send_summary(
                module_name=self.name(),
                status="completed",
                processed=total,
                succeeded=succeeded,
                failed=failed,
                skipped=skipped,
                duration_seconds=duration,
                error_summary=error_summary,
            )

            # Warn if failure rate is high
            if total and (failed / total) > 0.10:
                self.ctx.notifications.send_warning(
                    self.name(),
                    f"High failure rate: {failed}/{total} deals failed ({failed/total*100:.1f}%)",
                )

            logger.info(
                "=== Renewal Backfill complete — %d succeeded, %d failed, %d skipped (%.0fs) ===",
                succeeded, failed, skipped, duration,
            )
            return {
                "status": "completed",
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "duration_seconds": duration,
                "run_id": run_id,
            }

        except Exception as exc:
            duration = int(time.time() - start_time)
            logger.exception("Renewal Backfill crashed: %s", exc)
            self.ctx.metrics.complete_run(run_id, "failed", {"crash": str(exc)})
            self.ctx.notifications.send_critical(self.name(), exc)
            return {"status": "failed", "error": str(exc), "run_id": run_id}

    # ------------------------------------------------------------------
    # Per-deal processing
    # ------------------------------------------------------------------

    def _process_deal(self, deal: dict, run_id: str, auditor: AuditReporter, *, dry_run: bool) -> str:
        """Process a single deal. Returns 'success', 'skipped', or 'failed'."""
        cfg = self.ctx.config
        fields = cfg.crm_fields
        deal_id = deal.get("id", "")
        deal_name = deal.get("Deal_Name", "")
        service_type = deal.get("Service_Types") or ""
        is_excluded = service_type in _EXCLUDED_SERVICE_TYPES

        # --- Contact / Account checks ---
        contact_ref = deal.get(fields.contact)
        contact_id = None
        contact_name = ""
        if isinstance(contact_ref, dict):
            contact_id = contact_ref.get("id")
            contact_name = contact_ref.get("name", "")
        elif contact_ref:
            contact_id = contact_ref

        account_ref = deal.get(fields.account)
        account_id = None
        account_name = ""
        if isinstance(account_ref, dict):
            account_id = account_ref.get("id")
            account_name = account_ref.get("name", "")
        elif account_ref:
            account_id = account_ref

        if not contact_id and not account_id:
            auditor.record_issue("orphan_deal", deal_id, deal_name)
        elif not contact_id:
            contact_name = account_name

        if contact_id:
            contact = self.crm.get_contact(str(contact_id))
            if contact:
                contact_name = contact_name or contact.get("Full_Name", "")
                phone = contact.get("Phone", "") or ""
                mobile = contact.get("Mobile", "") or ""
                email = contact.get("Email", "") or ""

                if not phone and not mobile:
                    auditor.record_issue("missing_phone", deal_id, deal_name, contact_name)
                if not email:
                    auditor.record_issue("missing_email", deal_id, deal_name, contact_name)

                auditor.track_phone(phone, str(contact_id))
                auditor.track_phone(mobile, str(contact_id))

        # --- Excluded service type: skip OCR, write placeholder expiration ---
        if is_excluded:
            logger.info("Excluded service type '%s' for deal %s (%s) — writing %s",
                         service_type, deal_id, deal_name, _EXCLUDED_EXPIRATION)
            auditor.record_issue("excluded_service_type", deal_id, deal_name, contact_name, service_type)

            vin = deal.get(fields.vin, "") or ""
            vehicle_info: dict | None = None
            if vin:
                vin_result = vin_decoder.decode_single(vin)
                self.ctx.metrics.record_api_usage(run_id, "nhtsa", f"DecodeVinValues/{vin}")
                if vin_result["success"]:
                    vehicle_info = vin_result

            enrich_result = self.enricher.enrich(
                deal_id, deal_name, _EXCLUDED_EXPIRATION, vehicle_info, dry_run=dry_run
            )
            self.ctx.metrics.record_event(
                run_id, self.name(), "processed", deal_id, deal_name,
                {"expiration_date": _EXCLUDED_EXPIRATION, "service_type": service_type,
                 "excluded": True, "dry_run": dry_run},
            )
            return "success" if enrich_result.get("success") else "failed"

        # --- Attachments ---
        attachments = self.crm.list_attachments(deal_id)
        if not attachments:
            auditor.record_issue("no_attachment", deal_id, deal_name, contact_name)
            self.ctx.metrics.record_event(run_id, self.name(), "skipped", deal_id, deal_name, {"reason": "no_attachment"})
            return "skipped"

        # Compliance audit: check for required file types (suppressed per service type)
        att_audit = audit_attachments(attachments)
        if not att_audit["has_reg_file"] and not is_excluded:
            att_names = ", ".join(a.get("File_Name", "?") for a in attachments)
            auditor.record_issue("missing_reg_file", deal_id, deal_name, contact_name, att_names)
        if not att_audit["has_dmv_paperwork"] and service_type not in _NO_DMV_PAPERWORK_TYPES:
            att_names = ", ".join(a.get("File_Name", "?") for a in attachments)
            auditor.record_issue("missing_dmv_paperwork", deal_id, deal_name, contact_name, att_names)

        reg_att = pick_registration_attachment(attachments)
        if reg_att is None:
            auditor.record_issue("no_reg_attachment", deal_id, deal_name, contact_name)
            self.ctx.metrics.record_event(run_id, self.name(), "skipped", deal_id, deal_name, {"reason": "no_reg_attachment"})
            return "skipped"

        # --- Download & OCR ---
        att_id = reg_att.get("id", "")
        filename = reg_att.get("File_Name", reg_att.get("file_name", "unknown"))
        file_bytes, content_type = self.crm.download_attachment(deal_id, att_id)
        media_type = detect_media_type(filename, content_type)

        if not (is_image(media_type) or is_pdf(media_type)):
            auditor.record_issue("ocr_failed", deal_id, deal_name, contact_name, f"Unsupported file type: {media_type}")
            self.ctx.metrics.record_event(run_id, self.name(), "failed", deal_id, deal_name, {"reason": "unsupported_type"})
            return "failed"

        ocr_result = ocr_registration_card(self.ctx.claude_client, file_bytes, media_type, run_id=run_id)
        if not ocr_result["success"]:
            reason = ocr_result.get("reason", "")
            if reason == "perm_registration":
                auditor.record_issue("perm_registration", deal_id, deal_name, contact_name, "PERM — requires manual expiration entry")
                self.ctx.metrics.record_event(run_id, self.name(), "failed", deal_id, deal_name, {"reason": "perm_registration"})
            else:
                auditor.record_issue("ocr_failed", deal_id, deal_name, contact_name, reason)
                self.ctx.metrics.record_event(
                    run_id, self.name(), "failed", deal_id, deal_name, {"reason": "ocr_failed", "detail": reason}
                )
            return "failed"

        expiration_date = ocr_result["expiration_date"]

        # --- VIN decode ---
        vin = deal.get(fields.vin, "") or ""
        vehicle_info = None
        if not vin:
            auditor.record_issue("missing_vin", deal_id, deal_name, contact_name)
        else:
            vin_result = vin_decoder.decode_single(vin)
            self.ctx.metrics.record_api_usage(run_id, "nhtsa", f"DecodeVinValues/{vin}")
            if vin_result["success"]:
                vehicle_info = vin_result
            else:
                auditor.record_issue("invalid_vin", deal_id, deal_name, contact_name, vin_result.get("error_text", ""))

        # --- Enrich deal ---
        enrich_result = self.enricher.enrich(
            deal_id, deal_name, expiration_date, vehicle_info, dry_run=dry_run
        )
        if not enrich_result.get("success"):
            self.ctx.metrics.record_event(
                run_id, self.name(), "failed", deal_id, deal_name, {"reason": "enrich_failed"}
            )
            return "failed"

        # --- Create renewal deal (unless skipped) ---
        skip_renewals = self._skip_renewals
        renewal_result: dict = {"success": False, "reason": "skipped_by_config"}
        if skip_renewals:
            logger.debug("Renewal creation skipped for deal %s (skip_renewals=true)", deal_id)
        else:
            renewal_result = self.creator.create(
                deal, expiration_date, vehicle_info, contact_name, dry_run=dry_run
            )
            if renewal_result.get("reason") == "renewal_exists":
                auditor.record_issue("renewal_exists", deal_id, deal_name, contact_name)

        # --- Record success ---
        self.ctx.metrics.record_event(
            run_id,
            self.name(),
            "processed",
            deal_id,
            deal_name,
            {
                "expiration_date": expiration_date,
                "vehicle": vehicle_info,
                "renewal_created": renewal_result.get("success", False),
                "dry_run": dry_run,
            },
        )
        return "success"

    # ------------------------------------------------------------------
    # Google Sheets export
    # ------------------------------------------------------------------

    def _export_to_sheets(self, audit_json_path) -> None:
        """Export audit report to Google Sheets if configured."""
        import os
        oauth_path = os.getenv("GOOGLE_OAUTH_CREDENTIALS", "")
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
        if not oauth_path:
            logger.info("Google Sheets export skipped — GOOGLE_OAUTH_CREDENTIALS not set")
            return
        oauth_full = self.ctx.config.project_root / oauth_path
        if not oauth_full.exists():
            logger.warning("Google Sheets export skipped — %s not found", oauth_full)
            return
        try:
            from src.core.google_sheets import SheetsExporter
            exporter = SheetsExporter(oauth_full, folder_id=folder_id)
            url = exporter.export_audit_report(audit_json_path)
            logger.info("Audit report exported to Google Sheets: %s", url)
        except Exception as exc:
            logger.warning("Google Sheets export failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Vehicle field check
    # ------------------------------------------------------------------

    def _check_vehicle_fields(self) -> None:
        """Best-effort check for Year_Make_Model and other CRM fields."""
        try:
            all_fields = self.crm.get_deals_fields()
            api_names = {f.get("api_name") for f in all_fields}
            self.available_fields = api_names
            cfg_fields = self.ctx.config.crm_fields

            if cfg_fields.vehicle_ymm not in api_names:
                self.vehicle_fields_exist = False
                self.enricher.vehicle_fields_exist = False
                logger.warning(
                    "Vehicle field '%s' not found in CRM. VIN decode data will be logged but not written to deals. "
                    "Create the field and restart to enable.",
                    cfg_fields.vehicle_ymm,
                )

            if cfg_fields.amount not in api_names:
                logger.warning("Amount field (%s) not found in CRM — will be omitted from queries.", cfg_fields.amount)
        except Exception as exc:
            logger.warning("Could not check CRM fields (non-fatal): %s", exc)
