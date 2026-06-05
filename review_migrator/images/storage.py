from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def public_url_for_file(path: str | Path, *, base_url: str | None = None) -> str | None:
    if not base_url:
        return None
    file_name = quote(Path(path).name)
    return f"{base_url.rstrip('/')}/{file_name}"

