"""CRM Enrichment module — enriches Closed Won deals with registration expiration dates,
VIN numbers, and Year/Make/Model from OCR and NHTSA decode."""

import os
import time
from pathlib import Path
from typing import Any

from src.core.logger import get_logger
from src.core.module_registry import BaseModule, HubContext
from src.modules.crm_enrichment.crm_queries import EnrichmentCRMQueries
from src.modules.crm_enrichment.ocr_processor import ocr_registration_card
from src.modules.crm_enrichment.vin_decoder import extract_vin, nhtsa_decode
from src.modules.crm_enrichment.report import send_completion_report

logger = get_logger("hub.modules.crm_enrichment.module")

HEARTBEAT_INTERVAL = 200  # Telegram heartbeat every N deals
_SUPPORTED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp")
_SKIP_KEYWORDS = ("signature", "screenshot")
_REG_KEYWORDS = ("registration", "reg ")

_EXTENSION_MEDIA_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


class CRMEnrichmentModule(BaseModule):
    def __init__(self, hub_context: HubContext) -> None:
        super().__init__(hub_context)
        cfg = self.ctx.config
        self.crm = EnrichmentCRMQueries(
            self.ctx.zoho_auth, cfg.zoho.api_domain, cfg.crm_fields
        )
        self.data_dir = cfg.project_root / "data"

    def name(self) -> str:
        return "crm_enrichment"

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
        fields = cfg.crm_fields

        # Module-specific config from env vars (or kwargs override)
        target_year = int(kwargs.get("target_year", os.getenv("ENRICHMENT_TARGET_YEAR", "2025")))
        target_month = int(kwargs.get("target_month", os.getenv("ENRICHMENT_TARGET_MONTH", "1")))
        dry_run = kwargs.get("dry_run", os.getenv("ENRICHMENT_DRY_RUN", "true").lower() == "true")
        batch_size = int(kwargs.get("batch_size", os.getenv("ENRICHMENT_BATCH_SIZE", "200")))

        run_id = self.ctx.metrics.start_run(self.name())
        start_time = time.time()

        succeeded = 0
        failed = 0
        skipped = 0
        errors: dict[str, int] = {}
        progress_file = self.data_dir / "enrichment_progress.txt"

        try:
            # Load progress for resumability
            processed_ids = _load_progress(progress_file)
            logger.info(
                "=== CRM Enrichment starting (year=%d, month=%02d, dry_run=%s, resume=%d already done) ===",
                target_year, target_month, dry_run, len(processed_ids),
            )

            # Notify start
            self.ctx.notifications.send_warning(
                self.name(),
                f"Starting enrichment for {target_month:02d}/{target_year} (dry_run={dry_run})",
            )

            # Fetch all Closed Won deals for the target month
            all_deals = self.crm.fetch_closed_won_deals(target_year, target_month)
            logger.info("Fetched %d total Closed Won deals for %02d/%d", len(all_deals), target_month, target_year)

            # Filter: only deals missing Reg_Expiration
            target_deals = [
                d for d in all_deals
                if not d.get(fields.expiration_date)
            ]
            logger.info(
                "%d deals missing %s (out of %d total)",
                len(target_deals), fields.expiration_date, len(all_deals),
            )

            total = len(target_deals)
            self.ctx.metrics.update_run_counts(run_id, total_items=total)

            for idx, deal in enumerate(target_deals, 1):
                deal_id = str(deal.get("id", ""))
                deal_name = deal.get("Deal_Name", "")

                # Skip already-processed deals (resumability)
                if deal_id in processed_ids:
                    skipped += 1
                    continue

                try:
                    result = self._process_deal(deal, run_id, dry_run=dry_run)
                    if result == "success":
                        succeeded += 1
                        _append_progress(progress_file, deal_id)
                    elif result == "skipped":
                        skipped += 1
                        _append_progress(progress_file, deal_id)
                    else:
                        failed += 1
                        reason = result if isinstance(result, str) else "unknown"
                        errors[reason] = errors.get(reason, 0) + 1
                except Exception as exc:
                    logger.error("Unhandled error on deal %s (%s): %s", deal_id, deal_name, exc)
                    failed += 1
                    errors["unhandled_error"] = errors.get("unhandled_error", 0) + 1
                    self.ctx.metrics.record_event(
                        run_id, self.name(), "failed", deal_id, deal_name, {"error": str(exc)}
                    )

                # Update DB counters every 10 deals so /status stays fresh
                if idx % 10 == 0 or idx == total:
                    self.ctx.metrics.update_run_counts(
                        run_id, processed=idx, succeeded=succeeded, failed=failed, skipped=skipped,
                    )

                # Progress logging and Telegram heartbeat every HEARTBEAT_INTERVAL
                if idx % HEARTBEAT_INTERVAL == 0 or idx == total:
                    pct = (idx / total * 100) if total else 0
                    logger.info("Progress: %d/%d (%.1f%%) — %d ok, %d fail, %d skip",
                                idx, total, pct, succeeded, failed, skipped)
                    if idx % HEARTBEAT_INTERVAL == 0 and idx < total:
                        self.ctx.notifications.send_progress(
                            self.name(), idx, total,
                            f"{succeeded} enriched, {failed} failed",
                        )

            # Completion
            duration = int(time.time() - start_time)
            self.ctx.metrics.complete_run(run_id, "completed", errors if errors else None)

            # Build email client if configured
            email_client = None
            if cfg.sendgrid_api_key:
                from src.core.email_client import SendGridClient
                email_client = SendGridClient(
                    cfg.sendgrid_api_key, cfg.sendgrid_from_email, cfg.sendgrid_to_email,
                )

            send_completion_report(
                self.ctx.notifications,
                email_client,
                module_name=self.name(),
                year=target_year,
                month=target_month,
                total=len(all_deals),
                processed=total,
                succeeded=succeeded,
                failed=failed,
                skipped=skipped,
                errors=errors,
                duration_seconds=duration,
            )

            logger.info(
                "=== CRM Enrichment complete — %d succeeded, %d failed, %d skipped (%.0fs) ===",
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
            logger.exception("CRM Enrichment crashed: %s", exc)
            self.ctx.metrics.complete_run(run_id, "failed", {"crash": str(exc)})
            self.ctx.notifications.send_critical(self.name(), exc)
            return {"status": "failed", "error": str(exc), "run_id": run_id}

    # ------------------------------------------------------------------
    # Per-deal processing
    # ------------------------------------------------------------------

    def _process_deal(self, deal: dict, run_id: str, *, dry_run: bool) -> str:
        """Process a single deal. Returns 'success', 'skipped', or a failure reason string."""
        fields = self.ctx.config.crm_fields
        deal_id = str(deal.get("id", ""))
        deal_name = deal.get("Deal_Name", "")

        logger.debug("Processing deal %s: %s", deal_id, deal_name)

        # --- Extract VIN from Deal_Name ---
        vin = extract_vin(deal_name)
        existing_vin = deal.get(fields.vin, "") or ""

        # --- Attachments: find and OCR registration card ---
        has_attachments = deal.get("Has_Attatchments1", False)
        if not has_attachments:
            logger.info("Deal %s has no attachments — skipping OCR", deal_id)
            # Still try to enrich with VIN if available
            if vin:
                return self._enrich_vin_only(deal_id, deal_name, vin, existing_vin, fields, run_id, dry_run)
            return "skipped"

        attachments = self.crm.list_attachments(deal_id)
        if not attachments:
            logger.info("Deal %s returned no attachments from API — skipping", deal_id)
            if vin:
                return self._enrich_vin_only(deal_id, deal_name, vin, existing_vin, fields, run_id, dry_run)
            return "skipped"

        # Try up to 3 attachments to find a registration card
        reg_att = _pick_registration_attachment(attachments)
        candidates = [reg_att] if reg_att else []
        # If the top pick fails OCR, try the next best attachments
        if len(candidates) == 0:
            candidates = _rank_attachments(attachments)[:3]
        elif len(candidates) == 1:
            others = _rank_attachments([a for a in attachments if a.get("id") != reg_att.get("id")])
            candidates.extend(others[:2])

        expiration_date = None
        for att in candidates:
            att_id = str(att.get("id", ""))
            filename = att.get("File_Name") or att.get("file_name") or "unknown"
            logger.debug("Trying attachment: %s (%s)", filename, att_id)

            try:
                file_bytes, content_type = self.crm.download_attachment(deal_id, att_id)
            except Exception as exc:
                logger.warning("Failed to download attachment %s on deal %s: %s", att_id, deal_id, exc)
                continue

            media_type = _detect_media_type(filename, content_type)
            if media_type == "application/octet-stream":
                logger.debug("Unsupported media type for %s — skipping", filename)
                continue

            ocr_result = ocr_registration_card(
                self.ctx.claude_client, file_bytes, media_type, run_id=run_id,
            )
            if ocr_result["success"]:
                expiration_date = ocr_result["expiration_date"]
                logger.info("OCR success on deal %s: expiration=%s (from %s)", deal_id, expiration_date, filename)
                break
            else:
                logger.info("OCR did not find date on %s: %s", filename, ocr_result.get("reason", ""))

        if not expiration_date:
            logger.warning("No expiration date found for deal %s after trying %d attachments", deal_id, len(candidates))
            self.ctx.metrics.record_event(
                run_id, self.name(), "failed", deal_id, deal_name, {"reason": "ocr_failed"}
            )
            return "ocr_failed"

        # --- NHTSA VIN decode ---
        year_make_model = ""
        use_vin = vin or existing_vin
        if use_vin:
            year, make, model = nhtsa_decode(use_vin)
            if year or make or model:
                year_make_model = f"{year} {make} {model}".strip()
                self.ctx.metrics.record_api_usage(run_id, "nhtsa", f"decodevin/{use_vin}")

        # --- Write back to CRM ---
        update_fields: dict[str, Any] = {
            fields.expiration_date: expiration_date,
        }
        if year_make_model:
            update_fields[fields.vehicle_ymm] = year_make_model
        if vin and not existing_vin:
            update_fields[fields.vin] = vin

        if dry_run:
            logger.info("DRY RUN | Would update deal %s (%s): %s", deal_id, deal_name, update_fields)
        else:
            self.crm.update_deal(deal_id, update_fields)
            logger.info("Updated deal %s (%s): %s", deal_id, deal_name, update_fields)

        self.ctx.metrics.record_event(
            run_id, self.name(), "processed", deal_id, deal_name,
            {"expiration_date": expiration_date, "ymm": year_make_model, "dry_run": dry_run},
        )
        return "success"

    def _enrich_vin_only(
        self, deal_id: str, deal_name: str, vin: str, existing_vin: str,
        fields: Any, run_id: str, dry_run: bool,
    ) -> str:
        """When no attachment is available, at least try to decode and write VIN + YMM."""
        year, make, model = nhtsa_decode(vin)
        if not (year or make or model):
            return "skipped"

        year_make_model = f"{year} {make} {model}".strip()
        update_fields: dict[str, Any] = {}
        if year_make_model:
            update_fields[fields.vehicle_ymm] = year_make_model
        if vin and not existing_vin:
            update_fields[fields.vin] = vin

        if not update_fields:
            return "skipped"

        if dry_run:
            logger.info("DRY RUN | VIN-only enrich for deal %s: %s", deal_id, update_fields)
        else:
            self.crm.update_deal(deal_id, update_fields)
            logger.info("VIN-only enrich for deal %s: %s", deal_id, update_fields)

        self.ctx.metrics.record_event(
            run_id, self.name(), "processed", deal_id, deal_name,
            {"vin_only": True, "ymm": year_make_model, "dry_run": dry_run},
        )
        return "success"


# ------------------------------------------------------------------
# Attachment selection helpers (self-contained, not imported)
# ------------------------------------------------------------------


def _pick_registration_attachment(attachments: list[dict]) -> dict | None:
    """Pick the best registration-card attachment by keyword match."""
    ranked = _rank_attachments(attachments)
    return ranked[0] if ranked else None


def _rank_attachments(attachments: list[dict]) -> list[dict]:
    """Rank attachments by likelihood of being a registration card."""
    scored: list[tuple[int, dict]] = []
    for att in attachments:
        fname = (att.get("File_Name") or att.get("file_name") or "").lower()
        if not any(fname.endswith(ext) for ext in _SUPPORTED_EXTENSIONS):
            continue
        if any(kw in fname for kw in _SKIP_KEYWORDS):
            continue

        if any(kw in fname for kw in _REG_KEYWORDS):
            scored.append((0, att))
        elif fname.endswith(".pdf"):
            scored.append((1, att))
        else:
            scored.append((2, att))

    scored.sort(key=lambda pair: (pair[0], pair[1].get("Created_Time", "")))
    return [att for _, att in scored]


def _detect_media_type(filename: str, content_type_header: str = "") -> str:
    """Determine MIME type from filename extension or Content-Type header."""
    fname_lower = filename.lower()
    for ext, media in _EXTENSION_MEDIA_MAP.items():
        if fname_lower.endswith(ext):
            return media
    if content_type_header:
        ct = content_type_header.lower()
        if "pdf" in ct:
            return "application/pdf"
        if "jpeg" in ct or "jpg" in ct:
            return "image/jpeg"
        if "png" in ct:
            return "image/png"
    return "application/octet-stream"


# ------------------------------------------------------------------
# Progress file helpers
# ------------------------------------------------------------------


def _load_progress(path: Path) -> set[str]:
    """Load previously processed deal IDs from the progress file."""
    if not path.exists():
        return set()
    with open(path, "r") as f:
        return {line.strip() for line in f if line.strip()}


def _append_progress(path: Path, deal_id: str) -> None:
    """Append a deal ID to the progress file (flushed immediately for crash safety)."""
    with open(path, "a") as f:
        f.write(deal_id + "\n")
        f.flush()
