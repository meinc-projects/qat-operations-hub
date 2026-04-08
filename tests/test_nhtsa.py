"""Validate NHTSA VIN decode works with a known test VIN.

Usage::

    python tests/test_nhtsa.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.modules.renewal_backfill.vin_decoder import decode_single


def main() -> None:
    test_vin = "1HGCM82633A004352"
    print(f"Decoding test VIN: {test_vin}")

    result = decode_single(test_vin)

    if not result["success"]:
        print(f"[FAIL] Decode failed: {result}")
        sys.exit(1)

    print(f"  Year:       {result.get('year')}")
    print(f"  Make:       {result.get('make')}")
    print(f"  Model:      {result.get('model')}")
    print(f"  Body class: {result.get('body_class')}")
    print(f"  Error code: {result.get('error_code')}")

    expected_make = "HONDA"
    actual_make = (result.get("make") or "").upper()
    if expected_make in actual_make:
        print(f"\n[PASS] Make matches expected ({expected_make})")
    else:
        print(f"\n[FAIL] Expected make '{expected_make}', got '{actual_make}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
