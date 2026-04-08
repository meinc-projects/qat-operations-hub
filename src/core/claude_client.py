import json
import time
from typing import Any

import anthropic

from src.core.logger import get_logger

logger = get_logger("hub.claude_client")

MODEL = "claude-sonnet-4-20250514"
_MAX_RETRIES = 3
_BACKOFF_BASE = 2


class ClaudeClient:
    """Wrapper around the Anthropic Python SDK for Vision OCR and text analysis."""

    def __init__(self, api_key: str, metrics_collector: Any | None = None) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.metrics = metrics_collector

    def _call_with_retry(self, **kwargs: Any) -> anthropic.types.Message:
        """Call messages.create with retry logic on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self.client.messages.create(**kwargs)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                last_exc = exc
                wait = _BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "Claude API error (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def _record_usage(self, response: anthropic.types.Message, run_id: str | None, endpoint: str) -> dict:
        """Log token usage and optionally record to metrics DB."""
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        cost = (usage["input_tokens"] * 3.0 / 1_000_000) + (usage["output_tokens"] * 15.0 / 1_000_000)
        usage["cost_estimate"] = round(cost, 6)
        logger.debug("Claude usage — input=%d, output=%d, est_cost=$%.6f", usage["input_tokens"], usage["output_tokens"], cost)

        if self.metrics and run_id:
            self.metrics.record_api_usage(
                run_id=run_id,
                service="claude_vision",
                endpoint=endpoint,
                tokens=usage["input_tokens"] + usage["output_tokens"],
                cost=cost,
            )
        return usage

    def analyze_image(
        self,
        base64_data: str,
        media_type: str,
        prompt: str,
        *,
        run_id: str | None = None,
        max_tokens: int = 500,
    ) -> dict:
        """Send an image (JPEG/PNG) to Claude Vision and return the parsed response."""
        response = self._call_with_retry(
            model=MODEL,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        usage = self._record_usage(response, run_id, "analyze_image")
        text = response.content[0].text
        return {"text": text, "usage": usage}

    def analyze_document(
        self,
        base64_data: str,
        prompt: str,
        *,
        run_id: str | None = None,
        max_tokens: int = 500,
    ) -> dict:
        """Send a PDF document to Claude and return the parsed response."""
        response = self._call_with_retry(
            model=MODEL,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        usage = self._record_usage(response, run_id, "analyze_document")
        text = response.content[0].text
        return {"text": text, "usage": usage}

    def simple_message(self, prompt: str, max_tokens: int = 100) -> str:
        """Send a plain text message — used for connectivity testing."""
        response = self._call_with_retry(
            model=MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
