from __future__ import annotations


class ApprovalError(RuntimeError):
    pass


def ensure_apply_allowed(
    *,
    env: str,
    dry_run: bool,
    approve: bool,
    validation_error_count: int = 0,
) -> None:
    if dry_run:
        return
    if not approve:
        raise ApprovalError("apply mode requires --approve")
    if env == "production" and validation_error_count > 0:
        raise ApprovalError("production apply requires zero validation errors")

