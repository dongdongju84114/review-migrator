# Review Migrator

네이버 스마트스토어에서 사람이 다운로드한 리뷰 엑셀을 입력으로 받아 크리마 리뷰 등록용 CSV/API payload를 만들고, dry-run과 승인 게이트를 거쳐 안전하게 등록/검증하는 하네스형 파이프라인입니다.

## Quick Start

경영지원팀 실무자는 아래 파일을 더블클릭해서 GUI를 쓰면 됩니다.

```text
macOS: run_review_migrator_gui.command
Windows: run_review_migrator_gui.bat
```

Windows에서 `ReviewMigratorGUI.exe`를 받은 경우에는 EXE를 더블클릭하면 됩니다. 이 방식은 대상 PC에 Python 설치가 필요 없습니다.

EXE가 없고 개발 폴더를 그대로 쓰는 경우에는 `run_review_migrator_gui.bat`을 더블클릭합니다. Python 3.11 이상이 없으면 이 파일이 `winget`을 통해 Python 설치를 물어보거나 Python 다운로드 페이지를 열어줍니다. 첫 실행 때 `.venv` 가상환경을 만들고 필요한 패키지를 설치하므로 인터넷 연결이 필요할 수 있습니다. 한 번 준비된 뒤에는 같은 `.bat` 파일을 다시 더블클릭하면 바로 GUI가 열립니다.

Windows용 단독 EXE는 Windows PC에서 아래 명령으로 생성합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1
```

생성 결과는 `dist\ReviewMigratorGUI.exe`입니다. 이 EXE와 `.env`를 같은 폴더에 두고 운영 PC에 전달하면 Python 없이 실행할 수 있습니다. Windows EXE 실행 결과는 기본적으로 `내 문서\ReviewMigrator\operator_runs`에 저장됩니다.

GitHub Actions를 쓸 수 있는 저장소라면 `Build Windows EXE` 워크플로를 수동 실행해도 됩니다. 이 워크플로는 Windows 러너에서 테스트를 돌리고, EXE를 만든 뒤, 생성된 EXE를 `--smoke-test`로 실제 실행 확인한 다음 artifact로 업로드합니다.

GUI에서는 `네이버 리뷰 엑셀`, `마켓플러스 CSV`, `카페24 상품 CSV` 3개만 선택합니다. 상품 매핑은 항상 자동 생성하며, 안전 검증이 통과한 뒤에만 실제 등록을 진행할 수 있습니다.

개발자/운영자가 터미널에서 한 번에 실행하려면 `run-all`을 사용합니다.

```bash
python -m review_migrator run-all \
  --input data/naver_reviews.xlsx \
  --output-dir operator_runs \
  --auto-build-mapping \
  --crema-products-csv data/marketplus_products.csv \
  --cafe24-products-csv data/cafe24_products.csv
```

실제 크리마 등록까지 하려면 `.env` 설정 후 `--approve-upload`을 붙입니다.

먼저 크리마 API 권한만 확인할 수 있습니다. 이 명령은 리뷰를 만들거나 수정하지 않습니다.

```bash
python -m review_migrator check-crema-permissions \
  --env-file .env
```

`크리마 상품 조회 권한`이 실패하면 크리마 관리자/API 앱에 Product API 상품 조회 권한(`GET /v1/products`)을 추가하고 토큰을 갱신한 뒤 다시 확인합니다. 실제 등록에는 Review API 조회/생성/수정 권한(`GET/POST/PATCH /v1/reviews`)도 필요합니다.

```bash
python -m review_migrator run-all \
  --input data/naver_reviews.xlsx \
  --output-dir operator_runs \
  --auto-build-mapping \
  --approve-upload
