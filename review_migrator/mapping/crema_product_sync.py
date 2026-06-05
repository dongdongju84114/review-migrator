from __future__ import annotations

from collections.abc import Iterable

from review_migrator.schemas import ProductMapping, ValidationIssue


def validate_with_crema_products(client: object, mappings: Iterable[ProductMapping]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for mapping in mappings:
        if not mapping.enabled:
            continue
        try:
            if mapping.crema_product_code:
                found = client.get_product_by_code(mapping.crema_product_code)
            elif mapping.crema_product_id is not None:
                found = client.get_product(mapping.crema_product_id)
            else:
                found = None
        except Exception as error:  # pragma: no cover - depends on external API.
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="crema_product_lookup_failed",
                    message=f"{mapping.naver_product_no}: {error}",
                )
            )
            continue
        if not found:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="crema_product_not_found",
                    message=f"{mapping.naver_product_no} was not found in CREMA",
                )
            )
    return issues

