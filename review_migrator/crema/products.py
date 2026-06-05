from __future__ import annotations

from typing import Any

from .client import CremaClient


class ProductService:
    def __init__(self, client: CremaClient) -> None:
        self.client = client

    def list_products(self, *, limit: int = 100) -> Any:
        return self.client.get("/v1/products", params={"limit": limit})

    def get_product(self, product_id: int) -> Any:
        return self.client.get(f"/v1/products/{product_id}")

    def get_product_by_code(self, code: str) -> Any:
        return self.client.get("/v1/products", params={"code": code})

