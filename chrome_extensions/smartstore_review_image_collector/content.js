(function () {
if (window.__OG_SMARTSTORE_REVIEW_IMAGE_COLLECTOR__) {
  return;
}
window.__OG_SMARTSTORE_REVIEW_IMAGE_COLLECTOR__ = true;

const SMARTSTORE_COLLECTOR = {
  running: false,
  stopRequested: false,
};

const SORT_LABELS = {
  latest: '최신순',
  ranking: '랭킹순',
  score_high: '평점 높은순',
  score_low: '평점 낮은순',
};

const TARGET_STATE_KEY = 'ogSmartstoreReviewImageTargetState';
const IMAGE_CSV_HEADERS = [
  'naver_product_no',
  'naver_review_id',
  'image_url',
  'sort_order',
  'media_type',
  'source',
  'match_status',
  'match_basis',
];
const STATUS_CSV_HEADERS = [
  'naver_product_no',
  'naver_review_id',
  'found',
  'image_count',
  'scroll_count',
  'message',
];

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return false;
  }

  if (message.type === 'SMARTSTORE_COLLECT_IMAGES') {
    if (SMARTSTORE_COLLECTOR.running) {
      sendResponse({ ok: false, message: '이미 수집 중입니다.' });
      return false;
    }
    collectReviewImages(message.payload || {});
    sendResponse({ ok: true, message: '수집을 시작했습니다. 페이지 오른쪽 위 패널을 확인해주세요.' });
    return false;
  }

  if (message.type === 'SMARTSTORE_START_TARGET_COLLECTION') {
    if (SMARTSTORE_COLLECTOR.running) {
      sendResponse({ ok: false, message: '이미 수집 중입니다.' });
      return false;
    }
    startTargetCollection(message.payload || {});
    sendResponse({ ok: true, message: '대상 CSV 기준 수집을 시작했습니다.' });
    return false;
  }

  if (message.type === 'SMARTSTORE_DOWNLOAD_LOADED_IMAGES') {
    const rows = collectRowsFromLoadedReviews();
    downloadRows(rows, 'loaded');
    sendResponse({ ok: true, message: `현재 로드된 이미지 URL ${rows.length}건을 CSV로 저장했습니다.` });
    return false;
  }

  if (message.type === 'SMARTSTORE_STOP_COLLECTION') {
    SMARTSTORE_COLLECTOR.stopRequested = true;
    const state = loadTargetState();
    if (state && state.running && !SMARTSTORE_COLLECTOR.running) {
      finishTargetCollection(state, '중지됨');
    }
    sendResponse({ ok: true, message: '중지 요청을 보냈습니다.' });
    return false;
  }

  return false;
});

resumeTargetCollectionIfNeeded();

async function collectReviewImages(options) {
  SMARTSTORE_COLLECTOR.running = true;
  SMARTSTORE_COLLECTOR.stopRequested = false;
  const maxScrolls = clampNumber(options.maxScrolls, 80, 1, 500);
  const waitMs = clampNumber(options.waitMs, 700, 100, 5000);
  const sort = options.sort || 'latest';

  try {
    updateOverlay('수집 준비 중', '리뷰 영역으로 이동합니다.');
    ensureReviewHash();
    await wait(700);

    await openReviewModal();
    await wait(700);
    await selectSort(sort);
    await wait(900);

    let previousReviewCount = -1;
    let stableScrollCount = 0;
    for (let index = 0; index <= maxScrolls; index += 1) {
      if (SMARTSTORE_COLLECTOR.stopRequested) {
        updateOverlay('중지됨', '사용자 요청으로 수집을 멈췄습니다.');
        break;
      }

      const rows = collectRowsFromLoadedReviews();
      const reviewCount = countLoadedReviews();
      updateOverlay(
        '수집 중',
        `스크롤 ${index}/${maxScrolls}\n로드 리뷰 ${reviewCount}건\n이미지 URL ${rows.length}건`
      );

      if (reviewCount === previousReviewCount) {
        stableScrollCount += 1;
      } else {
        stableScrollCount = 0;
      }
      if (stableScrollCount >= 6) {
        updateOverlay('수집 완료', `더 이상 새 리뷰가 로드되지 않았습니다.\n이미지 URL ${rows.length}건`);
        break;
      }
      previousReviewCount = reviewCount;

      scrollReviewContainer();
      await wait(waitMs);
    }

    const rows = collectRowsFromLoadedReviews();
    downloadRows(rows, 'collected');
    updateOverlay('CSV 저장 완료', `이미지 URL ${rows.length}건을 저장했습니다.`);
  } catch (error) {
    updateOverlay('수집 실패', error.message || String(error));
  } finally {
    SMARTSTORE_COLLECTOR.running = false;
    SMARTSTORE_COLLECTOR.stopRequested = false;
  }
}

