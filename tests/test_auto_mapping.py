from pathlib import Path

from review_migrator.mapping.auto_mapping import (
    CremaProduct,
    build_auto_mapping,
    build_mapping_from_marketplus_csv,
    load_cafe24_product_no_by_product_code_csv,
    load_crema_products_from_csv,
    load_crema_products_from_json,
)
from review_migrator.naver_export.normalizer import normalize_naver_export
from review_migrator.pipeline import RunAllOptions, run_all


FIXTURES = Path(__file__).parent / "fixtures"


def test_auto_mapping_enables_only_confident_matches():
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    crema_products = load_crema_products_from_json(FIXTURES / "sample_crema_products.json")

    result = build_auto_mapping(reviews, crema_products)

    enabled = {mapping.naver_product_no for mapping in result.mappings if mapping.enabled}
    disabled = {mapping.naver_product_no for mapping in result.mappings if not mapping.enabled}

    assert enabled == {"100001", "100002"}
    assert disabled == {"999999"}
    assert len(result.review_required_rows) == 1


def test_run_all_can_generate_mapping_before_payload(tmp_path):
    summary = run_all(
        RunAllOptions(
            naver_export_path=FIXTURES / "sample_naver_reviews.xlsx",
            product_mapping_path=None,
            image_dir=FIXTURES / "sample_images",
            image_base_url="https://cdn.example.com/reviews",
            output_base_dir=tmp_path,
            auto_build_mapping=True,
            crema_products_json=FIXTURES / "sample_crema_products.json",
            download_images_from_excel=False,
        )
    )

    assert summary.files["product_mapping_generated"].exists()
    assert summary.payload_count == 2
    assert any("자동 상품 매핑 검토 필요" in message for message in summary.blocking_messages)


def test_auto_mapping_accepts_crema_product_csv():
    products = load_crema_products_from_csv(FIXTURES / "sample_crema_products.csv")

    assert products[0].id == 18794
    assert products[0].code == "100001"
    assert products[0].name == "Sample Artwork Poster"


def test_marketplus_mapping_resolves_to_crema_product_id_and_code(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    marketplus_csv = tmp_path / "marketplus.csv"
    marketplus_csv.write_text(
        "\ufeff마켓상품코드,상품코드,자체상품코드,상품명\n"
        "100001,P000001,INTERNAL-1,Sample Artwork Poster\n"
        "100002,P000002,INTERNAL-2,Another Artwork Phone Case\n",
        encoding="utf-8",
    )
    crema_products = [
        CremaProduct(id=11, code="501", name="Sample Artwork Poster"),
        CremaProduct(id=12, code="502", name="Another Artwork Phone Case"),
    ]

    result = build_mapping_from_marketplus_csv(reviews, marketplus_csv, crema_products=crema_products)

    mapping_by_product_no = {mapping.naver_product_no: mapping for mapping in result.mappings}

    assert mapping_by_product_no["100001"].crema_product_id == 11
    assert mapping_by_product_no["100001"].crema_product_code == "501"
    assert mapping_by_product_no["100001"].internal_product_code == "INTERNAL-1"
    assert mapping_by_product_no["100002"].crema_product_id == 12


def test_marketplus_mapping_requires_review_for_duplicate_crema_names(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    marketplus_csv = tmp_path / "marketplus.csv"
    marketplus_csv.write_text(
        "\ufeff마켓상품코드,상품코드,상품명\n"
        "100001,P000001,Sample Artwork Poster\n",
        encoding="utf-8",
    )
    crema_products = [
        CremaProduct(id=11, code="501", name="Sample Artwork Poster"),
        CremaProduct(id=12, code="502", name="Sample Artwork Poster"),
    ]

    result = build_mapping_from_marketplus_csv(reviews, marketplus_csv, crema_products=crema_products)
    mapping = next(mapping for mapping in result.mappings if mapping.naver_product_no == "100001")

    assert mapping.enabled is False
    assert result.review_required_rows[0]["reason"] == "marketplus_crema_ambiguous_or_low_confidence"


def test_marketplus_mapping_uses_cafe24_product_no_before_name_similarity(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    marketplus_csv = tmp_path / "marketplus.csv"
    marketplus_csv.write_text(
        "\ufeff마켓상품코드,상품코드,상품명\n"
        "100001,P000001,Sample Artwork Poster\n",
        encoding="utf-8",
    )
    crema_products = [
        CremaProduct(id=11, code="501", name="Sample Artwork Poster"),
        CremaProduct(id=12, code="502", name="Sample Artwork Poster"),
    ]

    result = build_mapping_from_marketplus_csv(
        reviews,
        marketplus_csv,
        crema_products=crema_products,
        cafe24_product_no_by_code={"P000001": "502"},
    )
    mapping = next(mapping for mapping in result.mappings if mapping.naver_product_no == "100001")

    assert mapping.enabled is True
    assert mapping.crema_product_id == 12
    assert mapping.crema_product_code == "502"
    assert all(row["naver_product_no"] != "100001" for row in result.review_required_rows)
    assert result.candidate_rows[0]["reason"] == "cafe24_product_no_exact"


def test_load_cafe24_product_no_by_product_code_csv(tmp_path):
    product_csv = tmp_path / "cafe24_products.csv"
    product_csv.write_text(
        "\ufeff상품코드,상품명,상품번호\n"
        "P000001,Sample Artwork Poster,501\n"
        "P000002,Another Artwork Phone Case,502\n",
        encoding="utf-8",
    )

    assert load_cafe24_product_no_by_product_code_csv(product_csv) == {
        "P000001": "501",
        "P000002": "502",
    }


def test_marketplus_mapping_without_crema_products_does_not_enable_cafe24_code(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    marketplus_csv = tmp_path / "marketplus.csv"
    marketplus_csv.write_text(
        "\ufeff마켓상품코드,상품코드,상품명\n"
        "100001,P000001,Sample Artwork Poster\n",
        encoding="utf-8",
    )

    result = build_mapping_from_marketplus_csv(reviews, marketplus_csv)
    mapping = next(mapping for mapping in result.mappings if mapping.naver_product_no == "100001")

    assert mapping.enabled is False
    assert mapping.crema_product_code is None
    assert result.review_required_rows[0]["best_crema_product_code"] == "P000001"
    assert result.review_required_rows[0]["reason"] == "crema_products_required_for_marketplus"
