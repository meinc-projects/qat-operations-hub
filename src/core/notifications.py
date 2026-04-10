"""Send notifications via Telegram Bot API."""

import traceback
from datetime import datetime, timezone
from typing import Any

import requests

from src.core.logger import get_logger

logger = get_logger("hub.notifications")

_TELEGRAM_MAX_LENGTH = 4096


class TelegramNotifier:
    """Send notifications to Telegram via Bot API using HTML formatting."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _send(self, text: str) -> bool:
        """Post a message to the configured Telegram chat."""
        if len(text) > _TELEGRAM_MAX_LENGTH:
            text = text[: _TELEGRAM_MAX_LENGTH - 20] + "\n\n[truncated]"

        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.status_code < 300:
                logger.debug("Telegram notification sent successfully")
                return True
            logger.warning("Telegram API returned status %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("Failed to send Telegram notification: %s", exc)
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
        """Send a run-complete summary message."""
        icon = "\u2705" if status == "completed" else "\u274c"
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60

        lines = [
            f"{icon} <b>QAT Hub \u2014 {module_name} run {status}</b>",
            "",
            f"<b>Module:</b> {module_name}",
            f"<b>Status:</b> {status.upper()}",
            f"<b>Processed:</b> {processed}",
            f"<b>Succeeded:</b> {succeeded}",
            f"<b>Failed:</b> {failed}",
            f"<b>Skipped:</b> {skipped}",
            f"<b>Duration:</b> {minutes}m {seconds}s",
        ]

        if error_summary:
            top = sorted(error_summary.items(), key=lambda x: x[1], reverse=True)[:5]
            errors_text = ", ".join(f"{k}: {v}" for k, v in top)
            lines.append(f"<b>Top errors:</b> {errors_text}")

        return self._send("\n".join(lines))

    def send_critical(
        self,
        module_name: str,
        error: Exception,
    ) -> bool:
        """Send a critical-failure notification with truncated stack trace."""
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text = "".join(tb)[-500:]

        lines = [
            f"\u26a0\ufe0f <b>CRITICAL \u2014 {module_name} crashed</b>",
            "",
            f"<b>Module:</b> {module_name}",
            f"<b>Error:</b> {type(error).__name__}: {error}",
            f"<b>Time:</b> {datetime.now(timezone.utc).isoformat()}",
            "",
            f"<pre>{_escape_html(tb_text)}</pre>",
        ]
        return self._send("\n".join(lines))

    def send_warning(self, module_name: str, message: str) -> bool:
        """Send a warning notification."""
        lines = [
            f"\u26a0\ufe0f <b>Warning \u2014 {module_name}</b>",
            "",
            f"<b>Module:</b> {module_name}",
            f"<b>Details:</b> {_escape_html(message)}",
            f"<b>Time:</b> {datetime.now(timezone.utc).isoformat()}",
        ]
        return self._send("\n".join(lines))

    def send_test(self) -> bool:
        """Send a simple test message to verify the bot works."""
        lines = [
            "\u2705 <b>QAT Operations Hub \u2014 Test Notification</b>",
            "",
            f"<b>Status:</b> Telegram bot is working",
            f"<b>Time:</b> {datetime.now(timezone.utc).isoformat()}",
        ]
        return self._send("\n".join(lines))

    def send_progress(self, module_name: str, processed: int, total: int, message: str = "") -> bool:
        """Send a progress heartbeat (used by enrichment module every N deals)."""
        pct = (processed / total * 100) if total else 0
        lines = [
            f"\U0001f4ca <b>{module_name} \u2014 Progress</b>",
            "",
            f"<b>Processed:</b> {processed} / {total} ({pct:.0f}%)",
        ]
        if message:
            lines.append(f"<b>Note:</b> {message}")
        return self._send("\n".join(lines))


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
