"""Create 2026 renewal deals in Zoho CRM."""

from datetime import datetime, timedelta
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.renewal_creator")


class RenewalCreator:
    def __init__(self, crm_queries: Any, crm_fields: Any, config: Any) -> None:
        self.crm = crm_queries
        self.fields = crm_fields
        self.renewal_year = config.backfill.renewal_year
        self.days_before = config.backfill.days_before_expiry

    def _build_deal_name(
        self,
        contact_name: str,
        vehicle_info: dict | None = None,
    ) -> str:
        if vehicle_info and vehicle_info.get("year") and vehicle_info.get("make") and vehicle_info.get("model"):
            return (
                f"{self.renewal_year} Renewal - "
                f"{vehicle_info['year']} {vehicle_info['make']} {vehicle_info['model']} - "
                f"{contact_name}"
            )
        return f"{self.renewal_year} Renewal - {contact_name}"

    def _compute_closing_date(self, expiration_date: str) -> str:
        exp = datetime.strptime(expiration_date, "%Y-%m-%d")
        closing = exp - timedelta(days=self.days_before)
        return closing.strftime("%Y-%m-%d")

    def create(
        self,
        original_deal: dict,
        expiration_date: str,
        vehicle_info: dict | None = None,
        contact_name: str = "",
        *,
        dry_run: bool = True,
    ) -> dict:
        """Create a renewal deal linked to the same contact.

        Args:
            original_deal: The source deal record dict.
            expiration_date: YYYY-MM-DD of the registration expiration.
            vehicle_info: VIN decode results (year, make, model).
            contact_name: Display name for the contact.
            dry_run: If True, log only.

        Returns:
            {"success": True, "deal_id": "..."} or {"success": False, ...}
        """
        vin = original_deal.get(self.fields.vin, "")
        original_id = original_deal.get("id", "")

        # Duplicate prevention
        if vin and self.crm.check_renewal_exists(vin, self.renewal_year):
            logger.info("Renewal already exists for VIN %s — skipping", vin)
            return {"success": False, "reason": "renewal_exists"}

        deal_name = self._build_deal_name(contact_name or "Unknown", vehicle_info)
        closing_date = self._compute_closing_date(expiration_date)

        contact_ref = original_deal.get(self.fields.contact)
        if isinstance(contact_ref, dict):
            contact_id = contact_ref.get("id")
        else:
            contact_id = contact_ref

        deal_data: dict[str, Any] = {
            "Deal_Name": deal_name,
            self.fields.stage: "Qualification",
            self.fields.closing_date: closing_date,
            self.fields.expiration_date: expiration_date,
            self.fields.vin: vin,
            "Pipeline": "Renewals",
            "Description": (
                f"Auto-generated renewal deal from {original_deal.get(self.fields.closing_date, '?')[:4]} "
                f"Closed Won deal {original_id}. "
                f"Registration expires {expiration_date}."
            ),
        }

        if contact_id:
            deal_data[self.fields.contact] = contact_id

        amount = original_deal.get(self.fields.amount)
        if amount is not None:
            deal_data[self.fields.amount] = amount

        if vehicle_info:
            ymm_parts = [
                str(vehicle_info.get("year", "")),
                str(vehicle_info.get("make", "")),
                str(vehicle_info.get("model", "")),
            ]
            ymm = " ".join(p for p in ymm_parts if p).strip()
            if ymm:
                deal_data[self.fields.vehicle_ymm] = ymm

        if dry_run:
            logger.info(
                'DRY RUN | Would create renewal deal: "%s" closing %s, linked to Contact %s',
                deal_name,
                closing_date,
                contact_id or "(none)",
            )
            return {"success": True, "dry_run": True, "deal_name": deal_name}

        try:
            result = self.crm.create_deal(deal_data)
            created = result.get("data", [{}])[0]
            new_id = created.get("details", {}).get("id", "unknown")
            logger.info('Created renewal deal "%s" (id=%s)', deal_name, new_id)
            return {"success": True, "deal_id": new_id, "deal_name": deal_name}
        except Exception as exc:
            logger.error('Failed to create renewal deal "%s": %s', deal_name, exc)
            return {"success": False, "error": str(exc)}
