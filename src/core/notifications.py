import json
import traceback
from datetime import datetime, timezone
from typing import Any

import requests

from src.core.logger import get_logger

logger = get_logger("hub.notifications")


class TeamsNotifier:
    """Send notifications to Microsoft Teams via incoming webhook using Adaptive Cards."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def _post_card(self, card: dict) -> bool:
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code < 300:
                logger.debug("Teams notification sent successfully")
                return True
            logger.warning("Teams webhook returned status %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("Failed to send Teams notification: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    def send_summary(
        self,
        module_name: str,
        status: str,
        processed: int,
        succeeded: int,
        failed: int,
        skipped: int,
        duration_seconds: int,
        error_summary: dict[str, int] | None = None,
    ) -> bool:
        """Send a run-complete summary card."""
        colour = "Good" if status == "completed" else "Attention"
        facts = [
            {"title": "Module", "value": module_name},
            {"title": "Status", "value": status.upper()},
            {"title": "Processed", "value": str(processed)},
            {"title": "Succeeded", "value": str(succeeded)},
            {"title": "Failed", "value": str(failed)},
            {"title": "Skipped", "value": str(skipped)},
            {"title": "Duration", "value": f"{duration_seconds // 60}m {duration_seconds % 60}s"},
        ]
        if error_summary:
            top = sorted(error_summary.items(), key=lambda x: x[1], reverse=True)[:5]
            facts.append({"title": "Top errors", "value": ", ".join(f"{k}: {v}" for k, v in top)})

        card = self._build_card(
            title=f"QAT Hub — {module_name} run {status}",
            colour=colour,
            facts=facts,
        )
        return self._post_card(card)

    def send_critical(
        self,
        module_name: str,
        error: Exception,
    ) -> bool:
        """Send a critical-failure notification with truncated stack trace."""
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text = "".join(tb)[-500:]
        card = self._build_card(
            title=f"CRITICAL — {module_name} crashed",
            colour="Attention",
            facts=[
                {"title": "Module", "value": module_name},
                {"title": "Error", "value": f"{type(error).__name__}: {error}"},
                {"title": "Traceback (last 500 chars)", "value": f"```{tb_text}```"},
                {"title": "Time", "value": datetime.now(timezone.utc).isoformat()},
            ],
        )
        return self._post_card(card)

    def send_warning(self, module_name: str, message: str) -> bool:
        card = self._build_card(
            title=f"Warning — {module_name}",
            colour="Warning",
            facts=[
                {"title": "Module", "value": module_name},
                {"title": "Details", "value": message},
                {"title": "Time", "value": datetime.now(timezone.utc).isoformat()},
            ],
        )
        return self._post_card(card)

    def send_test(self) -> bool:
        """Send a simple test card to verify the webhook works."""
        card = self._build_card(
            title="QAT Operations Hub — Test Notification",
            colour="Good",
            facts=[
                {"title": "Status", "value": "Webhook is working"},
                {"title": "Time", "value": datetime.now(timezone.utc).isoformat()},
            ],
        )
        return self._post_card(card)

    # ------------------------------------------------------------------
    # Card builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_card(title: str, colour: str, facts: list[dict[str, str]]) -> dict:
        body: list[dict] = [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": title,
                "color": colour,
            }
        ]
        for fact in facts:
            body.append(
                {
                    "type": "FactSet",
                    "facts": [{"title": fact["title"], "value": fact["value"]}],
                }
            )
        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }
