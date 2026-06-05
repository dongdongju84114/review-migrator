from __future__ import annotations

import time
from typing import Any

from .auth import TokenProvider
from .errors import CremaConfigurationError, CremaHTTPError


class CremaClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.cre.ma",
        token_provider: TokenProvider,
        session: Any | None = None,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.session = session or self._default_session()
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | list[tuple[str, Any]] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        attempts = 0
        refreshed_after_401 = False
        while True:
            token = self.token_provider.get_token()
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=self._params_with_token(params, token),
                data=self._data_with_token(data, token),
                json=json,
            )
            if response.status_code == 401 and not refreshed_after_401:
                self.token_provider.refresh_token()
                refreshed_after_401 = True
                continue
            if response.status_code == 429 or response.status_code >= 500:
                attempts += 1
                if attempts <= self.max_retries:
                    if self.retry_sleep:
                        time.sleep(self.retry_sleep * attempts)
                    continue
            if response.status_code >= 400:
                raise CremaHTTPError(response.status_code, "request failed", self._response_body(response))
            if response.status_code == 204:
                return None
            return self._response_body(response)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, data: dict[str, Any] | list[tuple[str, Any]] | None = None) -> Any:
        return self.request("POST", path, data=data)

    def patch(self, path: str, *, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> Any:
        return self.request("PATCH", path, params=params, data=data)

    @staticmethod
    def _params_with_token(params: dict[str, Any] | None, token: str) -> dict[str, Any]:
        merged = dict(params or {})
        merged.setdefault("access_token", token)
        return merged

    @staticmethod
    def _data_with_token(
        data: dict[str, Any] | list[tuple[str, Any]] | None,
        token: str,
    ) -> dict[str, Any] | list[tuple[str, Any]]:
        if isinstance(data, list):
            return [("access_token", token), *data]
        merged = dict(data or {})
        merged.setdefault("access_token", token)
        return merged

    @staticmethod
    def _response_body(response: Any) -> Any:
        try:
            return response.json()
        except Exception:
            return getattr(response, "text", "")

    @staticmethod
    def _default_session() -> Any:
        try:
            import httpx
        except ImportError:
            from .http_session import UrllibSession

            return UrllibSession(timeout=30)
        return httpx.Client(timeout=30)
