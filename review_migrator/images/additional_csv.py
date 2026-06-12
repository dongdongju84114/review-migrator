from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_migrator.schemas import NormalizedReview
from review_migrator.utils import write_csv


ADDITIONAL_IMAGE_IMPORT_COLUMNS = [
    "naver_product_no",
    "naver_review_id",
    "image_url",
    "sort_order",
    "media_type",
    "source",
    "merge_status",
    "message",
]


@dataclass
class AdditionalImageMergeResult:
    reviews: list[NormalizedReview]
    rows: list[dict[str, object]]
    merged_count: int = 0
    skipped_count: int = 0


def merge_additional_image_urls(
    reviews: list[NormalizedReview],
    csv_path: str | Path,
    *,
    max_images_per_review: int = 4,
) -> AdditionalImageMergeResult:
    review_by_id = {review.naver_review_id: review for review in reviews}
    urls_by_review_id = {review.naver_review_id: list(review.source_image_urls) for review in reviews}
    import_rows: list[dict[str, object]] = []
    merged_count = 0
    skipped_count = 0

    for row in _read_additional_image_rows(csv_path):
        naver_review_id = _first_value(row, ["naver_review_id", "review_id", "리뷰번호", "리뷰 ID"])
        naver_product_no = _first_value(row, ["naver_product_no", "product_no", "상품번호"])
        image_url = _first_value(row, ["image_url", "url", "이미지 URL", "이미지URL"])
        sort_order = _first_value(row, ["sort_order", "order", "순서"])
        media_type = _first_value(row, ["media_type", "type", "미디어타입"]) or "image"
        source = _first_value(row, ["source", "출처"]) or "additional_csv"

        status = "merged"
        message = ""
        if not naver_review_id:
            status = "missing_review_id"
            message = "naver_review_id is required"
        elif not image_url:
            status = "missing_image_url"
            message = "image_url is required"
        elif not str(image_url).startswith(("http://", "https://", "file://")):
            status = "invalid_image_url"
            message = "image_url must start with http://, https://, or file://"
        elif media_type and str(media_type).strip().lower() not in {"image", "photo", "picture"}:
            status = "unsupported_media_type"
            message = f"unsupported media_type: {media_type}"
        elif naver_review_id not in review_by_id:
            status = "review_not_in_export"
            message = "review id was not found in normalized Naver export"
        else:
            current_urls = urls_by_review_id[naver_review_id]
            if image_url in current_urls:
                status = "duplicate_skipped"
                message = "image_url is already present for this review"
            elif len(current_urls) >= max_images_per_review:
                status = "max_images_reached"
                message = f"CREMA supports up to {max_images_per_review} images per review"
            else:
                current_urls.append(image_url)
                merged_count += 1

        if status != "merged":
            skipped_count += 1

        import_rows.append(
            {
                "naver_product_no": naver_product_no,
                "naver_review_id": naver_review_id,
                "image_url": image_url,
                "sort_order": sort_order,
                "media_type": media_type,
                "source": source,
                "merge_status": status,
                "message": message,
            }
        )

    updated_reviews = [
        review.model_copy(update={"source_image_urls": urls_by_review_id[review.naver_review_id]})
        for review in reviews
    ]
    return AdditionalImageMergeResult(
        reviews=updated_reviews,
        rows=import_rows,
        merged_count=merged_count,
        skipped_count=skipped_count,
    )


def write_additional_image_import(path: str | Path, rows: list[dict[str, object]]) -> int:
    return write_csv(path, rows, ADDITIONAL_IMAGE_IMPORT_COLUMNS)


def _read_additional_image_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return sorted(rows, key=_additional_image_sort_key)


def _additional_image_sort_key(row: dict[str, str]) -> tuple[str, int]:
    review_id = _first_value(row, ["naver_review_id", "review_id", "리뷰번호", "리뷰 ID"])
    raw_order = _first_value(row, ["sort_order", "order", "순서"])
    try:
        sort_order = int(raw_order)
    except (TypeError, ValueError):
        sort_order = 9999
    return review_id, sort_order


def _first_value(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
