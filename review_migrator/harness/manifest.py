from __future__ import annotations

from datetime import datetime
from pathlib import Path

from review_migrator.schemas import RunManifest
from review_migrator.utils import dumps_json, file_checksum, now_kst


def create_manifest(
    run_id: str,
    started_at: datetime,
    mode: str = "dry-run",
    operator: str | None = None,
) -> RunManifest:
    return RunManifest(run_id=run_id, started_at=started_at, mode=mode, operator=operator)


def attach_existing_file(manifest: RunManifest, path: str | Path, kind: str) -> RunManifest:
    checksum = file_checksum(path)
    if kind == "input":
        manifest.input_files.append(checksum)
    elif kind == "output":
        manifest.output_files.append(checksum)
    else:
        raise ValueError("kind must be input or output")
    return manifest


def finish_manifest(manifest: RunManifest) -> RunManifest:
    manifest.finished_at = now_kst()
    return manifest


def write_manifest(path: str | Path, manifest: RunManifest) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dumps_json(manifest) + "\n", encoding="utf-8")

