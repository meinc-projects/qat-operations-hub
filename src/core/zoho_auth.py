import time
from typing import Any

import requests

from src.core.logger import get_logger

logger = get_logger("hub.zoho_auth")

_MAX_RETRIES = 4
_BACKOFF_SEQUENCE = [2, 4, 8, 16]
_REFRESH_COOLDOWN = 30  # seconds between token refresh attempts


class ZohoAuthManager:
    """Manages the Zoho OAuth 2.0 access-token lifecycle.

    * Stores the current access token in memory.
    * Automatically refreshes when expired or within 5 minutes of expiry.
    * Provides ``make_request`` that injects auth and handles 401/429.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_domain: str,
        api_domain: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.accounts_domain = accounts_domain.rstrip("/")
        self.api_domain = api_domain.rstrip("/")

        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._last_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _refresh_access_token(self) -> None:
        now = time.time()
        if self._access_token and now - self._last_refresh < _REFRESH_COOLDOWN:
            logger.debug("Skipping refresh — last refresh was %ds ago", int(now - self._last_refresh))
            return

        url = f"{self.accounts_domain}/oauth/v2/token"
        params = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }

        for attempt in range(3):
            resp = requests.post(url, params=params, timeout=30)

            if resp.status_code == 400 and "too many requests" in resp.text.lower():
                wait = 30 * (attempt + 1)
                logger.warning("Zoho rate-limited token refresh — waiting %ds before retry", wait)
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                logger.error("Token refresh failed (%d): %s", resp.status_code, resp.text[:300])
                raise RuntimeError(f"Zoho token refresh failed: {resp.status_code} {resp.text[:200]}")

            data = resp.json()
            if "access_token" not in data:
                logger.error("Token refresh response missing access_token: %s", data)
                raise RuntimeError(f"Zoho token refresh failed: {data}")

            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            self._token_expiry = time.time() + expires_in
            self._last_refresh = time.time()
            logger.info("Zoho access token refreshed — expires in %d s", expires_in)
            return

        raise RuntimeError("Zoho token refresh failed after 3 attempts — rate-limited")

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token is None or time.time() >= (self._token_expiry - 300):
            self._refresh_access_token()
        return self._access_token  # type: ignore[return-value]

    @property
    def is_token_valid(self) -> bool:
        return self._access_token is not None and time.time() < self._token_expiry

    # ------------------------------------------------------------------
    # Authenticated HTTP helper
    # ------------------------------------------------------------------

    def make_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Send an HTTP request with Zoho auth header.

        Handles:
        * 401 — refreshes the token once and retries.
        * 429 — honours ``Retry-After`` or falls back to exponential backoff.
        """
        token = self.get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Zoho-oauthtoken {token}"

        request_kwargs = {**kwargs, "headers": headers}
        request_kwargs.setdefault("timeout", 60)

        for attempt in range(_MAX_RETRIES):
            resp = requests.request(method, url, **request_kwargs)

            if resp.status_code == 401:
                logger.warning("Received 401 on %s — refreshing token and retrying", url)
                try:
                    self._refresh_access_token()
                except RuntimeError as exc:
                    logger.error("Token refresh failed after 401: %s", exc)
                    return resp
                request_kwargs["headers"]["Authorization"] = f"Zoho-oauthtoken {self._access_token}"
                resp = requests.request(method, url, **request_kwargs)
                return resp

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else _BACKOFF_SEQUENCE[min(attempt, len(_BACKOFF_SEQUENCE) - 1)]
                logger.warning("Rate-limited (429) — waiting %d s before retry %d/%d", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
                continue

            return resp

        logger.error("Request to %s failed after %d retries (last status %d)", url, _MAX_RETRIES, resp.status_code)
        return resp  # type: ignore[possibly-undefined]