async function startTargetCollection(payload) {
  const targetData = payload.targetData || {};
  const products = Array.isArray(targetData.products) ? targetData.products : [];
  if (!products.length) {
    updateOverlay('수집 실패', '대상 CSV 데이터가 없습니다.');
    return;
  }

  const state = {
    mode: 'target',
    running: true,
    storeId: payload.storeId || storeIdFromUrl() || 'opengallery',
    sort: payload.sort || 'latest',
    maxScrolls: clampNumber(payload.maxScrolls, 80, 1, 500),
    waitMs: clampNumber(payload.waitMs, 700, 100, 5000),
    productIndex: 0,
    products: products.map((product) => ({
      productNo: String(product.productNo || '').trim(),
      reviewIds: Array.from(new Set((product.reviewIds || []).map((reviewId) => String(reviewId).trim()).filter(Boolean))),
    })).filter((product) => product.productNo && product.reviewIds.length),
    rows: [],
    statusRows: [],
    startedAt: new Date().toISOString(),
  };
  if (!state.products.length) {
    updateOverlay('수집 실패', '대상 CSV에서 유효한 상품번호/리뷰ID를 찾지 못했습니다.');
    return;
  }
  saveTargetState(state);
  await continueTargetCollection();
}

async function resumeTargetCollectionIfNeeded() {
  const state = loadTargetState();
  if (!state || !state.running || state.mode !== 'target') {
    return;
  }
  await wait(900);
  continueTargetCollection();
}

async function continueTargetCollection() {
  const state = loadTargetState();
  if (!state || !state.running) {
    return;
  }
  const product = state.products[state.productIndex];
  if (!product) {
    finishTargetCollection(state, '완료');
    return;
  }

  const currentProductNo = productNoFromUrl();
  if (currentProductNo !== product.productNo) {
    updateOverlay(
      '상품 이동 중',
      `상품 ${state.productIndex + 1}/${state.products.length}\n${product.productNo}`
    );
    window.location.href = productUrl(state.storeId, product.productNo);
    return;
  }

  SMARTSTORE_COLLECTOR.running = true;
  SMARTSTORE_COLLECTOR.stopRequested = false;
  try {
    await collectTargetProduct(state, product);
    const nextState = loadTargetState() || state;
    if (!nextState.running) {
      return;
    }
    nextState.productIndex += 1;
    saveTargetState(nextState);
    if (nextState.productIndex >= nextState.products.length) {
      finishTargetCollection(nextState, '완료');
      return;
    }
    const nextProduct = nextState.products[nextState.productIndex];
    updateOverlay(
      '다음 상품 이동 중',
      `상품 ${nextState.productIndex + 1}/${nextState.products.length}\n${nextProduct.productNo}`
    );
    window.location.href = productUrl(nextState.storeId, nextProduct.productNo);
  } catch (error) {
    const failedState = loadTargetState() || state;
    appendStatusRowsForProduct(failedState, product, new Set(), {}, 0, error.message || String(error));
    failedState.productIndex += 1;
    saveTargetState(failedState);
    if (failedState.productIndex >= failedState.products.length) {
      finishTargetCollection(failedState, '오류 포함 완료');
      return;
    }
    const nextProduct = failedState.products[failedState.productIndex];
    updateOverlay('상품 수집 실패', `${product.productNo}: ${error.message || error}\n다음 상품으로 이동합니다.`);
    await wait(1200);
    window.location.href = productUrl(failedState.storeId, nextProduct.productNo);
  } finally {
    SMARTSTORE_COLLECTOR.running = false;
    SMARTSTORE_COLLECTOR.stopRequested = false;
  }
}

