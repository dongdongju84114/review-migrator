from pathlib import Path

from review_migrator.images.matcher import match_images
from review_migrator.images.downloader import download_review_images
from review_migrator.images.ftp_storage import FtpStorageConfig, stage_or_upload_matches_to_ftp
from review_migrator.naver_export.normalizer import normalize_naver_export


FIXTURES = Path(__file__).parent / "fixtures"


def test_image_matcher_auto_matches_review_id_pattern():
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records

    confirmed, review_required = match_images(
        reviews,
        FIXTURES / "sample_images",
        base_url="https://cdn.example.com/reviews",
    )

    first = next(match for match in confirmed if match.naver_review_id == "RV-001")
    assert first.auto_match is True
    assert len(first.image_urls) == 4
    assert first.warning
    assert any(match.auto_match is False for match in review_required)


def test_download_review_images_stages_local_files(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    source = tmp_path / "source.jpg"
    source.write_bytes(b"image")
    review = reviews[0].model_copy(update={"source_image_urls": [source.resolve().as_uri()]})

    matches, manifest = download_review_images([review], download_dir=tmp_path / "downloaded")

    assert len(matches) == 1
    assert matches[0].image_files
    assert not matches[0].image_urls
    assert manifest[0]["status"] == "downloaded"


def test_ftp_storage_plans_public_urls_without_upload(tmp_path):
    reviews = normalize_naver_export(FIXTURES / "sample_naver_reviews.xlsx").records
    source = tmp_path / "source.jpg"
    source.write_bytes(b"image")
    review = reviews[0].model_copy(update={"source_image_urls": [source.resolve().as_uri()]})
    matches, manifest = download_review_images([review], download_dir=tmp_path / "downloaded")
    config = FtpStorageConfig(
        host="ftp.example.com",
        user="user",
        password="password",
        remote_dir="/www/review-images",
        public_base_url="https://example.com/review-images",
    )

    updated_matches, updated_manifest = stage_or_upload_matches_to_ftp(
        matches,
        manifest,
        config=config,
        upload=False,
    )

    assert updated_matches[0].image_urls == ["https://example.com/review-images/RV-001_1.jpg"]
    assert updated_manifest[0]["status"] == "planned"
    assert updated_manifest[0]["remote_file"] == "/www/review-images/RV-001_1.jpg"
