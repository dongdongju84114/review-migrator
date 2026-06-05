from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FileChecksum(StrictModel):
    path: str
    sha256: str
    size: int


class NormalizedReview(StrictModel):
    source: Literal["naver_smartstore"] = "naver_smartstore"
    naver_review_id: str
    naver_product_no: str
    naver_product_name: str
    naver_option_text: str | None = None
    reviewer_id: str | None = None
    reviewer_name: str
    created_at_kst: datetime
    score: int
    message: str
    has_image: bool = False
    source_image_urls: list[str] = Field(default_factory=list)
    image_files: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    idempotency_code: str
    raw_row_hash: str

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("score must be between 1 and 5")
        return value


class ProductMapping(StrictModel):
    naver_product_no: str
    crema_product_id: int | None = None
    crema_product_code: str | None = None
    internal_product_code: str | None = None
    product_name: str
    enabled: bool = True


class CremaReviewPayload(StrictModel):
    code: str
    product_id: int | None = None
    product_code: str | None = None
    created_at: datetime
    message: str
    score: int
    user_code: str | None = None
    user_name: str
    image_urls: list[str] = Field(default_factory=list, max_length=4)
    display: bool = True

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("score must be between 1 and 5")
        return value

    @model_validator(mode="after")
    def require_product_key(self) -> "CremaReviewPayload":
        if self.product_id is None and not self.product_code:
            raise ValueError("product_id or product_code is required")
        return self


class ImageMatch(StrictModel):
    naver_review_id: str
    idempotency_code: str
    image_files: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    confidence: float
    auto_match: bool
    warning: str | None = None


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    row_number: int | None = None
    field: str | None = None


class RunManifest(StrictModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    input_files: list[FileChecksum] = Field(default_factory=list)
    output_files: list[FileChecksum] = Field(default_factory=list)
    total_reviews: int = 0
    valid_reviews: int = 0
    skipped_reviews: int = 0
    failed_reviews: int = 0
    warning_count: int = 0
    mode: Literal["dry-run", "apply"] = "dry-run"
    operator: str | None = None


class VerificationItem(StrictModel):
    code: str
    ok: bool
    messages: list[str] = Field(default_factory=list)


class VerificationReport(StrictModel):
    run_id: str
    checked_at: datetime
    expected_count: int
    actual_found_count: int
    ok_count: int
    failed_count: int
    items: list[VerificationItem] = Field(default_factory=list)
