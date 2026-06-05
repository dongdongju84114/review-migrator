from __future__ import annotations

from review_migrator.schemas import ValidationIssue


def validate_image_limit(code: str, image_urls: list[str], limit: int = 4) -> list[ValidationIssue]:
    if len(image_urls) <= limit:
        return []
    return [
        ValidationIssue(
            severity="warning",
            code="image_limit_truncated",
            message=f"{code} has {len(image_urls)} images; CREMA payload will include only {limit}",
        )
    ]

