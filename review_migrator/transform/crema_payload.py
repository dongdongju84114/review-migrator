from __future__ import annotations

from pathlib import Path

from review_migrator.schemas import CremaReviewPayload, ImageMatch, NormalizedReview, ProductMapping, ValidationIssue
from review_migrator.utils import write_jsonl


def load_image_matches(path: str | Path | None) -> dict[str, ImageMatch]:
    if path is None:
        return {}
    import csv

    matches: dict[str, ImageMatch] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            auto_match = str(row.get("auto_match", "")).lower() in {"1", "true", "yes", "y"}
            image_files = [item for item in str(row.get("image_files") or "").split("|") if item]
            image_urls = [item for item in str(row.get("image_urls") or "").split("|") if item]
            match = ImageMatch(
                naver_review_id=str(row["naver_review_id"]),
                idempotency_code=str(row["idempotency_code"]),
                image_files=image_files,
                image_urls=image_urls,
                confidence=float(row.get("confidence") or 0),
                auto_match=auto_match,
                warning=str(row.get("warning") or "") or None,
            )
            matches[match.idempotency_code] = match
    return matches


def build_payload(
    review: NormalizedReview,
    mapping: ProductMapping,
    image_match: ImageMatch | None = None,
    display: bool = True,
) -> tuple[CremaReviewPayload, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    image_urls = list(review.image_urls)
    if image_match and image_match.auto_match:
        image_urls.extend(image_match.image_urls)
    if len(image_urls) > 4:
        image_urls = image_urls[:4]
        issues.append(
            ValidationIssue(
                severity="warning",
                code="image_limit_truncated",
                message=f"{review.idempotency_code} has more than 4 images; only first 4 were included",
            )
        )

    payload = CremaReviewPayload(
        code=review.idempotency_code,
        product_id=mapping.crema_product_id,
        product_code=mapping.crema_product_code,
        created_at=review.created_at_kst,
        message=review.message,
        score=review.score,
        user_code=review.reviewer_id,
        user_name=review.reviewer_name,
        image_urls=image_urls,
        display=display,
    )
    return payload, issues


def build_payloads(
    mapped_reviews: list[tuple[NormalizedReview, ProductMapping]],
    image_matches: dict[str, ImageMatch] | None = None,
    display: bool = True,
) -> tuple[list[CremaReviewPayload], list[ValidationIssue]]:
    matches = image_matches or {}
    payloads: list[CremaReviewPayload] = []
    issues: list[ValidationIssue] = []
    seen_codes: set[str] = set()

    for review, mapping in mapped_reviews:
        if review.idempotency_code in seen_codes:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_code",
                    message=f"duplicate review code: {review.idempotency_code}",
                )
            )
            continue
        seen_codes.add(review.idempotency_code)
        payload, payload_issues = build_payload(
            review=review,
            mapping=mapping,
            image_match=matches.get(review.idempotency_code),
            display=display,
        )
        payloads.append(payload)
        issues.extend(payload_issues)

    return payloads, issues


def write_payloads(path: str | Path, payloads: list[CremaReviewPayload]) -> None:
    write_jsonl(path, payloads)

