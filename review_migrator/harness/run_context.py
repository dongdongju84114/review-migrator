from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from review_migrator.utils import now_kst


@dataclass(frozen=True)
class RunContext:
    run_id: str
    output_dir: Path
    mode: Literal["dry-run", "apply"]
    operator: str | None

    @classmethod
    def create(
        cls,
        output_dir: str | Path = "out",
        mode: Literal["dry-run", "apply"] = "dry-run",
        operator: str | None = None,
    ) -> "RunContext":
        timestamp = now_kst().strftime("%Y%m%dT%H%M%S")
        run_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return cls(run_id=run_id, output_dir=path, mode=mode, operator=operator)

    def path(self, *parts: str) -> Path:
        output_path = self.output_dir.joinpath(*parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

