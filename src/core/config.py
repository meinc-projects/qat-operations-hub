import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _require(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        print(f"FATAL: Required environment variable '{var_name}' is missing or empty.", file=sys.stderr)
        print(f"       Copy .env.template to .env and fill in all required values.", file=sys.stderr)
        sys.exit(1)
    return value


def _optional(var_name: str, default: str = "") -> str:
    return os.getenv(var_name, default).strip()


@dataclass(frozen=True)
class ZohoConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    api_domain: str
    accounts_domain: str


@dataclass(frozen=True)
class BackfillConfig:
    dry_run: bool
    batch_size: int
    year: int
    renewal_year: int
    days_before_expiry: int
    skip_renewals: bool
    start_date: str
    end_date: str


@dataclass(frozen=True)
class CRMFieldConfig:
    expiration_date: str
    vin: str
    vehicle_ymm: str
    stage: str
    contact: str
    account: str
    amount: str
    closing_date: str


@dataclass(frozen=True)
class RingCentralConfig:
    client_id: str = ""
    client_secret: str = ""
    jwt: str = ""
    from_number: str = ""


@dataclass(frozen=True)
class Config:
    zoho: ZohoConfig
    anthropic_api_key: str
    teams_webhook_url: str
    hub_host: str
    hub_port: int
    log_level: str
    backfill: BackfillConfig
    crm_fields: CRMFieldConfig
    ringcentral: RingCentralConfig
    zoho_books_org_id: str = ""
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)


def load_config() -> Config:
    """Load and validate all configuration from environment variables."""

    zoho = ZohoConfig(
        client_id=_require("ZOHO_CLIENT_ID"),
        client_secret=_require("ZOHO_CLIENT_SECRET"),
        refresh_token=_require("ZOHO_REFRESH_TOKEN"),
        api_domain=_optional("ZOHO_CRM_API_DOMAIN", "https://www.zohoapis.com"),
        accounts_domain=_optional("ZOHO_CRM_ACCOUNTS_DOMAIN", "https://accounts.zoho.com"),
    )

    year = int(_optional("BACKFILL_YEAR", "2025"))
    backfill = BackfillConfig(
        dry_run=_optional("BACKFILL_DRY_RUN", "true").lower() == "true",
        batch_size=int(_optional("BACKFILL_BATCH_SIZE", "50")),
        year=year,
        renewal_year=int(_optional("BACKFILL_RENEWAL_YEAR", "2026")),
        days_before_expiry=int(_optional("BACKFILL_DAYS_BEFORE_EXPIRY", "45")),
        skip_renewals=_optional("BACKFILL_SKIP_RENEWALS", "true").lower() == "true",
        start_date=_optional("BACKFILL_START_DATE", f"{year}-01-01"),
        end_date=_optional("BACKFILL_END_DATE", f"{year}-12-31"),
    )

    crm_fields = CRMFieldConfig(
        expiration_date=_optional("CRM_FIELD_EXPIRATION_DATE", "Expiration_Date"),
        vin=_optional("CRM_FIELD_VIN", "VIN"),
        vehicle_ymm=_optional("CRM_FIELD_VEHICLE_YMM", "Year_Make_Model"),
        stage=_optional("CRM_FIELD_STAGE", "Stage"),
        contact=_optional("CRM_FIELD_CONTACT", "Contact_Name"),
        account=_optional("CRM_FIELD_ACCOUNT", "Account_Name"),
        amount=_optional("CRM_FIELD_AMOUNT", "Amount"),
        closing_date=_optional("CRM_FIELD_CLOSING_DATE", "Closing_Date"),
    )

    ringcentral = RingCentralConfig(
        client_id=_optional("RC_CLIENT_ID"),
        client_secret=_optional("RC_CLIENT_SECRET"),
        jwt=_optional("RC_JWT"),
        from_number=_optional("RC_FROM_NUMBER"),
    )

    return Config(
        zoho=zoho,
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        teams_webhook_url=_require("TEAMS_WEBHOOK_URL"),
        hub_host=_optional("HUB_HOST", "0.0.0.0"),
        hub_port=int(_optional("HUB_PORT", "8100")),
        log_level=_optional("LOG_LEVEL", "INFO"),
        backfill=backfill,
        crm_fields=crm_fields,
        ringcentral=ringcentral,
        zoho_books_org_id=_optional("ZOHO_BOOKS_ORG_ID"),
    )
