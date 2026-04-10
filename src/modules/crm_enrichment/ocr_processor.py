"""Claude Vision OCR for CA DMV registration cards."""

import base64
import re
from datetime import datetime
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.crm_enrichment.ocr")

OCR_MODEL = "claude-sonnet-4-20250514"

_OCR_PROMPT = (
    "This is a CA DMV vehicle registration document. "
    "Find the registration EXPIRATION date only. "
    "Return YYYY-MM-DD format. If not found return NOT_FOUND. "
    "Return ONLY the date, nothing else."
)

_DATE_FORMATS = [
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
]


def ocr_registration_card(
    claude_client: Any,
    file_bytes: bytes,
    media_type: str,
    *,
    run_id: str | None = None,
) -> dict:
    """OCR a registration card image/PDF and extract the expiration date.

    Returns:
        {"success": True, "expiration_date": "YYYY-MM-DD", "raw_text": ..., "usage": ...}
        {"success": False, "reason": ..., "usage": ...}
    """
    b64 = base64.b64encode(file_bytes).decode("ascii")

    if media_type == "application/pdf":
        result = claude_client.analyze_document(
            b64, _OCR_PROMPT, run_id=run_id, model=OCR_MODEL
        )
    else:
        result = claude_client.analyze_image(
            b64, media_type, _OCR_PROMPT, run_id=run_id, model=OCR_MODEL
        )

    raw_text = result["text"].strip()
    usage = result.get("usage", {})

    if "NOT_FOUND" in raw_text.upper():
        return {"success": False, "reason": "not_found", "raw_text": raw_text, "usage": usage}

    # Try to parse the date from the response
    date_str = _extract_date_string(raw_text)
    if not date_str:
        return {"success": False, "reason": f"Unparseable response: {raw_text[:100]}", "raw_text": raw_text, "usage": usage}

    parsed = _parse_date(date_str)
    if not parsed:
        return {"success": False, "reason": f"Unparseable date: {date_str}", "raw_text": raw_text, "usage": usage}

    return {"success": True, "expiration_date": parsed, "raw_text": raw_text, "usage": usage}


def _extract_date_string(text: str) -> str | None:
    """Pull a date string out of the OCR response, stripping markdown/JSON wrappers."""
    # Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', text).replace('```', '').strip()

    # If it looks like a bare date, return it
    if re.match(r'^[\d/\-]+$', cleaned) or re.match(r'^\d{4}-\d{2}-\d{2}$', cleaned):
        return cleaned

    # Try to find a date pattern in the text
    m = re.search(r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', cleaned)
    if m:
        return m.group(1)

    m = re.search(r'(\d{4}-\d{2}-\d{2})', cleaned)
    if m:
        return m.group(1)

    return None


def _parse_date(date_str: str) -> str | None:
    """Parse a date string into YYYY-MM-DD format."""
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            # Fix 2-digit years
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
