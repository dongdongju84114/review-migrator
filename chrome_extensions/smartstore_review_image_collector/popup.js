const statusEl = document.getElementById('status');
const collectButton = document.getElementById('collect');
const collectTargetsButton = document.getElementById('collectTargets');
const loadTargetCsvButton = document.getElementById('loadTargetCsv');
const downloadLoadedButton = document.getElementById('downloadLoaded');
const stopButton = document.getElementById('stop');
const targetCsvInput = document.getElementById('targetCsv');

let targetData = null;

restoreTargetSummary();

targetCsvInput.addEventListener('change', async () => {
  await loadSelectedTargetCsv();
});

loadTargetCsvButton.addEventListener('click', async () => {
  await loadSelectedTargetCsv();
});

async function loadSelectedTargetCsv() {
  const file = targetCsvInput.files && targetCsvInput.files[0];
  if (!file) {
    setStatus('대상 CSV를 먼저 선택해주세요.');
    return null;
  }
  try {
    setStatus('대상 CSV를 읽는 중입니다.');
    const text = await file.text();
    targetData = parseTargetCsv(text, file.name);
    await saveTargetData(targetData);
    setStatus(targetSummary(targetData));
    return targetData;
  } catch (error) {
    setStatus(`대상 CSV 읽기 실패: ${error.message || error}`);
    return null;
  }
}

collectButton.addEventListener('click', () => {
  sendToActiveTab('SMARTSTORE_COLLECT_IMAGES', {
    sort: document.getElementById('sort').value,
    maxScrolls: Number(document.getElementById('maxScrolls').value || 80),
    waitMs: Number(document.getElementById('waitMs').value || 700),
  });
});

collectTargetsButton.addEventListener('click', async () => {
  const data = await getTargetData();
  if (!data || !data.products || !data.products.length) {
    setStatus('대상 CSV를 먼저 불러와주세요.');
    return;
  }
  sendToActiveTab('SMARTSTORE_START_TARGET_COLLECTION', {
    sort: document.getElementById('sort').value,
    maxScrolls: Number(document.getElementById('maxScrolls').value || 80),
    waitMs: Number(document.getElementById('waitMs').value || 700),
    storeId: document.getElementById('storeId').value || 'opengallery',
    targetData: data,
  });
});

downloadLoadedButton.addEventListener('click', () => {
  sendToActiveTab('SMARTSTORE_DOWNLOAD_LOADED_IMAGES', {});
});

stopButton.addEventListener('click', () => {
  sendToActiveTab('SMARTSTORE_STOP_COLLECTION', {});
});

async function sendToActiveTab(type, payload) {
  setStatus('요청을 보냈습니다. 진행 상황은 페이지 오른쪽 위 패널에서 확인해주세요.');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      setStatus('활성 탭을 찾지 못했습니다.');
      return;
    }
    if (!/^https:\/\/smartstore\.naver\.com\/.+\/products\//.test(tab.url || '')) {
      setStatus('스마트스토어 상품 페이지에서 실행해주세요.');
      return;
    }
    let response;
    try {
      response = await chrome.tabs.sendMessage(tab.id, { type, payload });
    } catch (error) {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
      });
      response = await chrome.tabs.sendMessage(tab.id, { type, payload });
    }
    setStatus(response && response.message ? response.message : '실행을 시작했습니다.');
  } catch (error) {
    setStatus(`실행 실패: ${error.message || error}`);
  }
}

function setStatus(message) {
  statusEl.textContent = message;
}

async function restoreTargetSummary() {
  const data = await getStoredTargetData();
  if (!data) {
    return;
  }
  targetData = data;
  setStatus(targetSummary(data));
}

async function getTargetData() {
  if (targetData && targetData.products && targetData.products.length) {
    return targetData;
  }
  const loaded = await loadSelectedTargetCsv();
  if (loaded) {
    return loaded;
  }
  const stored = await getStoredTargetData();
  if (stored && stored.products && stored.products.length) {
    targetData = stored;
    setStatus(targetSummary(stored));
    return stored;
  }
  return null;
}

async function saveTargetData(data) {
  try {
    await chrome.storage.local.set({ smartstoreTargetData: data });
  } catch (error) {
    // The current popup can still send the parsed data even if storage is unavailable.
  }
}

async function getStoredTargetData() {
  try {
    return (await chrome.storage.local.get('smartstoreTargetData')).smartstoreTargetData;
  } catch (error) {
    return null;
  }
}

function parseTargetCsv(text, fileName) {
  const rows = parseCsv(text);
  if (!rows.length) {
    throw new Error('CSV에 데이터가 없습니다.');
  }
  const header = rows[0].map((value) => normalizeHeader(value));
  const productIndex = findHeaderIndex(header, [
    'naver_product_no',
    'product_no',
    '상품번호',
    '상품 번호',
    '상품 no',
  ]);
  const reviewIndex = findHeaderIndex(header, [
    'naver_review_id',
    'review_id',
    '리뷰번호',
    '리뷰 번호',
    '리뷰 id',
  ]);
  if (productIndex < 0 || reviewIndex < 0) {
    throw new Error('naver_product_no/naver_review_id 컬럼을 찾지 못했습니다.');
  }

  const productMap = new Map();
  let rowCount = 0;
  for (const row of rows.slice(1)) {
    const productNo = cleanCell(row[productIndex]);
    const reviewId = cleanCell(row[reviewIndex]);
    if (!productNo || !reviewId) {
      continue;
    }
    if (!productMap.has(productNo)) {
      productMap.set(productNo, new Set());
    }
    productMap.get(productNo).add(reviewId);
    rowCount += 1;
  }

  const products = Array.from(productMap.entries()).map(([productNo, reviewIdSet]) => ({
    productNo,
    reviewIds: Array.from(reviewIdSet),
  }));
  if (!products.length) {
    throw new Error('수집 대상 리뷰가 없습니다.');
  }
  return {
    fileName,
    loadedAt: new Date().toISOString(),
    rowCount,
    productCount: products.length,
    reviewCount: products.reduce((total, product) => total + product.reviewIds.length, 0),
    products,
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = '';
  let inQuotes = false;
  const normalized = text.replace(/^\uFEFF/, '');

  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index];
    const next = normalized[index + 1];
    if (inQuotes) {
      if (char === '"' && next === '"') {
        value += '"';
        index += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        value += char;
      }
      continue;
    }
    if (char === '"') {
      inQuotes = true;
    } else if (char === ',') {
      row.push(value);
      value = '';
    } else if (char === '\n') {
      row.push(value);
      rows.push(row);
      row = [];
      value = '';
    } else if (char !== '\r') {
      value += char;
    }
  }
  row.push(value);
  if (row.length > 1 || row[0]) {
    rows.push(row);
  }
  return rows;
}

function findHeaderIndex(headers, candidates) {
  return headers.findIndex((header) => candidates.some((candidate) => header === normalizeHeader(candidate)));
}

function normalizeHeader(value) {
  return cleanCell(value).replace(/\s+/g, ' ').toLowerCase();
}

function cleanCell(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function targetSummary(data) {
  return [
    `대상 CSV: ${data.fileName || ''}`,
    `상품 ${data.productCount || 0}개`,
    `리뷰 ${data.reviewCount || 0}건`,
  ].join('\n');
}
