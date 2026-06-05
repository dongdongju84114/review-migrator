from __future__ import annotations

from pathlib import Path
from typing import Any

from review_migrator.utils import dumps_json, now_kst, safe_token

SENSITIVE_KEYS = {"access_token", "refresh_token", "token", "secret", "client_secret", "app_id"}


def sanitize_event(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                sanitized[key] = safe_token(str(item)) if item else item
            else:
                sanitized[key] = sanitize_event(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_event(item) for item in value]
    return value


def append_event(path: str | Path, event_type: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": now_kst().isoformat(),
        "event_type": event_type,
        "payload": sanitize_event(payload),
    }
    with output_path.open("a", encoding="utf-8") as file:
        file.write(dumps_json(event) + "\n")

