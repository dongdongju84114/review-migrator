from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from review_migrator.schemas import NormalizedReview, ProductMapping, ValidationIssue


def _parse_bool(value: object, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "enabled"}


def _parse_int(value: object) -> int | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    return int(float(text))


def load_product_mappings(path: str | Path) -> dict[str, ProductMapping]:
    mappings: dict[str, ProductMapping] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            naver_product_no = str(row.get("naver_product_no", "")).strip()
            if not naver_product_no:
                continue
            mappings[naver_product_no] = ProductMapping(
                naver_product_no=naver_product_no,
                crema_product_id=_parse_int(row.get("crema_product_id")),
                crema_product_code=str(row.get("crema_product_code") or "").strip() or None,
                internal_product_code=str(row.get("internal_product_code") or "").strip() or None,
                product_name=str(row.get("product_name") or "").strip(),
                enabled=_parse_bool(row.get("enabled"), default=True),
            )
    return mappings


@dataclass(frozen=True)
class MappingResult:
    mapped: list[tuple[NormalizedReview, ProductMapping]]
    failed_rows: list[dict[str, str]]
    issues: list[ValidationIssue]


def apply_product_mapping(
    reviews: list[NormalizedReview],
    mappings: dict[str, ProductMapping],
) -> MappingResult:
    mapped: list[tuple[NormalizedReview, ProductMapping]] = []
    failed_rows: list[dict[str, str]] = []
    issues: list[ValidationIssue] = []

    for review in reviews:
        mapping = mappings.get(review.naver_product_no)
        if mapping is None:
            reason = "mapping_not_found"
        elif not mapping.enabled:
            reason = "mapping_disabled"
        elif mapping.crema_product_id is None and not mapping.crema_product_code:
            reason = "crema_product_key_missing"
        else:
            mapped.append((review, mapping))
            continue

        failed_rows.append(
            {
                "naver_review_id": review.naver_review_id,
                "naver_product_no": review.naver_product_no,
                "idempotency_code": review.idempotency_code,
                "reason": reason,
            }
        )
        issues.append(
            ValidationIssue(
                severity="error",
                code=reason,
                message=f"{review.naver_review_id} cannot be mapped: {reason}",
            )
        )

    return MappingResult(mapped=mapped, failed_rows=failed_rows, issues=issues)

