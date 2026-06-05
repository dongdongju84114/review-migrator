from __future__ import annotations

import csv
import re
from pathlib import Path

from review_migrator.schemas import ImageMatch, NormalizedReview
from review_migrator.utils import write_csv

from .storage import public_url_for_file

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def discover_image_files(image_dir: str | Path) -> list[Path]:
    directory = Path(image_dir)
    if not directory.exists():
        raise FileNotFoundError(directory)
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def match_images(
    reviews: list[NormalizedReview],
    image_dir: str | Path,
    *,
    base_url: str | None = None,
) -> tuple[list[ImageMatch], list[ImageMatch]]:
    files = discover_image_files(image_dir)
    exact_by_review_id: dict[str, list[Path]] = {}
    uncertain_by_product: dict[str, list[Path]] = {}
    for file_path in files:
        stem = file_path.stem
        exact_match = re.match(r"^(?P<review_id>[^_]+)_(?P<index>\d+)$", stem)
        if exact_match:
            exact_by_review_id.setdefault(exact_match.group("review_id"), []).append(file_path)
            continue
        product_match = re.match(r"^(?P<product_no>[^_]+)_", stem)
        if product_match:
            uncertain_by_product.setdefault(product_match.group("product_no"), []).append(file_path)

    confirmed: list[ImageMatch] = []
    review_required: list[ImageMatch] = []
    for review in reviews:
        exact_files = exact_by_review_id.get(review.naver_review_id, [])
        if exact_files:
            limited_files = exact_files[:4]
            warning = None
            if len(exact_files) > 4:
                warning = "more than 4 images; only first 4 are auto matched"
            confirmed.append(
                ImageMatch(
                    naver_review_id=review.naver_review_id,
                    idempotency_code=review.idempotency_code,
                    image_files=[str(path) for path in limited_files],
                    image_urls=[
                        url
                        for path in limited_files
                        if (url := public_url_for_file(path, base_url=base_url)) is not None
                    ],
                    confidence=1.0,
                    auto_match=True,
                    warning=warning,
                )
            )
            continue

        candidates = uncertain_by_product.get(review.naver_product_no, [])
        if candidates:
            review_required.append(
                ImageMatch(
                    naver_review_id=review.naver_review_id,
                    idempotency_code=review.idempotency_code,
                    image_files=[str(path) for path in candidates[:10]],
                    image_urls=[
                        url
                        for path in candidates[:10]
                        if (url := public_url_for_file(path, base_url=base_url)) is not None
                    ],
                    confidence=0.35,
                    auto_match=False,
                    warning="filename does not include review id; human review required",
                )
            )

    return confirmed, review_required


def write_image_matches(path: str | Path, matches: list[ImageMatch]) -> int:
    fieldnames = [
        "naver_review_id",
        "idempotency_code",
        "image_files",
        "image_urls",
        "confidence",
        "auto_match",
        "warning",
    ]
    rows = [
        {
            "naver_review_id": match.naver_review_id,
            "idempotency_code": match.idempotency_code,
            "image_files": "|".join(match.image_files),
            "image_urls": "|".join(match.image_urls),
            "confidence": match.confidence,
            "auto_match": match.auto_match,
            "warning": match.warning or "",
        }
        for match in matches
    ]
    return write_csv(path, rows, fieldnames)


def read_image_matches(path: str | Path) -> list[ImageMatch]:
    matches: list[ImageMatch] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            matches.append(
                ImageMatch(
                    naver_review_id=row["naver_review_id"],
                    idempotency_code=row["idempotency_code"],
                    image_files=[item for item in row.get("image_files", "").split("|") if item],
                    image_urls=[item for item in row.get("image_urls", "").split("|") if item],
                    confidence=float(row.get("confidence") or 0),
                    auto_match=str(row.get("auto_match", "")).lower() in {"1", "true", "yes", "y"},
                    warning=row.get("warning") or None,
                )
            )
    return matches

