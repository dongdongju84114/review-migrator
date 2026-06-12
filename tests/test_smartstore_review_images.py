from pathlib import Path

from review_migrator.images.additional_csv import apply_image_csv_urls
from review_migrator.naver_export.normalizer import normalize_naver_export
from review_migrator.smartstore.review_images import extract_smartstore_review_image_rows


FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_review_images_from_smartstore_review_item_html():
    html = """
    <li class="N9LWAcN4hj" id="REVIEW_ITEM_4995291954">
      <div>
        <img src="https://phinf.pstatic.net/contact/profile.jpeg?type=f76_76">
        <p id="review_content_4995291954">좋아요</p>
        <ul>
          <li>
            <img
              src="https://phinf.pstatic.net/checkout.phinf/20260610_235/1781065229876MkJv0_JPEG/image.jpg?type=w480"
              data-src="https://phinf.pstatic.net/checkout.phinf/20260610_235/1781065229876MkJv0_JPEG/image.jpg?type=w480"
              alt="review_image">
          </li>
        </ul>
      </div>
    </li>
    """

    rows = extract_smartstore_review_image_rows(html, naver_product_no="13058129101")

    assert rows == [
        {
            "naver_product_no": "13058129101",
            "naver_review_id": "4995291954",
            "image_url": "https://phinf.pstatic.net/checkout.phinf/20260610_235/1781065229876MkJv0_JPEG/image.jpg?type=w480",
            "sort_order": 1,
            "media_type": "image",
            "source": "smartstore_review_modal",
            "match_status": "matched",
            "match_basis": "review_item_id",
        }
    ]


def test_image_csv_replaces_excel_images_and_caps_at_four(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    first = reviews[0]
    csv_path = tmp_path / "smartstore_review_images.csv"
    csv_path.write_text(
        "\n".join(
            [
                "naver_product_no,naver_review_id,image_url,sort_order,media_type",
                f"{first.naver_product_no},{first.naver_review_id},https://example.com/RV-001.jpg,1,image",
                f"{first.naver_product_no},{first.naver_review_id},https://example.com/RV-001-2.jpg,2,image",
                f"{first.naver_product_no},{first.naver_review_id},https://example.com/RV-001-3.jpg,3,image",
                f"{first.naver_product_no},{first.naver_review_id},https://example.com/RV-001-4.jpg,4,image",
                f"{first.naver_product_no},{first.naver_review_id},https://example.com/RV-001-5.jpg,5,image",
            ]
        ),
        encoding="utf-8",
    )

    result = apply_image_csv_urls(reviews, csv_path)
    updated_first = next(review for review in result.reviews if review.naver_review_id == first.naver_review_id)

    assert updated_first.source_image_urls == [
        "https://example.com/RV-001.jpg",
        "https://example.com/RV-001-2.jpg",
        "https://example.com/RV-001-3.jpg",
        "https://example.com/RV-001-4.jpg",
    ]
    assert result.applied_count == 4
    assert [row["merge_status"] for row in result.rows] == [
        "merged",
        "merged",
        "merged",
        "merged",
        "max_images_reached",
    ]
