# QAT Operations Hub — Project Summary

The QAT Operations Hub is a centralized Python automation platform for **Quick Auto Tags** (Mata Enterprises, Inc.), a California DMV-licensed vehicle tag and title agency. It runs as a Windows Service on a Windows VPS and provides shared infrastructure — Zoho OAuth management, Claude API integration, SQLite metrics, Microsoft Teams notifications, structured logging, and a FastAPI health/status server — so that pluggable business-automation modules can focus on their domain logic.

**Module 1 (Renewal Backfill)** processes thousands of 2025 Closed Won deals in Zoho CRM that are missing registration expiration dates. For each deal it downloads the attached registration card, uses Claude Vision to OCR the expiration date, decodes the VIN via NHTSA to enrich with year/make/model, writes the data back to the deal, creates a 2026 renewal deal, and generates a comprehensive data-quality audit report.

The architecture is designed so that future modules (SMS renewal outreach, RingCentral message intelligence, orphan deal resolution, duplicate contact merging, VIN validation, smog check automation) plug in under `src/modules/` by implementing the `BaseModule` interface — the Hub core handles everything else.
