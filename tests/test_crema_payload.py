from datetime import datetime, timezone, timedelta

from review_migrator.schemas import ImageMatch, NormalizedReview, ProductMapping
from review_migrator.transform.crema_payload import build_payload, build_payloads


def _review(review_id="RV-001", product_no="100001"):
    return NormalizedReview(
        naver_review_id=review_id,
        naver_product_no=product_no,
        naver_product_name="Sample",
        reviewer_name="tester",
        created_at_kst=datetime(2026, 1, 2, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        score=5,
        message="좋아요",
        has_image=True,
        idempotency_code=f"naver-review-{product_no}-{review_id}",
        raw_row_hash="hash",
    )


def test_payload_accepts_product_id_or_product_code():
    review = _review()
    id_mapping = ProductMapping(naver_product_no="100001", crema_product_id=1, product_name="Sample")
    code_mapping = ProductMapping(naver_product_no="100001", crema_product_code="OG-1", product_name="Sample")

    assert build_payload(review, id_mapping)[0].product_id == 1
    assert build_payload(review, code_mapping)[0].product_code == "OG-1"


def test_payload_truncates_images_to_four_and_warns():
    review = _review()
    mapping = ProductMapping(naver_product_no="100001", crema_product_code="OG-1", product_name="Sample")
    match = ImageMatch(
        naver_review_id="RV-001",
        idempotency_code=review.idempotency_code,
        image_files=[],
        image_urls=[f"https://cdn.example.com/{index}.jpg" for index in range(5)],
        confidence=1,
        auto_match=True,
    )

    payload, issues = build_payload(review, mapping, image_match=match)

    assert len(payload.image_urls) == 4
    assert issues[0].code == "image_limit_truncated"


def test_duplicate_code_is_reported():
    review = _review()
    mapping = ProductMapping(naver_product_no="100001", crema_product_code="OG-1", product_name="Sample")

    payloads, issues = build_payloads([(review, mapping), (review, mapping)])

    assert len(payloads) == 1
    assert issues[0].code == "duplicate_code"
