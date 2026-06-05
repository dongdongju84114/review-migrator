from datetime import datetime, timezone, timedelta

from review_migrator.schemas import CremaReviewPayload
from review_migrator.transform.crema_csv import payload_to_csv_row


def test_crema_csv_row_serializes_display_and_images():
    payload = CremaReviewPayload(
        code="naver-review-1-1",
        product_code="OG-1",
        created_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        message="message",
        score=5,
        user_name="tester",
        image_urls=["https://cdn.example.com/1.jpg"],
        display=True,
    )

    row = payload_to_csv_row(payload)

    assert row["진열여부 (display)"] == "Y"
    assert row["이미지1 (image_url1)"] == "https://cdn.example.com/1.jpg"
    assert row["리뷰 작성일 (created_at)"] == "2026. 01. 02"
