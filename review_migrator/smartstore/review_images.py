from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from review_migrator.naver_export.normalizer import normalize_naver_export
from review_migrator.utils import write_csv


SMARTSTORE_REVIEW_IMAGE_COLUMNS = [
    "naver_product_no",
    "naver_review_id",
    "image_url",
    "sort_order",
    "media_type",
    "source",
    "match_status",
    "match_basis",
]

SMARTSTORE_REVIEW_STATUS_COLUMNS = [
    "naver_product_no",
    "naver_review_id",
    "found",
    "image_count",
    "scroll_count",
    "message",
]

SORT_LABELS = {
    "latest": "최신순",
    "ranking": "랭킹순",
    "score_high": "평점 높은순",
    "score_low": "평점 낮은순",
}

LogFunc = Callable[[str], None]


@dataclass
class ParsedReviewItem:
    naver_review_id: str
    image_urls: list[str]


@dataclass
class SmartStoreReviewImageCollection:
    rows: list[dict[str, object]]
    status_rows: list[dict[str, object]]
    product_count: int
    target_review_count: int


class SmartStoreReviewHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: dict[str, ParsedReviewItem] = {}
        self._current_review_id: str | None = None
        self._current_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        review_id = _review_id_from_attrs(attr)
        if tag == "li" and review_id and self._current_review_id is None:
            self._current_review_id = review_id
            self._current_depth = 1
            self.items.setdefault(review_id, ParsedReviewItem(naver_review_id=review_id, image_urls=[]))
            return

        if self._current_review_id is not None:
            self._current_depth += 1
            if tag == "img" and _is_review_image(attr):
                image_url = _image_url_from_attrs(attr)
                if image_url:
                    item = self.items[self._current_review_id]
                    if image_url not in item.image_urls:
                        item.image_urls.append(image_url)

    def handle_endtag(self, tag: str) -> None:
        if self._current_review_id is None:
            return
        self._current_depth -= 1
        if self._current_depth <= 0:
            self._current_review_id = None
            self._current_depth = 0


def extract_smartstore_review_items(html: str) -> list[ParsedReviewItem]:
    parser = SmartStoreReviewHtmlParser()
    parser.feed(html)
    return list(parser.items.values())


