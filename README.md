# QAT Operations Hub

Centralized automation platform for **Quick Auto Tags** (Mata Enterprises, Inc.), a California DMV-licensed vehicle tag and title agency. Runs as a Windows Service, providing shared infrastructure and hosting pluggable automation modules.

## What It Does

The Hub provides:

- **Zoho OAuth 2.0 lifecycle management** — automatic token refresh, 401/429 handling
- **Claude API client** — Vision OCR and document analysis with retry logic
- **SQLite metrics** — tracks every module run, event, and API call
- **Telegram notifications** — summary, warning, critical, and progress alerts
- **SendGrid email** — module completion reports delivered to inbox
- **Structured logging** — rotating file + stdout with per-module namespaces
- **FastAPI server** — health, metrics, status, and on-demand module execution endpoints
- **Module registry** — auto-discovers modules, isolates crashes, manages lifecycle

### Module 1: CRM Renewal Backfill

Processes 2025 Closed Won deals in Zoho CRM that are missing registration expiration dates:

1. Queries target deals via COQL (paginated)
2. Downloads registration card attachments
3. OCRs the card via Claude Vision to extract expiration date
4. Decodes VIN via NHTSA API for year/make/model
5. Writes enriched data back to the deal
6. Creates a 2026 renewal deal (with duplicate prevention)
7. Generates a data-quality audit report (JSON + CSV)

### Module 2: CRM Enrichment

Enriches Closed Won deals for a target month/year that are missing the `Reg_Expiration` field:

1. Fetches all Closed Won deals for the target month via COQL (paginated)
2. Filters to deals missing `Reg_Expiration` in Python
3. Downloads registration card attachments (tries up to 3 per deal)
4. OCRs the card via Claude Vision (Opus) to extract expiration date
5. Extracts VIN from Deal_Name and decodes via NHTSA API
6. Writes `Reg_Expiration`, `Year_Make_Model`, and `VIN_Number1` back to the deal
7. Saves progress after every deal for resumability
8. Sends Telegram heartbeat every 200 deals
9. Sends Telegram + email report on completion

---

## Prerequisites

