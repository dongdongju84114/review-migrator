from review_migrator.storage.sqlite_registry import IdempotencyRegistry
from review_migrator.transform.idempotency import build_review_code


def test_review_code_is_deterministic():
    assert build_review_code(naver_product_no="100001", naver_review_id="RV-001") == "naver-review-100001-RV-001"


def test_registry_tracks_seen_codes(tmp_path):
    registry = IdempotencyRegistry(tmp_path / "registry.sqlite3")
    code = "naver-review-100001-RV-001"

    assert not registry.seen(code)
    registry.record(code, status="uploaded", run_id="run-1")
    assert registry.seen(code)
    registry.close()
