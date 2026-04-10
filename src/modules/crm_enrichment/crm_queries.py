"""Zoho CRM queries and operations for the CRM Enrichment module."""

import calendar
import time
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.crm_enrichment.crm")

COQL_PAGE_SIZE = 200
_MAX_RETRIES = 3
_RETRY_WAIT = 2  # seconds


def _retry(func):
    """Decorator: retry a Zoho API call up to _MAX_RETRIES times with _RETRY_WAIT between."""
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "%s attempt %d/%d failed: %s — retrying in %ds",
                    func.__name__, attempt, _MAX_RETRIES, exc, _RETRY_WAIT,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_WAIT)
        raise last_exc
    return wrapper


class EnrichmentCRMQueries:
    """COQL queries, attachment operations, and deal updates for CRM enrichment."""

    def __init__(self, zoho_auth: Any, api_domain: str, crm_fields: Any) -> None:
        self.auth = zoho_auth
        self.base = api_domain.rstrip("/") + "/crm/v8"
        self.base_v2 = api_domain.rstrip("/") + "/crm/v2"
        self.fields = crm_fields

    def fetch_closed_won_deals(self, year: int, month: int) -> list[dict]:
        """Fetch all Closed Won deals for a given month/year via paginated COQL.

        NOTE: COQL cannot combine 'is null' with 'between', so we fetch ALL
        Closed Won deals for the date range. Filtering for missing Reg_Expiration
        is done in Python by the caller.
        """
        last_day = calendar.monthrange(year, month)[1]
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{last_day:02d}"

        cols = (
            f"id, Deal_Name, Closing_Date, Account_Name, Contact_Name, "
            f"{self.fields.expiration_date}, {self.fields.vin}, "
            f"{self.fields.vehicle_ymm}, Has_Attatchments1"
        )

        all_deals: list[dict] = []
        offset = 0

        while True:
            query = (
                f"SELECT {cols} FROM Deals "
                f"WHERE Stage = 'Closed Won' "
                f"AND Closing_Date between '{start_date}' and '{end_date}' "
                f"LIMIT {COQL_PAGE_SIZE} OFFSET {offset}"
            )
            page = self._coql(query)
            all_deals.extend(page)
            logger.info(
                "Fetched %d deals (offset %d, total so far %d)",
                len(page), offset, len(all_deals),
            )
            if len(page) < COQL_PAGE_SIZE:
                break
            offset += COQL_PAGE_SIZE

        return all_deals

    @_retry
    def _coql(self, query: str) -> list[dict]:
        """Execute a COQL query and return the data array."""
        resp = self.auth.make_request(
            "POST",
            f"{self.base}/coql",
            json={"select_query": query},
            timeout=30,
        )
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])

    @_retry
    def list_attachments(self, deal_id: str) -> list[dict]:
        """List all attachments on a deal. Returns empty list if none."""
        resp = self.auth.make_request(
            "GET",
            f"{self.base_v2}/Deals/{deal_id}/Attachments",
            timeout=20,
        )
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])

    @_retry
    def download_attachment(self, deal_id: str, attachment_id: str) -> tuple[bytes, str]:
        """Download an attachment. Returns (file_bytes, content_type)."""
        resp = self.auth.make_request(
            "GET",
            f"{self.base_v2}/Deals/{deal_id}/Attachments/{attachment_id}",
            timeout=40,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, content_type

    @_retry
    def update_deal(self, deal_id: str, fields: dict) -> dict:
        """Update a deal with the given fields."""
        payload = {"data": [{"id": deal_id, **fields}]}
        resp = self.auth.make_request(
            "PUT",
            f"{self.base}/Deals/{deal_id}",
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
