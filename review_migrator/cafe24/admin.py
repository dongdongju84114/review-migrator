from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterable


class Cafe24AdminError(RuntimeError):
    pass


class Cafe24AdminHTTPError(Cafe24AdminError):
    def __init__(self, status_code: int, message: str, response_body: object | None = None) -> None:
        super().__init__(f"Cafe24 Admin API returned {status_code}: {message}")
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True)
class Cafe24AdminSettings:
    mall_id: str | None
    access_token: str | None
    api_version: str = "2024-12-01"
    shop_no: int = 1

    @classmethod
    def from_env(cls) -> "Cafe24AdminSettings":
        return cls(
            mall_id=os.getenv("CAFE24_MALL_ID"),
            access_token=os.getenv("CAFE24_ACCESS_TOKEN"),
            api_version=os.getenv("CAFE24_API_VERSION", "2024-12-01"),
            shop_no=int(os.getenv("CAFE24_SHOP_NO", "1")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.mall_id and self.access_token)

    @property
    def missing_keys(self) -> list[str]:
        missing = []
        if not self.mall_id:
            missing.append("CAFE24_MALL_ID")
        if not self.access_token:
            missing.append("CAFE24_ACCESS_TOKEN")
        return missing


class Cafe24AdminClient:
    def __init__(
        self,
        *,
        mall_id: str,
        access_token: str,
        api_version: str = "2024-12-01",
        session: Any | None = None,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
    ) -> None:
        self.base_url = f"https://{mall_id}.cafe24api.com/api/v2/admin"
        self.access_token = access_token
        self.api_version = api_version
        self.session = session or self._default_session()
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        attempts = 0
        while True:
            response = self.session.request(
                "GET",
                f"{self.base_url}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "X-Cafe24-Api-Version": self.api_version,
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                attempts += 1
                if attempts <= self.max_retries:
                    if self.retry_sleep:
                        time.sleep(self.retry_sleep * attempts)
                    continue
            if response.status_code >= 400:
                raise Cafe24AdminHTTPError(response.status_code, "request failed", self._response_body(response))
            return self._response_body(response)

    def product_no_by_product_code(
        self,
        product_codes: Iterable[str],
        *,
        shop_no: int = 1,
        chunk_size: int = 50,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        codes = [str(code).strip() for code in product_codes if str(code).strip()]
        for chunk in _chunks(sorted(set(codes)), chunk_size):
            body = self.get(
                "/products",
                params={
                    "shop_no": shop_no,
                    "product_code": ",".join(chunk),
                    "limit": 100,
                },
            )
            for product in body.get("products", []):
                product_code = str(product.get("product_code") or "").strip()
                product_no = str(product.get("product_no") or "").strip()
                if product_code in chunk and product_no:
                    result[product_code] = product_no
        return result

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
            from review_migrator.crema.http_session import UrllibSession

            return UrllibSession(timeout=30)
        return httpx.Client(timeout=30)


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]
