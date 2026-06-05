from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .errors import CremaConfigurationError, CremaHTTPError


@dataclass
class OAuthToken:
    access_token: str
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at


class TokenProvider:
    def __init__(
        self,
        *,
        base_url: str,
        app_id: str | None = None,
        secret: str | None = None,
        access_token: str | None = None,
        session: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.secret = secret
        self.session = session
        self.token = OAuthToken(access_token=access_token) if access_token else None
        self.refresh_count = 0

    def get_token(self) -> str:
        if self.token and not self.token.is_expired:
            return self.token.access_token
        return self.refresh_token()

    def refresh_token(self) -> str:
        if not self.app_id or not self.secret:
            raise CremaConfigurationError("CREMA_APP_ID and CREMA_SECRET are required to refresh token")
        session = self.session or _default_httpx_client()
        response = session.request(
            "POST",
            f"{self.base_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.secret,
            },
        )
        if response.status_code >= 400:
            raise CremaHTTPError(response.status_code, "token refresh failed", _response_body(response))
        body = response.json()
        created_at = body.get("created_at")
        expires_in = body.get("expires_in")
        expires_at = None
        if created_at and expires_in:
            expires_at = datetime.fromtimestamp(int(created_at), tz=timezone.utc) + timedelta(seconds=int(expires_in))
        self.token = OAuthToken(access_token=body["access_token"], expires_at=expires_at)
        self.refresh_count += 1
        return self.token.access_token


def _default_httpx_client() -> Any:
    try:
        import httpx
    except ImportError:
        from .http_session import UrllibSession

        return UrllibSession(timeout=30)
    return httpx.Client(timeout=30)


def _response_body(response: Any) -> object:
    try:
        return response.json()
    except Exception:
        return getattr(response, "text", "")
