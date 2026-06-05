from pathlib import Path

from review_migrator.naver_export.normalizer import normalize_naver_export


FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_filters_low_scores_and_outputs_kst_reviews():
    result = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx")

    assert result.error_count == 0
    assert len(result.records) == 3
    assert {review.score for review in result.records} == {4, 5}
    assert all(review.created_at_kst.utcoffset().total_seconds() == 9 * 3600 for review in result.records)
    assert any(issue.code == "low_score_skipped" for issue in result.issues)


def test_normalize_extracts_photo_url_from_export():
    result = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx")
    first = result.records[0]

    assert first.has_image is True
    assert first.source_image_urls == ["https://example.com/RV-001.jpg"]
