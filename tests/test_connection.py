"""Pre-flight validation — run BEFORE any live module execution.

Validates connectivity and configuration for all external services.

Usage::

    python tests/test_connection.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config
from src.core.zoho_auth import ZohoAuthManager
from src.core.claude_client import ClaudeClient
from src.core.notifications import TeamsNotifier


_pass = 0
_warn = 0
_fail = 0


def _report(level: str, label: str, detail: str = "") -> None:
    global _pass, _warn, _fail
    tag = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[level]
    msg = f"{tag} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    if level == "PASS":
        _pass += 1
    elif level == "WARN":
        _warn += 1
    else:
        _fail += 1


def main() -> None:
    print("=== QAT Operations Hub — Connection Test ===\n")

    try:
        config = load_config()
    except SystemExit:
        print("\n[FAIL] Configuration could not be loaded. Fix .env and retry.")
        sys.exit(1)

    # ── 1. Zoho OAuth ───────────────────────────────────────────────
    zoho = ZohoAuthManager(
        client_id=config.zoho.client_id,
        client_secret=config.zoho.client_secret,
        refresh_token=config.zoho.refresh_token,
        accounts_domain=config.zoho.accounts_domain,
        api_domain=config.zoho.api_domain,
    )
    try:
        token = zoho.get_access_token()
        _report("PASS", "Zoho OAuth", "Token refreshed successfully")
    except Exception as exc:
        _report("FAIL", "Zoho OAuth", str(exc))
        print("       Cannot proceed without Zoho auth. Aborting remaining Zoho checks.")
        _run_non_zoho_checks(config)
        _summary()
        return

    # ── 2. Zoho CRM field validation ────────────────────────────────
    base = config.zoho.api_domain.rstrip("/") + "/crm/v8"
    fields = config.crm_fields

    try:
        resp = zoho.make_request("GET", f"{base}/settings/fields", params={"module": "Deals"})
        resp.raise_for_status()
        all_fields = resp.json().get("fields", [])
        api_names = {f.get("api_name"): f.get("display_label") for f in all_fields}

        required_fields = [
            ("Expiration_Date", fields.expiration_date),
            ("VIN", fields.vin),
            ("Stage", fields.stage),
            ("Contact_Name", fields.contact),
            ("Closing_Date", fields.closing_date),
        ]
        optional_fields = [
            ("Amount", fields.amount),
            ("Vehicle_YMM", fields.vehicle_ymm),
        ]

        for label, api_name in required_fields:
            if api_name in api_names:
                _report("PASS", f"Zoho CRM: Field '{api_name}' found in Deals module")
            else:
                _report("FAIL", f"Zoho CRM: Field '{api_name}' ({label}) NOT found")
                _suggest_alternatives(label, api_names)

        for label, api_name in optional_fields:
            if api_name in api_names:
                _report("PASS", f"Zoho CRM: Field '{api_name}' found in Deals module")
            else:
                _report("WARN", f"Zoho CRM: Field '{api_name}' NOT found", f"create this field to enable {label.lower()} data")

    except Exception as exc:
        _report("FAIL", "Zoho CRM field validation", str(exc))

    # ── 3. Zoho CRM read (COQL) ────────────────────────────────────
    try:
        resp = zoho.make_request("POST", f"{base}/coql", json={"select_query": f"select id from Deals where {fields.stage} is not null limit 1"})
        if resp.status_code >= 400:
            _report("FAIL", "Zoho CRM: COQL query", f"status {resp.status_code}: {resp.text[:300]}")
            data = []
        else:
            data = resp.json().get("data", [])
            _report("PASS", "Zoho CRM: COQL query executed successfully", f"found deals in module")
    except Exception as exc:
        _report("FAIL", "Zoho CRM: COQL query", str(exc))
        data = []

    # ── 4. Zoho CRM attachments ─────────────────────────────────────
    if data:
        deal_id = data[0].get("id", "")
        try:
            resp = zoho.make_request("GET", f"{base}/Deals/{deal_id}/Attachments")
            # 204 = no attachments (valid), 200 = has attachments
            if resp.status_code in (200, 204):
                _report("PASS", "Zoho CRM: Attachments endpoint accessible")
            else:
                _report("WARN", "Zoho CRM: Attachments endpoint", f"status {resp.status_code}")
        except Exception as exc:
            _report("WARN", "Zoho CRM: Attachments endpoint", str(exc))
    else:
        _report("WARN", "Zoho CRM: Attachments test skipped", "no deals to test against")

    # ── 5. Non-Zoho checks ──────────────────────────────────────────
    _run_non_zoho_checks(config)
    _summary()


def _run_non_zoho_checks(config) -> None:
    """NHTSA, Claude API, Teams webhook."""
    import requests as req

    # ── NHTSA ───────────────────────────────────────────────────────
    try:
        test_vin = "1HGCM82633A004352"
        resp = req.get(
            f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{test_vin}?format=json",
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json().get("Results", [{}])[0]
        make = result.get("Make", "")
        model = result.get("Model", "")
        year = result.get("ModelYear", "")
        _report("PASS", "NHTSA API", f"VIN decode returned Make={make}, Model={model}, Year={year}")
    except Exception as exc:
        _report("FAIL", "NHTSA API", str(exc))

    # ── Claude API ──────────────────────────────────────────────────
    try:
        client = ClaudeClient(api_key=config.anthropic_api_key)
        reply = client.simple_message("Reply with the single word OK.")
        _report("PASS", "Claude API", "Response received successfully")
    except Exception as exc:
        _report("FAIL", "Claude API", str(exc))

    # ── Teams webhook ───────────────────────────────────────────────
    try:
        notifier = TeamsNotifier(webhook_url=config.teams_webhook_url)
        ok = notifier.send_test()
        if ok:
            _report("PASS", "Teams Webhook", "Notification sent successfully")
        else:
            _report("WARN", "Teams Webhook", "POST succeeded but response was non-2xx")
    except Exception as exc:
        _report("FAIL", "Teams Webhook", str(exc))


def _suggest_alternatives(label: str, api_names: dict[str, str]) -> None:
    search_terms = label.lower().replace("_", " ").split()
    matches = []
    for api, display in api_names.items():
        combined = f"{api} {display}".lower()
        if any(term in combined for term in search_terms):
            matches.append(f"  {api} (display: {display})")
    if matches:
        print("       Possible alternatives:")
        for m in matches:
            print(f"         {m}")
    else:
        print(f"       No fields matching '{label}' found. Check all field names:")
        for api, display in sorted(api_names.items()):
            print(f"         {api} ({display})")


def _summary() -> None:
    print(f"\nCritical: {_fail} failures | Warnings: {_warn}")
    if _fail == 0:
        print("Ready to run in dry-run mode. Resolve warnings before live run for full functionality.")
    else:
        print("Fix critical failures before proceeding.")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
