from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from review_migrator.schemas import ValidationIssue

T = TypeVar("T")


@dataclass
class HarnessResult(Generic[T]):
    records: list[T] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