async function collectTargetProduct(state, product) {
  updateOverlay(
    '상품 수집 준비 중',
    `상품 ${state.productIndex + 1}/${state.products.length}\n${product.productNo}\n대상 리뷰 ${product.reviewIds.length}건`
  );
  ensureReviewHash();
  await wait(700);
  await openReviewModal();
  await wait(700);
  await selectSort(state.sort);
  await wait(900);

  const targetReviewIds = new Set(product.reviewIds);
  const foundReviewIds = new Set();
  const imageCountByReviewId = {};
  let previousReviewCount = -1;
  let stableScrollCount = 0;
  let lastScrollIndex = 0;

  for (let scrollIndex = 0; scrollIndex <= state.maxScrolls; scrollIndex += 1) {
    lastScrollIndex = scrollIndex;
    if (SMARTSTORE_COLLECTOR.stopRequested) {
      const stoppedState = loadTargetState() || state;
      stoppedState.running = false;
      saveTargetState(stoppedState);
      finishTargetCollection(stoppedState, '중지됨');
      return;
    }

    const loadedReviewIds = new Set(
      Array.from(document.querySelectorAll('li[id^="REVIEW_ITEM_"]'))
        .map((item) => reviewIdFromElement(item))
        .filter(Boolean)
    );
    for (const reviewId of loadedReviewIds) {
      if (targetReviewIds.has(reviewId)) {
        foundReviewIds.add(reviewId);
      }
    }

    const rows = collectRowsFromLoadedReviews(targetReviewIds);
    const currentState = loadTargetState() || state;
    mergeImageRows(currentState, rows);
    for (const row of rows) {
      imageCountByReviewId[row.naver_review_id] = Math.max(
        Number(imageCountByReviewId[row.naver_review_id] || 0),
        Number(row.sort_order || 0)
      );
    }
    saveTargetState(currentState);

    updateOverlay(
      '대상 수집 중',
      [
        `상품 ${state.productIndex + 1}/${state.products.length}: ${product.productNo}`,
        `스크롤 ${scrollIndex}/${state.maxScrolls}`,
        `대상 리뷰 ${targetReviewIds.size}건`,
        `찾은 리뷰 ${foundReviewIds.size}건`,
        `이미지 URL 누적 ${currentState.rows.length}건`,
      ].join('\n')
    );

    if (targetReviewIds.size && foundReviewIds.size >= targetReviewIds.size) {
      break;
    }

    const reviewCount = countLoadedReviews();
    if (reviewCount === previousReviewCount) {
      stableScrollCount += 1;
    } else {
      stableScrollCount = 0;
    }
    if (stableScrollCount >= 6) {
      break;
    }
    previousReviewCount = reviewCount;
    scrollReviewContainer();
    await wait(state.waitMs);
  }

  const completedState = loadTargetState() || state;
  appendStatusRowsForProduct(
    completedState,
    product,
    foundReviewIds,
    imageCountByReviewId,
    lastScrollIndex,
    ''
  );
  saveTargetState(completedState);
}

function finishTargetCollection(state, title) {
  state.running = false;
  state.rows = Array.isArray(state.rows) ? state.rows : [];
  state.statusRows = Array.isArray(state.statusRows) ? state.statusRows : [];
  saveTargetState(state);
  downloadRows(state.rows || [], 'targets');
  downloadStatusRows(state.statusRows || []);
  clearTargetState();
  updateOverlay(title, `이미지 URL ${state.rows.length}건\n상태 ${state.statusRows.length}건\nCSV 저장 완료`);
}

async function openReviewModal() {
  if (document.querySelector('li[id^="REVIEW_ITEM_"]')) {
    return;
  }

  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const button = findClickableByText(/리뷰\s*전체보기|전체보기/);
    if (button) {
      button.click();
      await wait(1200);
      if (document.querySelector('li[id^="REVIEW_ITEM_"]')) {
        return;
      }
    }
    window.scrollBy({ top: Math.round(window.innerHeight * 0.8), behavior: 'smooth' });
    await wait(900);
  }
  throw new Error('리뷰 전체보기 버튼 또는 리뷰 항목을 찾지 못했습니다.');
}

