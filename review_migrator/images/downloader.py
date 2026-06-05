from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from review_migrator.schemas import ImageMatch, NormalizedReview
from review_migrator.utils import write_csv


def download_review_images(
    reviews: list[NormalizedReview],
    *,
    download_dir: str | Path,
    public_dir: str | Path | None = None,
    public_base_url: str | None = None,
    timeout: float = 30,
) -> tuple[list[ImageMatch], list[dict[str, object]]]:
    output_dir = Path(download_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    public_output_dir = Path(public_dir) if public_dir else None
    if public_output_dir:
        public_output_dir.mkdir(parents=True, exist_ok=True)

    matches: list[ImageMatch] = []
    manifest_rows: list[dict[str, object]] = []

    for review in reviews:
        if not review.source_image_urls:
            continue
        image_files: list[str] = []
        image_urls: list[str] = []
        warning = None
        for index, source_url in enumerate(review.source_image_urls, start=1):
            if index > 4:
                warning = "more than 4 source images; only first 4 were downloaded for CREMA"
                break
            file_name = _image_file_name(review.naver_review_id, index, source_url)
            local_path = output_dir / file_name
            try:
                download_url_to_file(source_url, local_path, timeout=timeout)
            except Exception as error:
                warning = f"download failed: {error}"
                manifest_rows.append(
                    {
                        "naver_review_id": review.naver_review_id,
                        "idempotency_code": review.idempotency_code,
                        "source_url": source_url,
                        "local_file": str(local_path),
                        "remote_file": "",
                        "public_file": "",
                        "public_url": "",
                        "status": "failed",
                    }
                )
                continue
            image_files.append(str(local_path))

            public_path = ""
            public_url = ""
            if public_output_dir:
                target_path = public_output_dir / file_name
                shutil.copy2(local_path, target_path)
                public_path = str(target_path)
                if public_base_url:
                    public_url = f"{public_base_url.rstrip('/')}/{file_name}"
                    image_urls.append(public_url)

            manifest_rows.append(
                {
                    "naver_review_id": review.naver_review_id,
                    "idempotency_code": review.idempotency_code,
                    "source_url": source_url,
                    "local_file": str(local_path),
                    "remote_file": "",
                    "public_file": public_path,
                    "public_url": public_url,
                    "status": "downloaded",
                }
            )

        matches.append(
            ImageMatch(
                naver_review_id=review.naver_review_id,
                idempotency_code=review.idempotency_code,
                image_files=image_files,
                image_urls=image_urls,
                confidence=1.0,
                auto_match=True,
                warning=warning if warning else ("public URL missing; image is staged locally only" if image_files and not image_urls else None),
            )
        )

    return matches, manifest_rows


def download_url_to_file(url: str, path: str | Path, *, timeout: float = 30) -> None:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 review-migrator",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        Path(path).write_bytes(response.read())


def write_download_manifest(path: str | Path, rows: list[dict[str, object]]) -> int:
    return write_csv(
        path,
        rows,
        [
            "naver_review_id",
            "idempotency_code",
            "source_url",
            "local_file",
            "remote_file",
            "public_file",
            "public_url",
            "status",
        ],
    )


def _image_file_name(naver_review_id: str, index: int, source_url: str) -> str:
    parsed = urlparse(source_url)
    suffix = Path(parsed.path).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(mimetypes.guess_type(source_url)[0] or "") or ".jpg"
    return f"{naver_review_id}_{index}{suffix}"