def extract_smartstore_review_image_rows(
    html: str,
    *,
    naver_product_no: str = "",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in extract_smartstore_review_items(html):
        for index, image_url in enumerate(item.image_urls, start=1):
            rows.append(
                {
                    "naver_product_no": naver_product_no,
                    "naver_review_id": item.naver_review_id,
                    "image_url": image_url,
                    "sort_order": index,
                    "media_type": "image",
                    "source": "smartstore_review_modal",
                    "match_status": "matched",
                    "match_basis": "review_item_id",
                }
            )
    return rows


def collect_smartstore_review_images_from_export(
    naver_export_path: str | Path,
    *,
    store_id: str = "opengallery",
    sort: str = "latest",
    max_scrolls: int = 80,
    wait_after_scroll_ms: int = 700,
    headless: bool = False,
    browser_channel: str | None = "chrome",
    browser_user_data_dir: str | Path | None = None,
    product_limit: int | None = None,
    log: LogFunc | None = None,
) -> SmartStoreReviewImageCollection:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "스마트스토어 이미지 수집에는 playwright 패키지가 필요합니다. "
            "개발 환경에서는 `pip install 'review-migrator[collector]'` 후 다시 실행해주세요."
        ) from error

    logger = log or (lambda message: None)
    normalize_result = normalize_naver_export(naver_export_path)
    target_review_ids_by_product = _target_review_ids_by_product(normalize_result.records)
    if product_limit is not None:
        limited_items = list(target_review_ids_by_product.items())[:product_limit]
        target_review_ids_by_product = dict(limited_items)

    rows: list[dict[str, object]] = []
    status_rows: list[dict[str, object]] = []
    product_count = len(target_review_ids_by_product)
    target_review_count = sum(len(review_ids) for review_ids in target_review_ids_by_product.values())
    if not target_review_ids_by_product:
        return SmartStoreReviewImageCollection(
            rows=[],
            status_rows=[],
            product_count=0,
            target_review_count=0,
        )

    with sync_playwright() as playwright:
        context = _launch_browser_context(
            playwright,
            headless=headless,
            browser_channel=browser_channel,
            browser_user_data_dir=browser_user_data_dir,
            logger=logger,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for index, (product_no, target_review_ids) in enumerate(target_review_ids_by_product.items(), start=1):
                logger(
                    f"상품 {index}/{product_count} 리뷰 이미지 수집: "
                    f"{product_no} / 대상 리뷰 {len(target_review_ids)}건"
                )
                try:
                    product_rows, product_status_rows = _collect_product_review_images(
                        page,
                        store_id=store_id,
                        product_no=product_no,
                        target_review_ids=target_review_ids,
                        sort=sort,
                        max_scrolls=max_scrolls,
                        wait_after_scroll_ms=wait_after_scroll_ms,
                        logger=logger,
                    )
                except PlaywrightTimeoutError as error:
                    product_rows = []
                    product_status_rows = _status_rows_for_product(
                        product_no,
                        target_review_ids,
                        found_review_ids=set(),
                        image_count_by_review_id={},
                        scroll_count=0,
                        message=f"timeout: {error}",
                    )
                rows.extend(product_rows)
                status_rows.extend(product_status_rows)
        finally:
            context.close()

    return SmartStoreReviewImageCollection(
        rows=rows,
        status_rows=status_rows,
        product_count=product_count,
        target_review_count=target_review_count,
    )


def write_smartstore_review_image_rows(path: str | Path, rows: Iterable[dict[str, object]]) -> int:
    return write_csv(path, rows, SMARTSTORE_REVIEW_IMAGE_COLUMNS)


def write_smartstore_review_status_rows(path: str | Path, rows: Iterable[dict[str, object]]) -> int:
    return write_csv(path, rows, SMARTSTORE_REVIEW_STATUS_COLUMNS)


def _collect_product_review_images(
    page,
    *,
    store_id: str,
    product_no: str,
    target_review_ids: set[str],
    sort: str,
    max_scrolls: int,
    wait_after_scroll_ms: int,
    logger: LogFunc,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    product_url = f"https://smartstore.naver.com/{store_id}/products/{product_no}#REVIEW"
    page.goto(product_url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(1200)
    logger("  - 보안 인증 또는 로그인 화면이 보이면 열린 브라우저에서 직접 완료해주세요. 인증 쿠키는 다음 실행에도 유지됩니다.")
    _open_review_modal(page, logger=logger, timeout_seconds=150)
    _select_review_sort(page, sort)

    rows_by_key: dict[tuple[str, str], dict[str, object]] = {}
    found_review_ids: set[str] = set()
    image_count_by_review_id: dict[str, int] = {}
    previous_loaded_review_count = -1
    stable_scroll_count = 0
    scroll_count = 0

    for scroll_count in range(max_scrolls + 1):
        html = page.content()
        items = extract_smartstore_review_items(html)
        loaded_review_ids = {item.naver_review_id for item in items}
        found_review_ids.update(loaded_review_ids & target_review_ids)
        for item in items:
            if item.naver_review_id not in target_review_ids:
                continue
            image_count_by_review_id[item.naver_review_id] = len(item.image_urls)
            for index, image_url in enumerate(item.image_urls, start=1):
                key = (item.naver_review_id, image_url)
                rows_by_key.setdefault(
                    key,
                    {
                        "naver_product_no": product_no,
                        "naver_review_id": item.naver_review_id,
                        "image_url": image_url,
                        "sort_order": index,
                        "media_type": "image",
                        "source": "smartstore_review_modal",
                        "match_status": "matched",
                        "match_basis": "review_item_id",
                    },
                )

        if target_review_ids <= found_review_ids:
            logger(f"  - 대상 리뷰를 모두 찾았습니다. scroll={scroll_count}")
            break

        loaded_review_count = len(loaded_review_ids)
        if loaded_review_count == previous_loaded_review_count:
            stable_scroll_count += 1
        else:
            stable_scroll_count = 0
        previous_loaded_review_count = loaded_review_count
        if stable_scroll_count >= 5:
            logger("  - 더 이상 새 리뷰가 로드되지 않아 수집을 중단합니다.")
            break

        _scroll_review_modal_to_bottom(page)
        page.wait_for_timeout(wait_after_scroll_ms)

    status_rows = _status_rows_for_product(
        product_no,
        target_review_ids,
        found_review_ids=found_review_ids,
        image_count_by_review_id=image_count_by_review_id,
        scroll_count=scroll_count,
        message="",
    )
    return list(rows_by_key.values()), status_rows


def _target_review_ids_by_product(records) -> dict[str, set[str]]:
    target_review_ids_by_product: dict[str, set[str]] = defaultdict(set)
    for review in records:
        if review.has_image or review.source_image_urls:
            target_review_ids_by_product[review.naver_product_no].add(review.naver_review_id)
    return dict(target_review_ids_by_product)


def _status_rows_for_product(
    product_no: str,
    target_review_ids: set[str],
    *,
    found_review_ids: set[str],
    image_count_by_review_id: dict[str, int],
    scroll_count: int,
    message: str,
) -> list[dict[str, object]]:
    rows = []
    for review_id in sorted(target_review_ids):
        found = review_id in found_review_ids
        rows.append(
            {
                "naver_product_no": product_no,
                "naver_review_id": review_id,
                "found": "Y" if found else "N",
                "image_count": image_count_by_review_id.get(review_id, 0),
                "scroll_count": scroll_count,
                "message": message if not found else "",
            }
        )
    return rows


def _launch_browser_context(
    playwright,
    *,
    headless: bool,
    browser_channel: str | None,
    browser_user_data_dir: str | Path | None,
    logger: LogFunc,
):
    channels = []
    if browser_channel:
        channels.append(browser_channel)
    for channel in ["chrome", "msedge"]:
        if channel not in channels:
            channels.append(channel)

    user_data_dir = Path(browser_user_data_dir) if browser_user_data_dir else _default_browser_user_data_dir()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    common_options = {
        "headless": headless,
        "viewport": {"width": 1440, "height": 1100},
        "locale": "ko-KR",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "args": ["--no-first-run", "--no-default-browser-check"],
    }

    for channel in channels:
        try:
            return playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                channel=channel,
                **common_options,
            )
        except Exception:
            logger(f"  - {channel} 브라우저 실행 실패, 다음 브라우저로 재시도합니다.")

    logger("  - Chrome/Edge 실행 실패, Playwright 기본 Chromium으로 재시도합니다.")
    return playwright.chromium.launch_persistent_context(str(user_data_dir), **common_options)


def _open_review_modal(page, *, logger: LogFunc, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_log_at = 0.0
    while time.monotonic() < deadline:
        candidates = [
            page.get_by_role("button", name=re.compile("리뷰 전체보기|전체보기")).first,
            page.locator("button:has-text('리뷰 전체보기')").first,
            page.locator("a:has-text('리뷰 전체보기')").first,
            page.locator("button:has-text('전체보기')").first,
            page.locator("a:has-text('전체보기')").first,
        ]
        for locator in candidates:
            try:
                locator.click(timeout=3_000)
                page.wait_for_selector("li[id^='REVIEW_ITEM_']", timeout=8_000)
                return
            except Exception:
                continue

        try:
            page.wait_for_selector("li[id^='REVIEW_ITEM_']", timeout=2_000)
            return
        except Exception:
            pass

        now = time.monotonic()
        if now - last_log_at > 20:
            logger("  - 리뷰 모달을 기다리는 중입니다. 인증/로그인이 필요하면 브라우저에서 직접 완료해주세요.")
            last_log_at = now
        page.wait_for_timeout(1_000)
    raise TimeoutError("리뷰 전체보기 모달을 열 수 없습니다. 보안 인증/로그인 완료 여부를 확인해주세요.")


def _default_browser_user_data_dir() -> Path:
    return Path.home() / "Documents" / "ReviewMigrator" / "smartstore_browser_profile"


def _select_review_sort(page, sort: str) -> None:
    label = SORT_LABELS.get(sort, SORT_LABELS["latest"])
    candidates = [
        page.get_by_role("radio", name=re.compile(re.escape(label))).first,
        page.locator(f"button[role='radio']:has-text('{label}')").first,
        page.locator(f"button:has-text('{label}')").first,
    ]
    for locator in candidates:
        try:
            locator.click(timeout=4_000)
            page.wait_for_timeout(800)
            return
        except Exception:
            continue


def _scroll_review_modal_to_bottom(page) -> None:
    page.evaluate(
        """() => {
            const reviewItem = document.querySelector('li[id^="REVIEW_ITEM_"]');
            let node = reviewItem ? reviewItem.parentElement : null;
            while (node && node !== document.body) {
                const style = window.getComputedStyle(node);
                const overflowY = style.overflowY || '';
                if (node.scrollHeight > node.clientHeight && /(auto|scroll)/.test(overflowY)) {
                    node.scrollTop = node.scrollHeight;
                    return;
                }
                node = node.parentElement;
            }
            window.scrollTo(0, document.body.scrollHeight);
        }"""
    )


def _review_id_from_attrs(attrs: dict[str, str]) -> str:
    raw_id = attrs.get("id", "")
    match = re.match(r"REVIEW_ITEM_(?P<review_id>.+)", raw_id)
    if match:
        return match.group("review_id")
    return ""


def _is_review_image(attrs: dict[str, str]) -> bool:
    if attrs.get("alt") == "review_image":
        return True
    class_name = attrs.get("class", "")
    src = _image_url_from_attrs(attrs)
    return "checkout.phinf" in src and "contact/" not in src and "profile" not in class_name.lower()


def _image_url_from_attrs(attrs: dict[str, str]) -> str:
    url = attrs.get("data-src") or attrs.get("src") or ""
    if not url.startswith(("http://", "https://")):
        return ""
    return url
