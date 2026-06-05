from datetime import datetime, timezone
from urllib.error import HTTPError

from review_migrator.crema.auth import TokenProvider
from review_migrator.crema.client import CremaClient
from review_migrator.crema.errors import CremaHTTPError, error_response_body_text, error_status_code
from review_migrator.crema.reviews import ReviewService
from review_migrator.images.url_checker import check_public_image_url
from review_migrator.pipeline import RunAllSummary, render_run_summary_markdown
from review_migrator.schemas import CremaReviewPayload


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


def test_client_encodes_repeated_form_data_as_bytes():
    provider = TokenProvider(base_url="https://api.cre.ma", access_token="token")
    api_session = FakeSession([FakeResponse(200, {"ok": True})])
    client = CremaClient(
        base_url="https://api.cre.ma",
        token_provider=provider,
        session=api_session,
        retry_sleep=0,
    )

    assert client.post(
        "/v1/reviews",
        data=[
            ("code", "review-1"),
            ("image_urls[]", "https://example.com/1.jpg"),
            ("image_urls[]", "https://example.com/2.jpg"),
        ],
    ) == {"ok": True}

    _, _, kwargs = api_session.calls[0]
    assert isinstance(kwargs["data"], bytes)
    assert b"access_token=token" in kwargs["data"]
    assert kwargs["data"].count(b"image_urls%5B%5D=") == 2
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded;charset=UTF-8"


def test_review_update_preserves_repeated_image_form_fields():
    provider = TokenProvider(base_url="https://api.cre.ma", access_token="token")
    api_session = FakeSession([FakeResponse(204)])
    service = ReviewService(
        CremaClient(
            base_url="https://api.cre.ma",
            token_provider=provider,
            session=api_session,
            retry_sleep=0,
        )
    )
    payload = CremaReviewPayload(
        code="review-1",
        product_id=1,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        message="message",
        score=5,
        user_name="tester",
        image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
    )

    assert service.update_by_code(payload) is None

    _, _, kwargs = api_session.calls[0]
    assert isinstance(kwargs["data"], bytes)
    assert kwargs["data"].count(b"image_urls%5B%5D=") == 2


class FakeUrlResponse:
    def __init__(self, status, content_type):
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def getcode(self):
        return self.status

    def read(self, _size=-1):
        return b"x"


def test_public_image_url_checker_falls_back_to_get_after_head_405():
    calls = []

    def opener(request, timeout):
        calls.append((request.get_method(), timeout))
        if request.get_method() == "HEAD":
            raise HTTPError(request.full_url, 405, "Method Not Allowed", {}, None)
        return FakeUrlResponse(200, "image/jpeg")

    check = check_public_image_url("https://example.com/image.jpg", opener=opener)

    assert check.ok is True
    assert calls == [("HEAD", 10), ("GET", 10)]


def test_public_image_url_checker_rejects_html_response():
    def opener(request, timeout):
        return FakeUrlResponse(200, "text/html; charset=utf-8")

    check = check_public_image_url("https://example.com/not-image", opener=opener)

    assert check.ok is False
    assert check.error == "not an image content type: text/html; charset=utf-8"


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
