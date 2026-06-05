from __future__ import annotations

from review_migrator.schemas import ProductMapping, ValidationIssue


def validate_mapping_rows(mappings: dict[str, ProductMapping]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for naver_product_no, mapping in mappings.items():
        if mapping.enabled and mapping.crema_product_id is None and not mapping.crema_product_code:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="crema_product_key_missing",
                    message=f"{naver_product_no} is enabled but has no crema product id/code",
                    field="crema_product_id",
                )
            )
    return issues

