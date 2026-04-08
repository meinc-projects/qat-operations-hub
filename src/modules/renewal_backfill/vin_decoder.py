"""NHTSA vPIC API integration for VIN decoding."""

import time
from typing import Any

import requests

from src.core.logger import get_logger

logger = get_logger("hub.modules.renewal_backfill.vin_decoder")

_SINGLE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
_BATCH_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
_BATCH_MAX = 50
_INTER_CALL_DELAY = 0.5


def decode_single(vin: str) -> dict:
    """Decode a single VIN via the NHTSA API.

    Returns::

        {"success": True, "year": "2019", "make": "HONDA", "model": "Civic", "body_class": "Sedan", "error_code": "0"}
        {"success": False, "error_code": "5", "error_text": "..."}
    """
    url = _SINGLE_URL.format(vin=vin)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("Results", [{}])[0]
    return _parse_result(results, vin)


def decode_batch(vins: list[str]) -> dict[str, dict]:
    """Decode up to 50 VINs in a single NHTSA batch request.

    Returns a mapping of VIN → decode result.
    """
    if not vins:
        return {}

    out: dict[str, dict] = {}
    for chunk_start in range(0, len(vins), _BATCH_MAX):
        chunk = vins[chunk_start : chunk_start + _BATCH_MAX]
        data_str = ";".join(chunk)
        resp = requests.post(
            _BATCH_URL,
            data={"DATA": data_str, "format": "json"},
            timeout=60,
        )
        resp.raise_for_status()

        results = resp.json().get("Results", [])
        for result in results:
            vin = result.get("VIN", "")
            if vin:
                out[vin] = _parse_result(result, vin)

        if chunk_start + _BATCH_MAX < len(vins):
            time.sleep(_INTER_CALL_DELAY)

    return out


def _parse_result(result: dict, vin: str) -> dict:
    error_code = result.get("ErrorCode", "0")
    primary_code = str(error_code).split(",")[0].strip() if error_code else "0"

    year = result.get("ModelYear", "")
    make = result.get("Make", "")
    model = result.get("Model", "")
    body_class = result.get("BodyClass", "")

    try:
        code_int = int(primary_code)
    except ValueError:
        code_int = 0

    if code_int >= 5:
        logger.warning("NHTSA: VIN %s is invalid (ErrorCode=%s): %s", vin, error_code, result.get("ErrorText", ""))
        return {
            "success": False,
            "error_code": primary_code,
            "error_text": result.get("ErrorText", ""),
            "year": year,
            "make": make,
            "model": model,
        }

    logger.debug("NHTSA decoded VIN %s → %s %s %s", vin, year, make, model)
    return {
        "success": True,
        "year": year,
        "make": make,
        "model": model,
        "body_class": body_class,
        "error_code": primary_code,
    }
