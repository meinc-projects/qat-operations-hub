"""RingCentral JWT auth manager — placeholder for future modules.

This module will manage the RingCentral authentication lifecycle when
SMS and messaging modules are implemented. Not required for Module 1.
"""

from src.core.logger import get_logger

logger = get_logger("hub.ringcentral_auth")


class RingCentralAuthManager:
    """Placeholder — implements RingCentral JWT auth for future modules."""

    def __init__(self, client_id: str, client_secret: str, jwt: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt = jwt
        self._access_token: str | None = None

    def get_access_token(self) -> str:
        raise NotImplementedError("RingCentral auth not yet implemented")
