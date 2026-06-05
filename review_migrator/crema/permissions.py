from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from review_migrator.utils import write_csv

from .errors import CremaHTTPError, error_response_body_text, error_status_code
from .products import ProductService
from .reviews import ReviewService


PROBE_REVIEW_CODE = "review-migrator-permission-probe"


@dataclass(frozen=True)
class PermissionCheckResult:
    key: str
    label: str
    ok: bool
    required: bool
    message: str
    status_code: int | None = None
    response_body: str = ""

    @property
    def severity(self) -> str:
        if self.ok:
            return "ok"
        return "error" if self.required else "warning"


def run_crema_permission_checks(
    *,
    review_service: ReviewService,
    product_service: ProductService,
    require_product_read: bool = True,
) -> list[PermissionCheckResult]:
    checks = [
        _check_endpoint(
            key="review_read",
            label="크리마 리뷰 조회 권한",
            required=True,
            action=lambda: review_service.get_by_code(PROBE_REVIEW_CODE),
            ok_error_status_codes={404},
        ),
        _check_endpoint(
            key="product_read",
            label="크리마 상품 조회 권한",
            required=require_product_read,
            action=lambda: product_service.list_products(limit=1),
            ok_error_status_codes=set(),
        ),
        PermissionCheckResult(
            key="review_write",
            label="크리마 리뷰 생성/수정 권한",
            ok=False,
            required=False,
            message="실제 리뷰를 생성하지 않고는 무해하게 확인할 수 없습니다. 크리마 앱 권한에서 리뷰 생성/수정 권한을 확인해주세요.",
        ),
    ]
    return checks


def required_permission_failures(checks: list[PermissionCheckResult]) -> list[PermissionCheckResult]:
    return [check for check in checks if check.required and not check.ok]


def write_permission_checks_csv(path: str | Path, checks: list[PermissionCheckResult]) -> int:
    return write_csv(
        path,
        [
            {
                "key": check.key,
                "label": check.label,
                "severity": check.severity,
                "required": check.required,
                "ok": check.ok,
                "status_code": check.status_code or "",
                "message": check.message,
                "response_body": check.response_body,
            }
            for check in checks
        ],
        ["key", "label", "severity", "required", "ok", "status_code", "message", "response_body"],
    )


def _check_endpoint(
    *,
    key: str,
    label: str,
    required: bool,
    action: Callable[[], Any],
    ok_error_status_codes: set[int],
) -> PermissionCheckResult:
    try:
        action()
    except CremaHTTPError as error:
        status_code = error_status_code(error)
        response_body = error_response_body_text(error)
        if status_code in ok_error_status_codes:
            return PermissionCheckResult(
                key=key,
                label=label,
                ok=True,
                required=required,
                status_code=status_code,
                message=f"엔드포인트 접근 가능: 예상된 {status_code} 응답",
                response_body=response_body,
            )
        return PermissionCheckResult(
            key=key,
            label=label,
            ok=False,
            required=required,
            status_code=status_code,
            message=_message_from_error(key, error, response_body),
            response_body=response_body,
        )
    except Exception as error:
        return PermissionCheckResult(
            key=key,
            label=label,
            ok=False,
            required=required,
            message=str(error),
        )
    return PermissionCheckResult(
        key=key,
        label=label,
        ok=True,
        required=required,
        message="접근 가능",
    )


def _message_from_error(key: str, error: CremaHTTPError, response_body: str) -> str:
    if "Permission denied" in response_body:
        if key == "product_read":
            return "크리마 Product API 상품 조회 권한(GET /v1/products) 추가 필요"
        if key == "review_read":
            return "크리마 Review API 조회 권한(GET /v1/reviews) 추가 필요"
        return "Permission denied"
    return str(error)
