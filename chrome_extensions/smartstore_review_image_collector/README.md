# SmartStore Review Image Collector

스마트스토어 상품 리뷰 모달에서 리뷰 이미지 URL을 모아 `additional_review_images_*.csv`로 다운로드하는 Chrome 확장프로그램입니다.

## 설치

1. Chrome에서 `chrome://extensions`를 엽니다.
2. 오른쪽 위 `개발자 모드`를 켭니다.
3. `압축해제된 확장 프로그램을 로드합니다`를 누릅니다.
4. 이 폴더를 선택합니다.

```text
chrome_extensions/smartstore_review_image_collector
```

## 사용: 대상 CSV 기준 자동 수집

1. 크리마 등록 도구에서 `안전 검증 파일 만들기`를 먼저 실행합니다.
2. 결과 폴더에서 `smartstore_image_targets.csv`를 찾습니다.
3. 일반 Chrome에서 스마트스토어 상품 페이지를 엽니다.
   예: `https://smartstore.naver.com/opengallery/products/13058129101#REVIEW`
4. 네이버 보안 인증이나 로그인이 나오면 직접 완료합니다.
5. Chrome 오른쪽 위 확장프로그램 아이콘에서 `SmartStore Review Image Collector`를 엽니다.
6. `대상 CSV`에 `smartstore_image_targets.csv`를 넣습니다. 파일을 선택하면 자동으로 읽히며, 필요하면 `선택한 대상 CSV 확인`을 눌러 상품/리뷰 수를 확인합니다.
7. `대상 CSV 기준 자동 수집`을 누릅니다.
8. 확장프로그램이 상품 페이지를 자동으로 이동하며 리뷰 모달을 열고, 대상 리뷰 ID만 찾아 이미지 URL을 수집합니다.
9. 수집이 끝나면 `additional_review_images_*_targets_YYYYMMDD_HHMMSS.csv`와 상태 CSV가 다운로드됩니다.
10. 크리마 등록 도구 GUI의 `추가 이미지 CSV(선택)`에 이미지 CSV를 넣고 `안전 검증 파일 만들기`를 다시 실행합니다.

## 버튼

- `선택한 대상 CSV 확인`: `smartstore_image_targets.csv`를 읽고 상품/리뷰 수를 확인합니다.
- `대상 CSV 기준 자동 수집`: 대상 CSV의 상품을 순서대로 열고, 해당 리뷰 ID의 이미지만 수집합니다.
- `현재 상품 전체 이미지 CSV`: 현재 상품의 리뷰 전체보기 모달을 열고 선택한 정렬 기준으로 스크롤하며 이미지 URL을 수집합니다.
- `현재 로드된 리뷰만 CSV`: 이미 화면에 로드된 리뷰만 파싱해서 바로 CSV를 저장합니다.
- `중지`: 진행 중인 스크롤 수집을 멈춥니다.

## CSV 컬럼

```csv
naver_product_no,naver_review_id,image_url,sort_order,media_type,source,match_status,match_basis
```

이 CSV는 크리마 등록 도구의 `추가 이미지 CSV(선택)` 입력으로 바로 사용할 수 있습니다.
