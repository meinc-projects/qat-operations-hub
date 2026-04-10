"""SendGrid email client for module completion reports."""

import json
import urllib.request

from src.core.logger import get_logger

logger = get_logger("hub.email_client")


class SendGridClient:
    """Send emails via the SendGrid v3 REST API (no pip dependency)."""

    def __init__(self, api_key: str, from_email: str, to_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email
        self.to_email = to_email

    def send(self, subject: str, html_body: str, plain_body: str = "") -> bool:
        """Send an email. Returns True on success, False on failure."""
        payload = json.dumps({
            "personalizations": [{"to": [{"email": self.to_email}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": plain_body or subject},
                {"type": "text/html", "value": html_body},
            ],
        }).encode()

        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                logger.info("SendGrid email sent (status %d)", resp.status)
                return True
        except Exception as exc:
            logger.error("SendGrid email failed: %s", exc)
            return False