```

네이버 엑셀의 `포토/영상` 이미지는 로컬로 다운로드한 뒤 Cafe24 FTP에 올리고, 그 공개 URL을 크리마에 전달합니다. 검증 실행에서는 FTP에 실제 업로드하지 않고 업로드 예정 URL만 계산하며, `--approve-upload` 실행 때만 FTP 업로드와 크리마 등록을 진행합니다.

`.env`에 필요한 FTP 설정:

```bash
CAFE24_FTP_HOST=
CAFE24_FTP_USER=
CAFE24_FTP_PASSWORD=
CAFE24_FTP_REMOTE_DIR=/www/review-images
CAFE24_IMAGE_BASE_URL=https://example.com/review-images
CAFE24_UPLOAD_PROTOCOL=sftp
CAFE24_FTP_PORT=8012
```

`CAFE24_IMAGE_BASE_URL`은 FTP 접속 호스트가 아니라 브라우저와 크리마 서버에서 실제로 열리는 공개 이미지 URL이어야 합니다. Cafe24 이미지 CDN을 쓰는 경우에는 `https://ecimg.cafe24img.com/.../web/upload/review-images`처럼 실제 이미지가 열리는 base URL을 넣습니다.

자동 매핑은 크리마 상품 목록을 읽고 확실한 상품만 `enabled=true`로 둡니다. 애매한 상품은 `product_mapping_review_required.csv`에 남기고 실제 등록을 막습니다.

매핑 CSV만 먼저 만들고 싶을 때:

```bash
python -m review_migrator build-product-mapping \
  --input data/naver_reviews.xlsx \
  --output config/product_mapping.generated.csv
```

마켓플러스 CSV의 `상품코드`는 카페24 `P000...` 코드입니다. 카페24 상품 CSV(`상품코드`, `상품번호`)를 같이 넣으면 `P000...`을 카페24 `product_no`로 변환하고, 이 값을 크리마 상품 `code`와 대조해서 더 정확히 자동 매핑합니다.

크리마 Product API 권한이 없으면 크리마에서 내려받은 상품 목록 CSV를 넣을 수 있습니다. 이 CSV에는 실제 크리마 `id` 또는 `code`와 상품명이 있어야 합니다.

```bash
python -m review_migrator build-product-mapping \
  --input data/naver_reviews.xlsx \
  --crema-products-csv data/crema_products.csv \
  --cafe24-products-csv data/cafe24_products.csv \
  --output config/product_mapping.generated.csv
```

개별 하네스만 실행하려면 아래처럼 사용할 수 있습니다.

```bash
python -m review_migrator normalize \
  --input tests/fixtures/sample_naver_reviews.xlsx \
  --output work/reviews_normalized.jsonl \
  --csv-output work/reviews_normalized.csv

python -m review_migrator build-crema-payload \
  --input work/reviews_normalized.jsonl \
  --mapping config/product_mapping.generated.csv \
  --output work/crema_payloads.jsonl \
  --dry-run
```

기본 실행은 dry-run입니다. 실제 크리마 등록은 `upload-crema --approve`가 있어야만 진행됩니다.
같은 결과 폴더에 `failed_mapping.csv`, `product_mapping_review_required.csv`, `image_matches_review_required.csv`, `payload_issues.jsonl` 오류가 남아 있으면 `upload-crema --approve`도 기본적으로 중단됩니다. 검토가 끝난 뒤 안전 검증을 다시 실행해서 상태가 `업로드 가능`인지 확인한 다음 실제 등록을 진행합니다.

## Safety Defaults

- 네이버 리뷰 조회 API가 있다는 전제로 구현하지 않습니다.
- 네이버 관리자 로그인 자동화, 비공식 크롤링, 캡차/2FA 우회는 포함하지 않습니다.
- 크리마 API 호출은 dry-run 우선이며, production에서는 validation error가 있으면 등록하지 않습니다.
- Cafe24 FTP 업로드도 실제 등록 승인 전에는 실행하지 않고, 검증 파일에는 예정 URL만 넣습니다.
- 토큰, app secret, 개인정보성 값은 audit/report에 원문 저장하지 않습니다.
- 리뷰 code는 `naver-review-{naver_product_no}-{naver_review_id}` 형태로 결정적으로 생성합니다. 크리마 CSV 양식에서 언더바를 허용하지 않기 때문에 하이픈을 사용합니다.
