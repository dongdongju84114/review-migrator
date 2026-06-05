from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_output_dir() -> Path:
    configured = os.getenv("REVIEW_MIGRATOR_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    if is_frozen_app():
        return (Path.home() / "Documents" / "ReviewMigrator" / "operator_runs").resolve()

    return (app_dir() / "operator_runs").resolve()


def default_env_file() -> Path:
    configured = os.getenv("REVIEW_MIGRATOR_ENV_FILE")
    if configured:
        return Path(configured).expanduser().resolve()

    candidate = app_dir() / ".env"
    if is_frozen_app() or candidate.exists():
        return candidate.resolve()

    return Path(".env").resolve()


def path_from_text(value: str, fallback: Path) -> Path:
    text = value.strip()
    if not text:
        return fallback
    return Path(text).expanduser()
