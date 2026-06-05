from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from review_migrator.utils import write_csv


PUBLIC_IMAGE_URL_CHECK_COLUMNS = ["url", "ok", "status_code", "content_type", "error"]


@dataclass(frozen=True)
class PublicImageUrlCheck:
    url: str
    ok: bool
    status_code: int | None = None
    content_type: str | None = None
    error: str | None = None

    def as_row(self) -> dict[str, object]:
        return {
            "url": self.url,
            "ok": "true" if self.ok else "false",
            "status_code": self.status_code or "",
            "content_type": self.content_type or "",
            "error": self.error or "",
        }


UrlOpenFunc = Callable[..., Any]


def check_public_image_url(url: str, *, timeout: float = 10, opener: UrlOpenFunc = urlopen) -> PublicImageUrlCheck:
    head_check = _request_public_image_url(url, method="HEAD", timeout=timeout, opener=opener)
    if head_check.ok:
        return head_check
    if head_check.status_code in {403, 405}:
        return _request_public_image_url(url, method="GET", timeout=timeout, opener=opener)
    return head_check


def check_public_image_urls(
    urls: Iterable[str],
    *,
    timeout: float = 10,
    opener: UrlOpenFunc = urlopen,
) -> list[PublicImageUrlCheck]:
    return [check_public_image_url(url, timeout=timeout, opener=opener) for url in dict.fromkeys(urls) if url]


def write_public_image_url_checks(path, checks: list[PublicImageUrlCheck]) -> None:
    write_csv(path, [check.as_row() for check in checks], PUBLIC_IMAGE_URL_CHECK_COLUMNS)


def _request_public_image_url(
    url: str,
    *,
    method: str,
    timeout: float,
    opener: UrlOpenFunc,
) -> PublicImageUrlCheck:
    headers = {"User-Agent": "ReviewMigrator/1.0"}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    request = Request(url, method=method, headers=headers)
    try:
        with opener(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            content_type = response.headers.get("Content-Type")
            if method == "GET":
                response.read(1)
            error = _image_content_type_error(content_type)
            return PublicImageUrlCheck(
                url=url,
                ok=200 <= status_code < 400 and error is None,
                status_code=status_code,
                content_type=content_type,
                error=error,
            )
    except HTTPError as error:
        return PublicImageUrlCheck(
            url=url,
            ok=False,
            status_code=error.code,
            content_type=error.headers.get("Content-Type") if error.headers else None,
            error=f"HTTP {error.code}",
        )
    except URLError as error:
        reason = getattr(error, "reason", error)
        return PublicImageUrlCheck(url=url, ok=False, error=str(reason))
    except Exception as error:
        return PublicImageUrlCheck(url=url, ok=False, error=str(error))


def _image_content_type_error(content_type: str | None) -> str | None:
    if not content_type:
        return None
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("image/") or media_type == "application/octet-stream":
        return None
    return f"not an image content type: {content_type}"
