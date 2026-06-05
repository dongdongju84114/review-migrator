from __future__ import annotations

import re
from dataclasses import dataclass


COLUMN_ALIASES: dict[str, list[str]] = {
    "review_id": [
        "review_id",
        "reviewid",
        "리뷰id",
        "리뷰아이디",
        "리뷰번호",
        "리뷰글번호",
        "구매평번호",
        "리뷰관리번호",
    ],
    "product_no": [
        "product_no",
        "productno",
        "상품번호",
        "스마트스토어상품번호",
        "채널상품번호",
        "네이버상품번호",
    ],
    "product_name": [
        "product_name",
        "productname",
        "상품명",
        "상품이름",
    ],
    "option_text": [
        "option",
        "option_text",
        "옵션",
        "상품옵션",
        "옵션정보",
    ],
    "reviewer_id": [
        "reviewer_id",
        "writer_id",
        "작성자id",
        "작성자아이디",
        "구매자id",
        "구매자아이디",
        "아이디",
    ],
    "reviewer_name": [
        "reviewer_name",
        "writer",
        "작성자",
        "작성자명",
        "등록자",
        "구매자",
        "구매자명",
        "닉네임",
    ],
    "created_at": [
        "created_at",
        "createdat",
        "작성일",
        "리뷰작성일",
        "리뷰등록일",
        "등록일",
        "작성일시",
    ],
    "score": [
        "score",
        "rating",
        "평점",
        "별점",
        "리뷰평점",
    ],
    "message": [
        "message",
        "content",
        "review",
        "리뷰내용",
        "리뷰상세내용",
        "내용",
        "구매평내용",
        "리뷰",
    ],
    "has_image": [
        "has_image",
        "image",
        "이미지",
        "이미지여부",
        "사진여부",
        "포토",
        "포토동영상",
    ],
}

REQUIRED_COLUMNS = [
    "review_id",
    "product_no",
    "product_name",
    "reviewer_name",
    "created_at",
    "score",
    "message",
]


@dataclass(frozen=True)
class ColumnDetectionResult:
    columns: dict[str, str]
    missing: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing


def normalize_header(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s_\-()/\\[\].:]+", "", text)
    return text


def detect_columns(headers: list[object]) -> ColumnDetectionResult:
    normalized_headers = {normalize_header(header): str(header) for header in headers}
    detected: dict[str, str] = {}

    for canonical, aliases in COLUMN_ALIASES.items():
        normalized_aliases = [normalize_header(alias) for alias in aliases]
        for alias in normalized_aliases:
            if alias in normalized_headers:
                detected[canonical] = normalized_headers[alias]
                break
        if canonical in detected:
            continue
        for header_key, original in normalized_headers.items():
            if any(alias and alias in header_key for alias in normalized_aliases):
                detected[canonical] = original
                break

    missing = [column for column in REQUIRED_COLUMNS if column not in detected]
    return ColumnDetectionResult(columns=detected, missing=missing)
