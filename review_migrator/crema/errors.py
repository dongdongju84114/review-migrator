from __future__ import annotations

import json
from typing import Any


class CremaError(RuntimeError):
    pass


class CremaConfigurationError(CremaError):
    pass


class CremaHTTPError(CremaError):
    def __init__(self, status_code: int, message: str, response_body: object | None = None) -> None:
        super().__init__(f"CREMA API returned {status_code}: {message}")
        self.status_code = status_code
        self.response_body = response_body


SENSITIVE_RESPONSE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "client_secret",
}


def error_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def error_response_body_text(error: Exception, *, limit: int = 2000) -> str:
    body = getattr(error, "response_body", None)
    if body is None:
        return ""
    safe_body = _sanitize_response_body(body)
    if isinstance(safe_body, str):
        return safe_body[:limit]
    return json.dumps(safe_body, ensure_ascii=False, sort_keys=True)[:limit]


def _sanitize_response_body(value: Any) -> Any:
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_RESPONSE_KEYS:
                safe[key_text] = "***"
            else:
                safe[key_text] = _sanitize_response_body(item)
        return safe
    if isinstance(value, list):
        return [_sanitize_response_body(item) for item in value]
    return value