- Python 3.11+ installed on Windows VPS
- Anthropic API key
- Zoho CRM Self Client with OAuth credentials and required scopes
- Telegram bot token and chat ID
- [NSSM](https://nssm.cc/) installed for Windows Service management
- Git

---

## Zoho CRM Setup

### Required OAuth Scopes

These must be set on your Zoho API Console Self Client before generating the refresh token:

```
ZohoCRM.modules.deals.ALL
ZohoCRM.modules.contacts.ALL
ZohoCRM.modules.accounts.ALL
ZohoCRM.modules.attachments.ALL
ZohoCRM.settings.ALL
ZohoCRM.coql.READ
ZohoCRM.files.READ
```

### CRM Fields

The modules use these CRM field API names (configurable via `.env`):

| Field | API Name | Purpose |
|-------|----------|---------|
| Registration Expiration | `Reg_Expiration` | Expiration date from OCR |
| VIN | `VIN_Number1` | Vehicle identification number |
| Year Make Model | `Year_Make_Model` | Combined vehicle info from NHTSA decode |

> The modules run without `Year_Make_Model` — VIN decode data will be logged but not written to deals. A warning is shown at startup.

### Renewals Pipeline (Optional)

Create a pipeline called **Renewals** in the Deals module for renewal deals. If it doesn't exist, renewal deals will go to the default pipeline (a warning is logged).

---

## File Structure

```
qat-operations-hub/
├── src/
│   ├── core/
│   │   ├── config.py               # Env var loading + validation
│   │   ├── zoho_auth.py            # Zoho OAuth 2.0 token lifecycle
│   │   ├── ringcentral_auth.py     # RingCentral JWT auth (placeholder)
│   │   ├── claude_client.py        # Claude API wrapper (Vision + text)
│   │   ├── metrics.py              # SQLite-backed metrics collector
│   │   ├── notifications.py        # Telegram bot notifier
│   │   ├── email_client.py         # SendGrid email delivery
│   │   ├── logger.py               # Structured logging with rotation
│   │   ├── module_registry.py      # BaseModule ABC + registry
│   │   └── server.py               # FastAPI health/metrics/run endpoints
│   ├── modules/
│   │   ├── renewal_backfill/
│   │   │   ├── module.py           # Module entry point (BaseModule impl)
│   │   │   ├── crm_queries.py      # COQL queries and CRM API operations
│   │   │   ├── attachment_handler.py  # Download + identify reg cards
│   │   │   ├── ocr_processor.py    # Claude Vision OCR
│   │   │   ├── vin_decoder.py      # NHTSA vPIC API
│   │   │   ├── deal_enricher.py    # Write-back enriched data
│   │   │   ├── renewal_creator.py  # Create renewal deals
│   │   │   └── audit_reporter.py   # Data quality audit reports
│   │   └── crm_enrichment/
│   │       ├── module.py           # Module entry point (BaseModule impl)
│   │       ├── crm_queries.py      # COQL queries and CRM operations
│   │       ├── ocr_processor.py    # Claude Vision OCR (Opus model)
│   │       ├── vin_decoder.py      # VIN extraction + NHTSA decode
│   │       └── report.py           # Completion reporting (Telegram + email)
│   └── main.py                     # Application entry point
├── tests/
│   ├── test_connection.py          # Pre-flight API connectivity test
│   ├── test_zoho_fields.py         # CRM field name validation
│   └── test_nhtsa.py               # NHTSA VIN decode test
├── docs/
│   └── ADDING_MODULES.md           # Guide for creating new modules
├── logs/                           # Log files (gitignored)
├── data/                           # SQLite DB + audit reports (gitignored)
├── .env.template                   # All env vars with blank values
├── .gitignore
├── requirements.txt
├── README.md
└── PROJECT_SUMMARY.md
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ZOHO_CLIENT_ID` | Yes | — | Zoho Self Client OAuth client ID |
| `ZOHO_CLIENT_SECRET` | Yes | — | Zoho Self Client OAuth client secret |
| `ZOHO_REFRESH_TOKEN` | Yes | — | Zoho OAuth refresh token |
| `ZOHO_CRM_API_DOMAIN` | No | `https://www.zohoapis.com` | Zoho CRM API base URL |
| `ZOHO_CRM_ACCOUNTS_DOMAIN` | No | `https://accounts.zoho.com` | Zoho accounts domain for token refresh |
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic Claude API key |
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | Yes | — | Telegram chat ID for notifications |
| `HUB_HOST` | No | `0.0.0.0` | FastAPI listen address |
| `HUB_PORT` | No | `8100` | FastAPI listen port |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `BACKFILL_DRY_RUN` | No | `true` | **Must be true for first run** |
| `BACKFILL_BATCH_SIZE` | No | `50` | Processing batch size |
| `BACKFILL_YEAR` | No | `2025` | Source deal year |
| `BACKFILL_RENEWAL_YEAR` | No | `2026` | Renewal deal year |
| `BACKFILL_DAYS_BEFORE_EXPIRY` | No | `45` | Days before expiry for renewal closing date |
| `ENRICHMENT_TARGET_YEAR` | No | `2025` | Target year for CRM enrichment |
| `ENRICHMENT_TARGET_MONTH` | No | — | Target month (1-12) for CRM enrichment |
| `ENRICHMENT_DRY_RUN` | No | `true` | **Must be true for first run** |
| `ENRICHMENT_BATCH_SIZE` | No | `200` | COQL page size for enrichment |
| `CRM_FIELD_EXPIRATION_DATE` | No | `Reg_Expiration` | CRM field API name |
| `CRM_FIELD_VIN` | No | `VIN_Number1` | CRM field API name |
| `CRM_FIELD_VEHICLE_YMM` | No | `Year_Make_Model` | CRM field API name |
| `CRM_FIELD_STAGE` | No | `Stage` | CRM field API name |
| `CRM_FIELD_CONTACT` | No | `Contact_Name` | CRM field API name |
| `CRM_FIELD_AMOUNT` | No | `Amount` | CRM field API name |
| `CRM_FIELD_CLOSING_DATE` | No | `Closing_Date` | CRM field API name |
| `SENDGRID_API_KEY` | No | — | SendGrid API key for email reports |
| `SENDGRID_FROM_EMAIL` | No | — | Verified sender email address |
| `SENDGRID_TO_EMAIL` | No | — | Report recipient email address |
| `RC_CLIENT_ID` | No | — | RingCentral (future modules) |
| `RC_CLIENT_SECRET` | No | — | RingCentral (future modules) |
| `RC_JWT` | No | — | RingCentral (future modules) |
| `RC_FROM_NUMBER` | No | — | RingCentral (future modules) |
| `ZOHO_BOOKS_ORG_ID` | No | — | Zoho Books (future modules) |

---

## Setup From Scratch

```bash
# 1. Clone the repo
git clone <repo-url> C:\QATHub
cd C:\QATHub

# 2. Create .env from template
copy .env.template .env

# 3. Fill in credentials in .env (Zoho, Anthropic, Telegram)

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run pre-flight connection test
python tests/test_connection.py

# 6. Resolve any [FAIL] items shown in the output

# 7. Run dry run (ALWAYS do this first)
python src/main.py --run crm_enrichment --dry-run

# 8. Review the output in logs/hub.log

# 9. When satisfied, run live
python src/main.py --run crm_enrichment
```

---

## How to Run

```bash
# CRM Enrichment — dry run (ALWAYS do this first)
python src/main.py --run crm_enrichment --dry-run

# CRM Enrichment — live run
python src/main.py --run crm_enrichment

# Renewal Backfill — dry run
python src/main.py --run renewal_backfill --dry-run

# Renewal Backfill — live run
python src/main.py --run renewal_backfill

# Service mode — starts FastAPI server, modules triggered via API
python src/main.py --serve
```

---

## How to Restart

```bash
nssm restart QATOperationsHub
```

---

## NSSM Windows Service Setup

```bash
nssm install QATOperationsHub "C:\Python311\python.exe" "C:\QATHub\src\main.py --serve"
nssm set QATOperationsHub AppDirectory "C:\QATHub"
nssm set QATOperationsHub DisplayName "QAT Operations Hub"
nssm set QATOperationsHub Description "Centralized automation platform for Quick Auto Tags"
nssm set QATOperationsHub Start SERVICE_AUTO_START
nssm set QATOperationsHub AppStdout "C:\QATHub\logs\service_stdout.log"
nssm set QATOperationsHub AppStderr "C:\QATHub\logs\service_stderr.log"
nssm start QATOperationsHub
```

---

## Monitoring

| What | How |
|------|-----|
| Health check | `GET http://localhost:8100/health` |
| All module metrics | `GET http://localhost:8100/metrics` |
| Module status | `GET http://localhost:8100/status/crm_enrichment` |
| Trigger enrichment | `POST http://localhost:8100/run/crm_enrichment` (body: `{"dry_run": true, "target_month": 1}`) |
| Trigger backfill | `POST http://localhost:8100/run/renewal_backfill` (body: `{"dry_run": true}`) |
| Logs | `logs/hub.log` (rotated at 10 MB, 5 backups) |
| Audit reports | `data/audit_report_*.json` and `data/audit_report_*.csv` |

---

## Adding New Modules

See [docs/ADDING_MODULES.md](docs/ADDING_MODULES.md) for the `BaseModule` interface and step-by-step instructions.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Authentication failed" / token errors | Refresh token may have expired. Regenerate via Zoho API Console (Self Client) and update `.env`. |
| "Field not found" | Run `python tests/test_connection.py` to check field API names. Update `CRM_FIELD_*` in `.env` if they differ. |
| "429 Too Many Requests" | Zoho rate-limited — the backoff handler retries automatically. If persistent, reduce batch size or add delays. |
| Module appears stuck | Check `logs/hub.log` for the last processed deal. Restart the service (`nssm restart QATOperationsHub`). The module is resumable — already-processed deals are skipped on the next run. |
| "Could not process PDF" | Intermittent Anthropic API issue (<1% of PDFs). The retry logic handles most cases. If a specific file always fails, check its format. |
| Telegram notifications not arriving | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Run `python tests/test_connection.py` to test the bot. |

---

## Security Notes

- **Dry run is default.** Both modules default to `DRY_RUN=true` — never set to `false` without reviewing dry-run output.
- **Sensitive documents.** Registration cards are processed in memory and never persisted to disk.
- **Rotate exposed tokens.** If any Zoho token was shared in chat or logs, revoke it immediately via the Zoho API Console.
- **`.env` is gitignored.** Never commit credentials to version control.
