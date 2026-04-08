"""Write enriched data (expiration date, vehicle info) back to CRM deals."""

from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.deal_enricher")


class DealEnricher:
    def __init__(self, crm_queries: Any, crm_fields: Any, vehicle_fields_exist: bool = True) -> None:
        self.crm = crm_queries
        self.fields = crm_fields
        self.vehicle_fields_exist = vehicle_fields_exist

    def enrich(
        self,
        deal_id: str,
        deal_name: str,
        expiration_date: str,
        vehicle_info: dict | None = None,
        *,
        dry_run: bool = True,
    ) -> dict:
        """Update a deal with expiration date and optionally vehicle info.

        Args:
            deal_id: Zoho deal record ID.
            deal_name: Human-readable deal name (for logging).
            expiration_date: YYYY-MM-DD format.
            vehicle_info: Dict with keys year, make, model (from VIN decode).
            dry_run: If True, log what would happen but skip the API call.

        Returns:
            {"success": True/False, ...}
        """
        update: dict[str, str] = {
            self.fields.expiration_date: expiration_date,
        }

        if vehicle_info and self.vehicle_fields_exist:
            ymm_parts = [
                str(vehicle_info.get("year", "")),
                str(vehicle_info.get("make", "")),
                str(vehicle_info.get("model", "")),
            ]
            ymm = " ".join(p for p in ymm_parts if p).strip()
            if ymm:
                update[self.fields.vehicle_ymm] = ymm

        if dry_run:
            parts = ", ".join(f"{k}={v}" for k, v in update.items())
            logger.info("DRY RUN | Deal %s (%s) | Would set %s", deal_id, deal_name, parts)
            return {"success": True, "dry_run": True}

        try:
            result = self.crm.update_deal(deal_id, update)
            logger.info("Updated deal %s (%s) — %s", deal_id, deal_name, update)
            return {"success": True, "response": result}
        except Exception as exc:
            logger.error("Failed to update deal %s (%s): %s", deal_id, deal_name, exc)
            return {"success": False, "error": str(exc)}
