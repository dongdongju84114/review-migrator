from pathlib import Path

from review_migrator.mapping.product_mapping import apply_product_mapping, load_product_mappings
from review_migrator.naver_export.normalizer import normalize_naver_export


FIXTURES = Path(__file__).parent / "fixtures"


def test_product_mapping_splits_success_and_failure():
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    mappings = load_product_mappings(FIXTURES / "sample_product_mapping.csv")

    result = apply_product_mapping(reviews, mappings)

    assert len(result.mapped) == 2
    assert len(result.failed_rows) == 1
    assert result.failed_rows[0]["reason"] == "mapping_not_found"
