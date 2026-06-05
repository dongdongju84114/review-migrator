from __future__ import annotations

from review_migrator.utils import slugify_code


def build_review_code(*, naver_product_no: str, naver_review_id: str) -> str:
    product = slugify_code(str(naver_product_no))
    review = slugify_code(str(naver_review_id))
    return f"naver-review-{product}-{review}"
