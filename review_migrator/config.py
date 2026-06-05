from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    crema_app_id: str | None
    crema_secret: str | None
    crema_access_token: str | None
    crema_api_base_url: str
    env: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            crema_app_id=os.getenv("CREMA_APP_ID"),
            crema_secret=os.getenv("CREMA_SECRET"),
            crema_access_token=os.getenv("CREMA_ACCESS_TOKEN"),
            crema_api_base_url=os.getenv("CREMA_API_BASE_URL", "https://api.cre.ma"),
            env=os.getenv("REVIEW_MIGRATOR_ENV", "local"),
        )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

