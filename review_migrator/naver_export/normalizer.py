from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from review_migrator.harness.base import HarnessResult
from review_migrator.schemas import NormalizedReview, ValidationIssue
from review_migrator.transform.idempotency import build_review_code
from review_migrator.utils import ensure_kst, row_hash, write_csv, write_jsonl

from .column_detector import detect_columns
from .parser import read_naver_export
from .validators import clean_text, extract_urls, issues_for_detection, parse_bool


def _value(row: dict[str, Any], columns: dict[str, str], key: str, default: Any = None) -> Any:
    source = columns.get(key)
    if source is None:
        return default
    return row.get(source, default)


def _parse_score(value: Any) -> int:
    if value is None:
        raise ValueError("score is empty")
    if isinstance(value, str):
        value = value.strip().replace("점", "")
    return int(float(value))


def _parse_created_at(value: Any) -> pd.Timestamp:
    if value is None or str(value).strip().lower() == "nan":
        raise ValueError("created_at is empty")
    parsed = pd.to_datetime(value)
    if pd.isna(parsed):
        raise ValueError("created_at is invalid")
    return parsed


def normalize_naver_export(path: str | Path) -> HarnessResult[NormalizedReview]:
    dataframe = read_naver_export(path)
    detection = detect_columns(list(dataframe.columns))
    result: HarnessResult[NormalizedReview] = HarnessResult()
    result.issues.extend(issues_for_detection(detection))
    if not detection.ok:
        return result

    for offset, row in enumerate(dataframe.to_dict(orient="records"), start=2):
        try:
            score = _parse_score(_value(row, detection.columns, "score"))
        except (TypeError, ValueError) as error:
            result.issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_score",
                    message=str(error),
                    row_number=offset,
                    field="score",
                )
            )
            continue

        if score < 4:
            result.issues.append(
                ValidationIssue(
                    severity="warning",
                    code="low_score_skipped",
                    message=f"score {score} review was skipped",
                    row_number=offset,
                    field="score",
                )
            )
            continue

        try:
            created_at = _parse_created_at(_value(row, detection.columns, "created_at"))
        except ValueError as error:
            result.issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_created_at",
                    message=str(error),
                    row_number=offset,
                    field="created_at",
                )
            )
            continue

        naver_review_id = clean_text(_value(row, detection.columns, "review_id"))
        naver_product_no = clean_text(_value(row, detection.columns, "product_no"))
        product_name = clean_text(_value(row, detection.columns, "product_name"))
        reviewer_name = clean_text(_value(row, detection.columns, "reviewer_name"), default="네이버 구매자")
        message = clean_text(_value(row, detection.columns, "message"))
        if not naver_review_id or not naver_product_no or not message:
            result.issues.append(
                ValidationIssue(
                    severity="error",
                    code="required_value_missing",
                    message="review_id, product_no, and message are required",
                    row_number=offset,
                )
            )
            continue

        raw = {
            "naver_review_id": naver_review_id,
            "naver_product_no": naver_product_no,
            "naver_product_name": product_name,
            "reviewer_name": reviewer_name,
            "created_at": str(created_at),
            "score": score,
            "message": message,
        }
        code = build_review_code(naver_product_no=naver_product_no, naver_review_id=naver_review_id)
        source_image_urls = extract_urls(_value(row, detection.columns, "has_image"))
        result.records.append(
            NormalizedReview(
                naver_review_id=naver_review_id,
                naver_product_no=naver_product_no,
                naver_product_name=product_name,
                naver_option_text=clean_text(_value(row, detection.columns, "option_text")) or None,
                reviewer_id=clean_text(_value(row, detection.columns, "reviewer_id")) or None,
                reviewer_name=reviewer_name,
                created_at_kst=ensure_kst(created_at.to_pydatetime()),
                score=score,
                message=message,
                has_image=bool(source_image_urls) or parse_bool(_value(row, detection.columns, "has_image")),
                source_image_urls=source_image_urls,
                idempotency_code=code,
                raw_row_hash=row_hash(raw),
            )
        )

    return result


def write_normalized_outputs(
    reviews: list[NormalizedReview],
    jsonl_path: str | Path,
    csv_path: str | Path | None = None,
) -> None:
    write_jsonl(jsonl_path, reviews)
    if csv_path:
        fieldnames = list(NormalizedReview.model_fields.keys())
        rows = [review.model_dump(mode="json") for review in reviews]
        write_csv(csv_path, rows, fieldnames)
