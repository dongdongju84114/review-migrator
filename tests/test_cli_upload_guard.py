from argparse import Namespace
from datetime import datetime

from review_migrator.cli import command_upload_crema
from review_migrator.schemas import CremaReviewPayload
from review_migrator.transform.crema_payload import write_payloads
from review_migrator.utils import write_csv


def test_upload_crema_blocks_approved_upload_when_run_artifacts_need_review(tmp_path, capsys):
    payload_path = tmp_path / "crema_payloads.jsonl"
    write_payloads(
        payload_path,
        [
            CremaReviewPayload(
                code="naver-review-1",
                product_id=1,
                created_at=datetime(2026, 6, 5, 10, 0, 0),
                message="좋아요",
                score=5,
                user_name="tester",
            )
        ],
    )
    write_csv(
        tmp_path / "failed_mapping.csv",
        [
            {
                "naver_review_id": "1",
                "naver_product_no": "100001",
                "idempotency_code": "naver-review-1",
                "reason": "mapping_disabled",
            }
        ],
        ["naver_review_id", "naver_product_no", "idempotency_code", "reason"],
    )

    result = command_upload_crema(
        Namespace(
            payload=payload_path,
            mode="create-or-update",
            duplicate_mode="update",
            approve=True,
            allow_partial_upload=False,
            env_file=tmp_path / ".env",
            registry=tmp_path / "idempotency.sqlite3",
            audit_log=tmp_path / "audit_log.jsonl",
            responses_output=tmp_path / "api_responses.jsonl",
            failed_output=tmp_path / "failed_records.csv",
            run_id="test",
        )
    )

    captured = capsys.readouterr()

    assert result == 2
    assert "upload blocked" in captured.err
    assert "상품 매핑 실패 1건" in captured.err
    assert not (tmp_path / "api_responses.jsonl").exists()
