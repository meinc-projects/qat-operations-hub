"""Completion reporting for CRM Enrichment — Telegram + SendGrid email."""

from datetime import datetime, timezone
from typing import Any

from src.core.logger import get_logger

logger = get_logger("hub.crm_enrichment.report")


def send_completion_report(
    notifier: Any,
    email_client: Any | None,
    *,
    module_name: str,
    year: int,
    month: int,
    total: int,
    processed: int,
    succeeded: int,
    failed: int,
    skipped: int,
    errors: dict[str, int],
    duration_seconds: int,
) -> None:
    """Send completion summary via Telegram and (optionally) email."""

    # Telegram summary
    notifier.send_summary(
        module_name=module_name,
        status="completed" if failed == 0 else "completed_with_errors",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        duration_seconds=duration_seconds,
        error_summary=errors if errors else None,
    )

    # Email report via SendGrid
    if email_client:
        html = _build_html_report(
            year=year,
            month=month,
            total=total,
            processed=processed,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_seconds=duration_seconds,
        )
        subject = f"CRM Enrichment Report — {month:02d}/{year}"
        email_client.send(subject=subject, html_body=html, plain_body=subject)
    else:
        logger.info("SendGrid not configured — skipping email report")


def _build_html_report(
    *,
    year: int,
    month: int,
    total: int,
    processed: int,
    succeeded: int,
    failed: int,
    skipped: int,
    errors: dict[str, int],
    duration_seconds: int,
) -> str:
    minutes = duration_seconds // 60
    seconds = duration_seconds % 60
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    error_rows = ""
    if errors:
        sorted_errors = sorted(errors.items(), key=lambda x: x[1], reverse=True)
        for reason, count in sorted_errors:
            error_rows += f"<tr><td>{reason}</td><td>{count}</td></tr>\n"

    return f"""<!DOCTYPE html>
<html>
<head><style>
  body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
  h2 {{ color: #333; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background: #f5f5f5; }}
  .success {{ color: #28a745; }}
  .failure {{ color: #dc3545; }}
</style></head>
<body>
  <h2>CRM Enrichment Report &mdash; {month:02d}/{year}</h2>
  <p>Generated: {timestamp}</p>

  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Total deals in range</td><td>{total}</td></tr>
    <tr><td>Processed (missing expiration)</td><td>{processed}</td></tr>
    <tr><td class="success">Succeeded</td><td>{succeeded}</td></tr>
    <tr><td class="failure">Failed</td><td>{failed}</td></tr>
    <tr><td>Skipped (already processed)</td><td>{skipped}</td></tr>
    <tr><td>Duration</td><td>{minutes}m {seconds}s</td></tr>
  </table>

  {"<h3>Error Breakdown</h3><table><tr><th>Reason</th><th>Count</th></tr>" + error_rows + "</table>" if error_rows else ""}
</body>
</html>"""
