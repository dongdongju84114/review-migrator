from __future__ import annotations

import re
from typing import Any

from review_migrator.schemas import ValidationIssue

from .column_detector import ColumnDetectionResult


def issues_for_detection(result: ColumnDetectionResult) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            severity="error",
            code="missing_column",
            message=f"required column is missing: {column}",
            field=column,
        )
        for column in result.missing
    ]


def parse_bool(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text or text == "nan":
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return True
    return text in {"1", "true", "t", "yes", "y", "o", "있음", "유", "포토", "사진", "첨부"}


def extract_urls(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    return re.findall(r"https?://[^\s,|]+", text)


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() == "nan":
        return default
    return text
