from review_migrator.crema.auth import TokenProvider
from review_migrator.crema.client import CremaClient
from review_migrator.crema.errors import CremaHTTPError, error_response_body_text, error_status_code
from review_migrator.pipeline import RunAllSummary, render_run_summary_markdown


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body or {}
        self.text = str(self.body)

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_client_refreshes_token_after_401():
    token_session = FakeSession([FakeResponse(200, {"access_token": "fresh"})])
    provider = TokenProvider(
        base_url="https://api.cre.ma",
        app_id="app",
        secret="secret",
        access_token="stale",
        session=token_session,
    )
    api_session = FakeSession([FakeResponse(401), FakeResponse(200, {"ok": True})])
    client = CremaClient(
        base_url="https://api.cre.ma",
        token_provider=provider,
        session=api_session,
        retry_sleep=0,
    )

    assert client.get("/v1/reviews", params={"code": "x"}) == {"ok": True}
    assert provider.refresh_count == 1


def test_client_retries_rate_limit_response():
    provider = TokenProvider(base_url="https://api.cre.ma", access_token="token")
    api_session = FakeSession([FakeResponse(429), FakeResponse(200, {"ok": True})])
    client = CremaClient(
        base_url="https://api.cre.ma",
        token_provider=provider,
        session=api_session,
        retry_sleep=0,
    )

    assert client.get("/v1/products") == {"ok": True}
    assert len(api_session.calls) == 2


def test_error_response_body_text_sanitizes_sensitive_keys():
    error = CremaHTTPError(
        400,
        "request failed",
        {"message": "Permission denied", "access_token": "secret-token"},
    )

    assert error_status_code(error) == 400
    body = error_response_body_text(error)

    assert "Permission denied" in body
    assert "secret-token" not in body
    assert '"access_token": "***"' in body


def test_run_summary_status_marks_upload_failures():
    summary = RunAllSummary(run_id="run-test", output_dir="out")
    summary.upload_failed_count = 1

    assert summary.status_label == "등록 실패"


def test_run_summary_separates_dry_run_from_blocked_upload():
    dry_run_summary = RunAllSummary(run_id="run-dry", output_dir="out")
    dry_run_summary.payload_count = 7
    dry_run_summary.dry_run_payload_count = 7

    blocked_summary = RunAllSummary(run_id="run-blocked", output_dir="out")
    blocked_summary.apply_requested = True
    blocked_summary.payload_count = 7
    blocked_summary.upload_blocked_count = 7
    blocked_summary.blocking_messages.append("상품 매핑 실패 10건")

    assert "- dry-run payload 기록: 7건" in render_run_summary_markdown(dry_run_summary)
    assert "- 실제 등록 보류: 7건" in render_run_summary_markdown(blocked_summary)
    assert "실제 등록/드라이런 처리" not in render_run_summary_markdown(blocked_summary)
