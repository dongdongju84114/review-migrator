from __future__ import annotations

import sqlite3
from pathlib import Path

from review_migrator.utils import now_kst


class IdempotencyRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_registry (
                code TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                run_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def seen(self, code: str) -> bool:
        cursor = self.connection.execute("SELECT 1 FROM review_registry WHERE code = ?", (code,))
        return cursor.fetchone() is not None

    def record(self, code: str, *, status: str, run_id: str | None = None) -> None:
        now = now_kst().isoformat()
        self.connection.execute(
            """
            INSERT INTO review_registry (code, status, run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                status = excluded.status,
                run_id = excluded.run_id,
                updated_at = excluded.updated_at
            """,
            (code, status, run_id, now, now),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

