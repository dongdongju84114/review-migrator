from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from review_migrator.schemas import CremaReviewPayload, VerificationItem, VerificationReport
from review_migrator.utils import now_kst, row_hash


def _extract_single_review(response: Any) -> dict[str, Any] | None:
    if isinstance(response, list):
        return response[0] if response else None
    if isinstance(response, dict):
        return response
    return None


def verify_payloads(
    *,
    payloads: list[CremaReviewPayload],
    get_review_by_code: Callable[[str], Any],
    run_id: str,
    attempts: int = 1,
    sleep_seconds: float = 0,
) -> VerificationReport:
    items: list[VerificationItem] = []
    found_count = 0

    for payload in payloads:
        actual = None
        messages: list[str] = ["review not found"]
        for attempt in range(max(attempts, 1)):
            actual = _extract_single_review(get_review_by_code(payload.code))
            if actual:
                messages = _verification_messages(payload, actual)
                if "image count mismatch" not in messages:
                    break
            if attempt < max(attempts, 1) - 1 and sleep_seconds:
                time.sleep(sleep_seconds)
        if not actual:
            items.append(VerificationItem(code=payload.code, ok=False, messages=messages))
            continue
        found_count += 1

        items.append(VerificationItem(code=payload.code, ok=not messages, messages=messages))

    ok_count = sum(1 for item in items if item.ok)
    return VerificationReport(
        run_id=run_id,
        checked_at=now_kst(),
        expected_count=len(payloads),
        actual_found_count=found_count,
        ok_count=ok_count,
        failed_count=len(items) - ok_count,
        items=items,
    )


def _verification_messages(payload: CremaReviewPayload, actual: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    if str(actual.get("code")) != payload.code:
        messages.append("code mismatch")
    if payload.product_id is not None and actual.get("product_id") != payload.product_id:
        messages.append("product_id mismatch")
    if payload.product_code and str(actual.get("product_code")) != str(payload.product_code):
        messages.append("product_code mismatch")
    if int(actual.get("score", 0)) != payload.score:
        messages.append("score mismatch")
    if bool(actual.get("display")) != payload.display:
        messages.append("display mismatch")
    actual_date = str(actual.get("created_at", ""))[:10]
    expected_date = payload.created_at.date().isoformat()
    if actual_date and actual_date != expected_date:
        messages.append("created_at date mismatch")

    expected_message_hash = row_hash({"message": payload.message})[:12]
    actual_message_hash = row_hash({"message": actual.get("message", "")})[:12]
    if expected_message_hash != actual_message_hash:
        messages.append("message hash mismatch")

    expected_image_count = len(payload.image_urls)
    actual_image_count = int(actual.get("images_count") or len(actual.get("images", [])))
    if actual_image_count != expected_image_count:
        messages.append("image count mismatch")
    return messages


def empty_report(run_id: str) -> VerificationReport:
    return VerificationReport(
        run_id=run_id,
        checked_at=datetime.now(),
        expected_count=0,
        actual_found_count=0,
        ok_count=0,
        failed_count=0,
    )
