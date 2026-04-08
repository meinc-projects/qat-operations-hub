"""Claude Vision OCR for California DMV registration cards."""

import base64
import json
import re
from datetime import datetime
from typing import Any

from src.core.claude_client import ClaudeClient
from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.ocr_processor")

_OCR_PROMPT = (
    "Extract the registration EXPIRATION date from this document. "
    "Rules: if the card says 'VALID FROM: [date1] TO: [date2]', use date2. "
    "If it says 'EXP' or 'EXP DT' or 'PR EXP DATE', use that date. "
    "Always use the LATER date — the one the registration EXPIRES on. "
    "Do NOT return the start/from date. "
    "Respond with ONLY this JSON, nothing else: "
    '{"expiration_date": "MM/DD/YYYY"}'
)


def _extract_json(text: str) -> dict | None:
    """Try to find and parse a JSON object embedded in free text."""
    match = re.search(r'\{[^{}]*"expiration_date"[^{}]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from Claude's response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_DATE_FORMATS = [
    "%m/%d/%Y",    # 01/06/2025
    "%m/%d/%y",    # 01/06/25
    "%m-%d-%Y",    # 01-06-2025
    "%m-%d-%y",    # 01-06-25
    "%Y-%m-%d",    # 2025-01-06
    "%B %d, %Y",   # January 06, 2025
    "%b %d, %Y",   # Jan 06, 2025
]


def _parse_date(raw: str) -> str | None:
    """Parse common date formats and return YYYY-MM-DD for Zoho, or None."""
    cleaned = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue
    return None


def ocr_registration_card(
    claude_client: ClaudeClient,
    file_bytes: bytes,
    media_type: str,
    *,
    run_id: str | None = None,
) -> dict:
    """Run OCR on a registration card image or PDF.

    Returns::

        {"success": True, "expiration_date": "2026-07-31", "raw_date": "07/31/2026", "usage": {...}}
        {"success": False, "reason": "...", "usage": {...}}
    """
    b64 = base64.b64encode(file_bytes).decode("ascii")

    if media_type == "application/pdf":
        result = claude_client.analyze_document(b64, _OCR_PROMPT, run_id=run_id)
    else:
        result = claude_client.analyze_image(b64, media_type, _OCR_PROMPT, run_id=run_id)

    raw_text = result["text"]
    usage = result["usage"]

    try:
        cleaned = _strip_code_fences(raw_text)
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _extract_json(raw_text)
        if parsed is None:
            logger.warning("Claude returned non-JSON response: %s", raw_text[:200])
            return {"success": False, "reason": f"Non-JSON response: {raw_text[:200]}", "usage": usage}

    raw_date = parsed.get("expiration_date")
    if raw_date is None:
        reason = parsed.get("reason", "No date found")
        logger.info("OCR could not extract date: %s", reason)
        return {"success": False, "reason": reason, "usage": usage}

    if raw_date.strip().upper() == "PERM":
        logger.info("OCR detected permanent registration")
        return {"success": False, "reason": "perm_registration", "usage": usage}

    zoho_date = _parse_date(raw_date)
    if zoho_date is None:
        logger.warning("OCR returned unparseable date: %s", raw_date)
        return {"success": False, "reason": f"Unparseable date format: {raw_date}", "usage": usage}

    logger.debug("OCR extracted expiration date: %s → %s", raw_date, zoho_date)
    return {"success": True, "expiration_date": zoho_date, "raw_date": raw_date, "usage": usage}
