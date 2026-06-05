from datetime import datetime, timezone, timedelta

from review_migrator.schemas import CremaReviewPayload
from review_migrator.verification.verifier import verify_payloads


def test_verification_compares_payload_and_crema_response():
    payload = CremaReviewPayload(
        code="naver-review-1-1",
        product_code="OG-1",
        created_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        message="message",
        score=5,
        user_name="tester",
        image_urls=["https://cdn.example.com/1.jpg"],
    )

    report = verify_payloads(
        payloads=[payload],
        run_id="run-1",
        get_review_by_code=lambda code: {
            "code": code,
            "product_code": "OG-1",
            "created_at": "2026-01-02T10:00:00.000+09:00",
            "message": "message",
            "score": 5,
            "display": True,
            "images_count": 1,
        },
    )

    assert report.ok_count == 1
    assert report.failed_count == 0
