"""VIN extraction from deal names and NHTSA VIN decoding."""

import json
import re
import urllib.request

from src.core.logger import get_logger

logger = get_logger("hub.crm_enrichment.vin_decoder")

_VIN_PATTERN = re.compile(r'[A-HJ-NPR-Z0-9]{17}', re.I)


def extract_vin(deal_name: str) -> str | None:
    """Extract a 17-character VIN from a deal name.

    Deal names typically follow: "Contact - Service - VIN" or similar patterns.
    Tries structured split first, then falls back to regex search.
    """
    if not deal_name:
        return None

    # Try structured split: parts[-1] is often the VIN
    parts = deal_name.split(" - ")
    if len(parts) >= 3:
        candidate = parts[-1].strip()
        if re.match(r'^[A-HJ-NPR-Z0-9]{17}$', candidate, re.I):
            return candidate.upper()

    # Fallback: find any 17-char VIN anywhere in the string
    m = _VIN_PATTERN.search(deal_name)
    return m.group(0).upper() if m else None


def nhtsa_decode(vin: str) -> tuple[str, str, str]:
    """Decode a VIN via the NHTSA vPIC API.

    Returns (year, make, model). Empty strings on failure.
    """
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
            results = {
                i["Variable"]: i["Value"]
                for i in data.get("Results", [])
                if i.get("Value") and i["Value"] not in ("Not Applicable", "null", None)
            }
        year = results.get("Model Year", "")
        make = results.get("Make", "")
        model = results.get("Model", "")
        logger.debug("NHTSA decode %s: %s %s %s", vin, year, make, model)
        return (year, make, model)
    except Exception as exc:
        logger.warning("NHTSA decode failed for VIN %s: %s", vin, exc)
        return ("", "", "")
