"""Zoho CRM COQL queries and record-level API operations for the Renewal Backfill module."""

from typing import Any

from src.core.logger import get_logger
from src.core.zoho_auth import ZohoAuthManager

logger = get_logger("hub.modules.renewal_backfill.crm_queries")

COQL_PAGE_SIZE = 200


class CRMQueries:
    def __init__(self, zoho_auth: ZohoAuthManager, api_domain: str, crm_fields: Any) -> None:
        self.auth = zoho_auth
        self.base = api_domain.rstrip("/") + "/crm/v8"
        self.base_v2 = api_domain.rstrip("/") + "/crm/v2"
        self.fields = crm_fields

    # ------------------------------------------------------------------
    # COQL helpers
    # ------------------------------------------------------------------

    def _coql(self, query: str) -> list[dict]:
        url = f"{self.base}/coql"
        logger.debug("COQL query: %s", query)
        resp = self.auth.make_request("POST", url, json={"select_query": query})
        if resp.status_code >= 400:
            logger.error("COQL error %d: %s | Query: %s", resp.status_code, resp.text[:500], query)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    # ------------------------------------------------------------------
    # Target deal queries
    # ------------------------------------------------------------------

    def fetch_target_deals(
        self,
        start_date: str,
        end_date: str,
        available_fields: set[str] | None = None,
    ) -> list[dict]:
        """Return all deals in [start_date, end_date] that have no Expiration_Date.

        Paginates through COQL in pages of 200 until exhausted.
        """
        all_deals: list[dict] = []
        offset = 0
        f = self.fields

        select_cols = [
            "id", "Deal_Name", f.contact, f.account, f.vin,
            f.expiration_date, f.closing_date, "Service_Types",
        ]
        if available_fields is None or f.amount in available_fields:
            select_cols.append(f.amount)

        select_str = ", ".join(select_cols)

        while True:
            query = (
                f"select {select_str} "
                f"from Deals "
                f"where {f.closing_date} between '{start_date}' and '{end_date}' "
                f"and {f.expiration_date} is null "
                f"limit {COQL_PAGE_SIZE} offset {offset}"
            )
            page = self._coql(query)
            all_deals.extend(page)
            logger.info(
                "COQL page offset=%d returned %d deals (total so far: %d)",
                offset, len(page), len(all_deals),
            )

            if len(page) < COQL_PAGE_SIZE:
                break
            offset += COQL_PAGE_SIZE

        return all_deals

    def check_renewal_exists(self, vin: str, renewal_year: int) -> bool:
        """Check whether a renewal deal already exists for the given VIN."""
        if not vin:
            return False
        query = (
            f"select id from Deals "
            f"where Deal_Name like '%{renewal_year} Renewal%' "
            f"and {self.fields.vin} = '{vin}' "
            f"and {self.fields.stage} != 'Closed Lost' "
            f"limit 1"
        )
        results = self._coql(query)
        return len(results) > 0

    # ------------------------------------------------------------------
    # Attachment operations
    # ------------------------------------------------------------------

    def list_attachments(self, deal_id: str) -> list[dict]:
        url = f"{self.base_v2}/Deals/{deal_id}/Attachments"
        resp = self.auth.make_request("GET", url)
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])

    def download_attachment(self, deal_id: str, attachment_id: str) -> tuple[bytes, str]:
        """Download an attachment and return (raw_bytes, content_type)."""
        url = f"{self.base_v2}/Deals/{deal_id}/Attachments/{attachment_id}"
        resp = self.auth.make_request("GET", url)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, content_type

    # ------------------------------------------------------------------
    # Deal CRUD
    # ------------------------------------------------------------------

    def update_deal(self, deal_id: str, fields: dict) -> dict:
        url = f"{self.base}/Deals/{deal_id}"
        payload = {"data": [{"id": deal_id, **fields}]}
        resp = self.auth.make_request("PUT", url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def create_deal(self, deal_data: dict) -> dict:
        url = f"{self.base}/Deals"
        payload = {"data": [deal_data]}
        resp = self.auth.make_request("POST", url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Contact operations
    # ------------------------------------------------------------------

    def get_contact(self, contact_id: str) -> dict | None:
        url = f"{self.base}/Contacts/{contact_id}"
        params = {"fields": "Phone,Mobile,Email,Full_Name"}
        resp = self.auth.make_request("GET", url, params=params)
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0] if data else None

    # ------------------------------------------------------------------
    # Field introspection (used by test_connection)
    # ------------------------------------------------------------------

    def get_deals_fields(self) -> list[dict]:
        url = f"{self.base}/settings/fields"
        resp = self.auth.make_request("GET", url, params={"module": "Deals"})
        resp.raise_for_status()
        return resp.json().get("fields", [])