async function selectSort(sort) {
  const label = SORT_LABELS[sort] || SORT_LABELS.latest;
  const button = findClickableByText(new RegExp(escapeRegExp(label)));
  if (!button) {
    return;
  }
  button.click();
  await wait(900);
}

function collectRowsFromLoadedReviews(targetReviewIds) {
  const productNo = productNoFromUrl();
  const rows = [];
  const seen = new Set();
  const items = Array.from(document.querySelectorAll('li[id^="REVIEW_ITEM_"]'));

  for (const item of items) {
    const reviewId = reviewIdFromElement(item);
    if (!reviewId) {
      continue;
    }
    if (targetReviewIds && !targetReviewIds.has(reviewId)) {
      continue;
    }
    const imageUrls = reviewImageUrlsFromItem(item);
    imageUrls.forEach((imageUrl, index) => {
      const key = `${reviewId}|${imageUrl}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      rows.push({
        naver_product_no: productNo,
        naver_review_id: reviewId,
        image_url: imageUrl,
        sort_order: index + 1,
        media_type: 'image',
        source: 'chrome_extension',
        match_status: 'matched',
        match_basis: 'review_item_id',
      });
    });
  }

  return rows;
}

function mergeImageRows(state, rows) {
  const seen = new Set((state.rows || []).map((row) => `${row.naver_review_id}|${row.image_url}`));
  for (const row of rows) {
    const key = `${row.naver_review_id}|${row.image_url}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    state.rows.push(row);
  }
}

function appendStatusRowsForProduct(state, product, foundReviewIds, imageCountByReviewId, scrollCount, message) {
  const existing = new Set(
    (state.statusRows || []).map((row) => `${row.naver_product_no}|${row.naver_review_id}`)
  );
  for (const reviewId of product.reviewIds) {
    const key = `${product.productNo}|${reviewId}`;
    if (existing.has(key)) {
      continue;
    }
    const found = foundReviewIds.has(reviewId);
    state.statusRows.push({
      naver_product_no: product.productNo,
      naver_review_id: reviewId,
      found: found ? 'Y' : 'N',
      image_count: imageCountByReviewId[reviewId] || 0,
      scroll_count: scrollCount,
      message: found ? '' : message || 'target review was not loaded before scroll limit',
    });
  }
}

function saveTargetState(state) {
  window.sessionStorage.setItem(TARGET_STATE_KEY, JSON.stringify(state));
}

function loadTargetState() {
  const raw = window.sessionStorage.getItem(TARGET_STATE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const state = JSON.parse(raw);
    state.rows = Array.isArray(state.rows) ? state.rows : [];
    state.statusRows = Array.isArray(state.statusRows) ? state.statusRows : [];
    state.products = Array.isArray(state.products) ? state.products : [];
    return state;
  } catch (error) {
    window.sessionStorage.removeItem(TARGET_STATE_KEY);
    return null;
  }
}

function clearTargetState() {
  window.sessionStorage.removeItem(TARGET_STATE_KEY);
}

function reviewImageUrlsFromItem(item) {
  const urls = [];
  const seen = new Set();
  const images = Array.from(
    item.querySelectorAll('img[alt="review_image"], img[src*="checkout.phinf"], img[data-src*="checkout.phinf"]')
  );

  for (const image of images) {
    const url = image.getAttribute('data-src') || image.getAttribute('src') || '';
    if (!/^https?:\/\//.test(url)) {
      continue;
    }
    if (url.includes('/contact/') || url.includes('profile')) {
      continue;
    }
    if (seen.has(url)) {
      continue;
    }
    seen.add(url);
    urls.push(url);
  }
  return urls;
}

function downloadRows(rows, suffix) {
  const productNo = productNoFromUrl() || 'unknown_product';
  const timestamp = timestampForFileName();
  const filename = `additional_review_images_${productNo}_${suffix}_${timestamp}.csv`;
  const csv = rowsToCsv(rows, IMAGE_CSV_HEADERS);
  downloadCsvText(csv, filename);
}

function downloadStatusRows(rows) {
  const timestamp = timestampForFileName();
  const csv = rowsToCsv(rows, STATUS_CSV_HEADERS);
  downloadCsvText(csv, `additional_review_images_targets_status_${timestamp}.csv`);
}

function downloadCsvText(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function rowsToCsv(rows, headers) {
  const lines = [headers.join(',')];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(','));
  }
  return `\uFEFF${lines.join('\r\n')}\r\n`;
}

function csvCell(value) {
  const text = value === null || value === undefined ? '' : String(value);
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function scrollReviewContainer() {
  const container = findScrollableReviewContainer();
  if (container === window) {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    return;
  }
  container.scrollTop = container.scrollHeight;
}

function findScrollableReviewContainer() {
  const reviewItem = document.querySelector('li[id^="REVIEW_ITEM_"]');
  let node = reviewItem ? reviewItem.parentElement : null;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    const overflowY = style.overflowY || '';
    if (node.scrollHeight > node.clientHeight + 40 && /(auto|scroll)/.test(overflowY)) {
      return node;
    }
    node = node.parentElement;
  }
  return window;
}

function countLoadedReviews() {
  return document.querySelectorAll('li[id^="REVIEW_ITEM_"]').length;
}

function findClickableByText(pattern) {
  const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], [role="radio"]'));
  return candidates.find((element) => isVisible(element) && pattern.test(normalizedText(element)));
}

