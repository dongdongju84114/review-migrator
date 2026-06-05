from __future__ import annotations

from typing import Any

from review_migrator.schemas import CremaReviewPayload

from .client import CremaClient


def payload_to_form(payload: CremaReviewPayload) -> list[tuple[str, Any]]:
    form: list[tuple[str, Any]] = [
        ("code", payload.code),
        ("created_at", payload.created_at.isoformat()),
        ("message", payload.message),
        ("score", payload.score),
        ("user_name", payload.user_name),
        ("display", "1" if payload.display else "0"),
    ]
    if payload.product_id is not None:
        form.append(("product_id", payload.product_id))
    if payload.product_code:
        form.append(("product_code", payload.product_code))
    if payload.user_code:
        form.append(("user_code", payload.user_code))
    for image_url in payload.image_urls:
        form.append(("image_urls[]", image_url))
    return form


class ReviewService:
    def __init__(self, client: CremaClient) -> None:
        self.client = client

    def get_by_code(self, code: str) -> Any:
        return self.client.get("/v1/reviews", params={"code": code})

    def create(self, payload: CremaReviewPayload) -> Any:
        return self.client.post("/v1/reviews", data=payload_to_form(payload))

    def update_by_code(self, payload: CremaReviewPayload) -> Any:
        return self.client.patch("/v1/reviews", params={"code": payload.code}, data=payload_to_form(payload))

    def create_or_update(self, payload: CremaReviewPayload, duplicate_mode: str = "update") -> Any:
        existing = None
        try:
            existing = self.get_by_code(payload.code)
        except Exception:
            existing = None

        if existing and duplicate_mode == "skip":
            return {"status": "skipped", "code": payload.code, "existing": existing}
        if existing and duplicate_mode == "update":
            updated = self.update_by_code(payload)
            return {"status": "updated", "code": payload.code, "response": updated}
        if existing and duplicate_mode == "fail":
            raise RuntimeError(f"review already exists: {payload.code}")
        created = self.create(payload)
        return {"status": "created", "code": payload.code, "response": created}
