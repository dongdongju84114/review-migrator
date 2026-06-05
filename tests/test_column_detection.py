from review_migrator.naver_export.column_detector import detect_columns


def test_column_detector_accepts_header_variants():
    result = detect_columns(
        [
            "리뷰 ID",
            "스마트스토어 상품번호",
            "상품명",
            "작성자명",
            "리뷰 작성일",
            "별점",
            "리뷰 내용",
            "사진 여부",
        ]
    )

    assert result.ok
    assert result.columns["review_id"] == "리뷰 ID"
    assert result.columns["product_no"] == "스마트스토어 상품번호"
    assert result.columns["has_image"] == "사진 여부"