function isVisible(element) {
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
}

function normalizedText(element) {
  return (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
}

function reviewIdFromElement(element) {
  const match = /^REVIEW_ITEM_(.+)$/.exec(element.id || '');
  return match ? match[1] : '';
}

function productNoFromUrl() {
  const match = /\/products\/(\d+)/.exec(window.location.pathname);
  return match ? match[1] : '';
}

function storeIdFromUrl() {
  const match = /^\/([^/]+)\/products\//.exec(window.location.pathname);
  return match ? match[1] : '';
}

function productUrl(storeId, productNo) {
  return `https://smartstore.naver.com/${encodeURIComponent(storeId)}/products/${encodeURIComponent(productNo)}#REVIEW`;
}

function ensureReviewHash() {
  if (window.location.hash !== '#REVIEW') {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#REVIEW`);
  }
}

function updateOverlay(title, message) {
  const overlay = ensureOverlay();
  overlay.querySelector('[data-og-title]').textContent = title;
  overlay.querySelector('[data-og-message]').textContent = message;
}

function ensureOverlay() {
  let overlay = document.getElementById('og-smartstore-review-image-collector');
  if (overlay) {
    return overlay;
  }
  overlay = document.createElement('div');
  overlay.id = 'og-smartstore-review-image-collector';
  overlay.innerHTML = `
    <div data-og-title></div>
    <pre data-og-message></pre>
  `;
  Object.assign(overlay.style, {
    position: 'fixed',
    top: '16px',
    right: '16px',
    zIndex: '2147483647',
    width: '280px',
    padding: '14px',
    borderRadius: '8px',
    border: '1px solid rgba(15, 23, 42, 0.2)',
    background: 'rgba(255, 255, 255, 0.96)',
    color: '#0f172a',
    boxShadow: '0 12px 36px rgba(15, 23, 42, 0.18)',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    fontSize: '13px',
    lineHeight: '1.45',
  });
  const title = overlay.querySelector('[data-og-title]');
  Object.assign(title.style, {
    marginBottom: '8px',
    fontWeight: '800',
    fontSize: '14px',
  });
  const message = overlay.querySelector('[data-og-message]');
  Object.assign(message.style, {
    margin: '0',
    whiteSpace: 'pre-wrap',
    fontFamily: 'inherit',
  });
  document.documentElement.appendChild(overlay);
  return overlay;
}

function clampNumber(value, fallback, min, max) {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, value));
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function timestampForFileName() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    '_',
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
  ].join('');
}
})();
