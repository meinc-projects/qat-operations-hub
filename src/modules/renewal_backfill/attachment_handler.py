"""Download and identify registration-card attachments on Zoho CRM deals."""

from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.attachment_handler")

_REG_KEYWORDS = ("registration", "reg ")
_SKIP_KEYWORDS = ("signature", "screenshot")
_SUPPORTED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp")

_EXTENSION_MEDIA_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def pick_registration_attachment(attachments: list[dict]) -> dict | None:
    """Select the most likely registration-card attachment from a list.

    Priority:
    1. Files with 'registration' or 'reg ' in the filename
    2. Any PDF attachment (most likely to be the scanned document)
    3. Any image attachment (jpg/png photo of the card)

    Skips files that look like signatures or screenshots.
    Prefers the most recently created file when multiple candidates exist.
    """
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

    if not scored:
        return None

    scored.sort(key=lambda pair: (pair[0], pair[1].get("Created_Time", "")))
    chosen = scored[0][1]
    logger.info(
        "Selected attachment: %s (id=%s, priority=%d)",
        chosen.get("File_Name"),
        chosen.get("id"),
        scored[0][0],
    )
    return chosen


def detect_media_type(filename: str, content_type_header: str = "") -> str:
    """Determine the MIME type from filename extension or Content-Type header."""
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

    logger.warning("Could not determine media type for '%s' (content-type: %s)", filename, content_type_header)
    return "application/octet-stream"


def audit_attachments(attachments: list[dict]) -> dict[str, bool]:
    """Check which required file types are present.

    Returns {"has_reg_file": bool, "has_dmv_paperwork": bool}.
    """
    has_reg = False
    has_dmv = False
    for att in attachments:
        fname = (att.get("File_Name") or att.get("file_name") or "").lower()
        if fname.startswith("reg") or fname.startswith("registration"):
            has_reg = True
        if fname.startswith("dmv paperwork") or fname.startswith("dmv_paperwork"):
            has_dmv = True
    return {"has_reg_file": has_reg, "has_dmv_paperwork": has_dmv}


def is_pdf(media_type: str) -> bool:
    return media_type == "application/pdf"


def is_image(media_type: str) -> bool:
    return media_type.startswith("image/")
