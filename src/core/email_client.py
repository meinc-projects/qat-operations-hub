"""SendGrid email client for module completion reports."""

import requests

from src.core.logger import get_logger

logger = get_logger("hub.email_client")


class SendGridClient:
    """Send emails via the SendGrid v3 REST API."""

    def __init__(self, api_key: str, from_email: str, to_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email
        self.to_email = to_email

    def send(self, subject: str, html_body: str, plain_body: str = "") -> bool:
        """Send an email. Returns True on success, False on failure."""
        payload = {
            "personalizations": [{"to": [{"email": self.to_email}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": plain_body or subject},
                {"type": "text/html", "value": html_body},
            ],
        }
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            if resp.status_code < 300:
                logger.info("SendGrid email sent (status %d)", resp.status_code)
                return True
            logger.warning("SendGrid returned status %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("SendGrid email failed: %s", exc)
            return False
