from review_migrator.crema.errors import CremaHTTPError
from review_migrator.crema.permissions import required_permission_failures, run_crema_permission_checks


class FakeReviewService:
    def get_by_code(self, code):
        raise CremaHTTPError(404, "not found", {"message": "review not found"})


class FakeProductService:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else []
        self.error = error

    def list_products(self, *, limit=100):
        if self.error:
            raise self.error
        return self.response


def test_permission_probe_treats_review_404_as_reachable():
    checks = run_crema_permission_checks(
        review_service=FakeReviewService(),
        product_service=FakeProductService(),
        require_product_read=True,
    )

    assert checks[0].key == "review_read"
    assert checks[0].ok is True
    assert required_permission_failures(checks) == []


def test_permission_probe_fails_required_product_permission():
    checks = run_crema_permission_checks(
        review_service=FakeReviewService(),
        product_service=FakeProductService(
            error=CremaHTTPError(400, "request failed", {"message": "Permission denied"})
        ),
        require_product_read=True,
    )

    failures = required_permission_failures(checks)

    assert len(failures) == 1
    assert failures[0].key == "product_read"
    assert failures[0].message == "크리마 Product API 상품 조회 권한(GET /v1/products) 추가 필요"


def test_permission_probe_warns_optional_product_permission():
    checks = run_crema_permission_checks(
        review_service=FakeReviewService(),
        product_service=FakeProductService(
            error=CremaHTTPError(400, "request failed", {"message": "Permission denied"})
        ),
        require_product_read=False,
    )

    product_check = next(check for check in checks if check.key == "product_read")

    assert product_check.severity == "warning"
    assert required_permission_failures(checks) == []
