from __future__ import annotations

import json as json_module
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class SimpleResponse:
    status_code: int
    text: str
    headers: dict[str, str]

    def json(self) -> Any:
        return json_module.loads(self.text) if self.text else {}


class UrllibSession:
    def __init__(self, timeout: float = 30) -> None:
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | list[tuple[str, Any]] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> SimpleResponse:
        full_url = _with_query(url, params)
        body: bytes | None = None
        request_headers: dict[str, str] = dict(headers or {})
        if json is not None:
            body = json_module.dumps(json).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json;charset=UTF-8")
        elif data is not None:
            body = urlencode(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")

        request = Request(full_url, data=body, method=method.upper(), headers=request_headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
                return SimpleResponse(response.status, text, dict(response.headers.items()))
        except HTTPError as error:
            text = error.read().decode("utf-8")
            return SimpleResponse(error.code, text, dict(error.headers.items()))


def _with_query(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"
