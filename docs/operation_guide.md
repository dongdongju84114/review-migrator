# Operation Guide

## 0. GUI로 실행하기

경영지원팀 실무자는 터미널 명령어를 직접 쓰지 않고 아래 파일을 더블클릭한다.

```text
macOS: run_review_migrator_gui.command
Windows: run_review_migrator_gui.bat
Windows packaged app: ReviewMigratorGUI.exe
```

Windows 운영 PC에 Python을 설치하기 어렵다면 `ReviewMigratorGUI.exe`를 전달한다. 이 EXE는 대상 PC에 Python 설치가 필요 없다.

Windows용 EXE는 Windows 빌드 PC에서 아래 명령으로 만든다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1
```

생성 결과는 `dist\ReviewMigratorGUI.exe`다. 이 EXE와 `.env`를 같은 폴더에 두고 운영 PC에 전달한다. Windows EXE 실행 결과는 기본적으로 `내 문서\ReviewMigrator\operator_runs`에 저장된다.

GitHub Actions를 쓸 수 있는 저장소라면 `Build Windows EXE` 워크플로를 수동 실행한다. 이 워크플로는 Windows 러너에서 테스트를 돌리고, EXE를 만든 뒤, 생성된 EXE를 `--smoke-test`로 실제 실행 확인한 다음 artifact로 업로드한다.

EXE가 없고 개발 폴더를 그대로 전달하는 경우에는 `run_review_migrator_gui.bat`을 사용한다. Python 3.11 이상이 없으면 `.bat`이 `winget` 자동 설치를 물어보거나 Python 다운로드 페이지를 연다. 첫 실행 때 `.venv` 가상환경을 만들고 필요한 패키지를 설치하므로 인터넷 연결이 필요할 수 있다.

화면에서 아래 항목을 선택한다.

1. `네이버 리뷰 엑셀`: 스마트스토어 관리자에서 다운로드한 리뷰 엑셀
2. `마켓플러스 CSV`: 카페24 마켓플러스에서 네이버 스마트스토어로 필터해서 다운로드한 상품 CSV다.
3. `카페24 상품 CSV`: 카페24 상품 전체 목록 CSV다. `상품코드`와 `상품번호` 컬럼이 있어야 한다.

결과는 자동으로 기본 결과 폴더에 저장된다. Windows EXE는 `내 문서\ReviewMigrator\operator_runs`, macOS/개발 폴더 실행은 실행 폴더의 `operator_runs`를 사용한다. `.env`와 이미지 공개 URL은 미리 준비된 기본 설정을 사용한다.

먼저 `안전 검증 파일 만들기`를 누른다. 이 버튼은 크리마에 실제 등록하지 않는다.

결과 폴더에서 아래 파일을 확인한다.

- `run_summary.html`: 전체 결과 요약
- `product_mapping.generated.csv`: 자동 생성된 상품 매핑 파일
- `product_mapping_review_required.csv`: 사람이 확인해야 하는 상품 매핑 후보
- `failed_mapping.csv`: 상품 매핑 실패 목록
- `downloaded_images/`: 네이버에서 다운로드한 이미지 파일
- `downloaded_image_manifest.csv`: 원본 URL, 로컬 파일, 공개 URL 매칭 목록
- `image_matches_review_required.csv`: 사람이 확인해야 하는 이미지 후보
- `crema_other_reviews_upload.csv`: 크리마 CSV 업로드용 파일
- `crema_payloads.jsonl`: 크리마 API 등록 후보

`run_summary.html`에 `검토 필요`가 남아 있으면 실제 등록을 누르지 않는다. 특히 `product_mapping_review_required.csv`가 있으면 상품 연결을 사람이 확인해야 한다. 검토 필요가 남은 상태에서 실제 등록을 눌러도 도구는 크리마 등록과 Cafe24 FTP 업로드를 보류한다.
Cafe24 FTP 설정이나 이미지 공개 URL이 없으면 네이버 이미지는 로컬 다운로드까지만 완료되고, 크리마에는 이미지 URL을 넣지 않는다.

`안전 검증 파일 만들기`는 Cafe24 FTP에도 실제 업로드하지 않는다. `downloaded_image_manifest.csv`의 이미지 상태가 `planned`이면 실제 등록 승인 때 FTP에 올라갈 예정이라는 뜻이다.

실제 등록이 필요하면 안전 검증 상태가 `업로드 가능`인지 확인한 뒤, `크리마 권한 확인`을 먼저 누른다. 필수 권한이 실패하면 실제 등록을 진행하지 않는다. 필수 권한이 통과하면 화면에서 `실제 등록 승인`을 체크하고 `실제 크리마 등록 실행`을 누른다.

## 1. 입력 준비

1. 네이버 스마트스토어 관리자에서 리뷰 엑셀을 직접 다운로드한다.
2. 기간은 1년, 별점은 4점/5점 기준으로 검색하되, 도구도 1~3점 리뷰를 한 번 더 제외한다.
3. 상품 매핑은 기본적으로 도구가 자동 생성한다. 단, `product_mapping_review_required.csv`에 남은 항목은 사람이 확인해 수정한다.
4. 리뷰 이미지는 도구가 네이버 엑셀의 `포토/영상` URL에서 자동 다운로드한다. GUI에서 별도 이미지 폴더를 고를 필요는 없다.

## 1-1. Cafe24 FTP 설정

`.env`에 아래 값을 준비한다. 비밀번호는 문서나 리포트에 적지 않는다.

```bash
CAFE24_FTP_HOST=
CAFE24_FTP_USER=
CAFE24_FTP_PASSWORD=
CAFE24_FTP_REMOTE_DIR=/www/review-images
CAFE24_IMAGE_BASE_URL=https://example.com/review-images
CAFE24_UPLOAD_PROTOCOL=sftp
CAFE24_FTP_PORT=8012
```

- `CAFE24_FTP_REMOTE_DIR`: FTP 접속 후 이미지를 올릴 서버 폴더
- `CAFE24_IMAGE_BASE_URL`: 위 폴더가 웹에서 보이는 공개 URL
- SFTP 계정이면 `CAFE24_UPLOAD_PROTOCOL=sftp`와 SFTP 포트를 함께 입력한다.
- FTPS를 쓰는 계정이면 `CAFE24_UPLOAD_PROTOCOL=ftps` 또는 `CAFE24_FTP_USE_TLS=true`를 추가한다.

`CAFE24_IMAGE_BASE_URL`은 FTP 호스트 주소가 아니라 실제 이미지가 브라우저에서 열리는 공개 주소여야 한다. Cafe24 이미지 CDN을 쓰는 경우 `https://ecimg.cafe24img.com/.../web/upload/review-images`처럼 파일명 앞까지의 base URL을 넣는다. 실제 등록 실행 때 도구가 업로드된 이미지 공개 URL을 확인하며, 접근 실패가 있으면 크리마 등록을 중단한다.

## 2. 표준화

전체 과정을 한 번에 실행하려면 다음 명령을 쓴다.

```bash
python -m review_migrator run-all \
  --input data/naver_reviews.xlsx \
  --output-dir operator_runs \
  --auto-build-mapping \
  --crema-products-csv data/marketplus_products.csv \
  --cafe24-products-csv data/cafe24_products.csv
```

마켓플러스 CSV의 `상품코드(P000...)`는 카페24 관리 상품코드이고, 카페24 상품 CSV의 `상품번호`가 크리마에 저장된 상품 `code`와 대응한다. 도구는 `마켓상품코드` → `상품코드(P000...)` → `상품번호(product_no)` → 크리마 상품 `code` 순서로 자동 보정한다.

크리마 Product API 권한이 없어서 상품 목록 조회가 막히면, 크리마에서 내려받은 상품 목록 CSV를 받아 다음처럼 실행한다. 이 CSV에는 실제 크리마 `id` 또는 `code`와 상품명이 있어야 한다.

```bash
python -m review_migrator run-all \
  --input data/naver_reviews.xlsx \
  --crema-products-csv data/crema_products.csv \
  --cafe24-products-csv data/cafe24_products.csv \
  --output-dir operator_runs \
  --auto-build-mapping
```

아래 명령들은 각 단계를 따로 점검할 때 사용한다.

```bash
python -m review_migrator normalize \
  --input data/naver_reviews.xlsx \
  --output out/reviews_normalized.jsonl \
  --csv-output out/reviews_normalized.csv
```

## 3. 상품 매핑 검증

```bash
python -m review_migrator validate-naver-export \
  --input data/naver_reviews.xlsx \
  --mapping operator_runs/{run_id}/product_mapping.generated.csv
```

매핑 실패 건은 등록 대상에서 제외하고 `failed_mapping.csv`로 분리한다. `failed_mapping.csv`나 `product_mapping_review_required.csv`에 데이터가 있으면 실제 등록은 진행하지 않는다.

## 4. 크리마 CSV 생성

```bash
python -m review_migrator build-crema-csv \
  --input out/reviews_normalized.jsonl \
  --mapping operator_runs/{run_id}/product_mapping.generated.csv \
  --output out/crema_other_reviews_upload.csv
```

## 5. 이미지 매칭

```bash
python -m review_migrator match-images \
  --reviews out/reviews_normalized.jsonl \
  --image-dir data/review_images \
  --base-url https://cdn.example.com/review-images \
  --output out/image_matches.csv
```

불확실한 후보는 `out/image_matches_review_required.csv`로 분리된다.

## 6. Payload dry-run

```bash
python -m review_migrator build-crema-payload \
  --input out/reviews_normalized.jsonl \
  --mapping operator_runs/{run_id}/product_mapping.generated.csv \
  --image-matches out/image_matches.csv \
  --dry-run \
  --output out/crema_payloads.jsonl
```

## 7. 실제 등록

환경변수:

```bash
CREMA_APP_ID=
CREMA_SECRET=
CREMA_ACCESS_TOKEN=
CREMA_API_BASE_URL=https://api.cre.ma
REVIEW_MIGRATOR_ENV=local
CAFE24_FTP_HOST=
CAFE24_FTP_USER=
CAFE24_FTP_PASSWORD=
CAFE24_FTP_REMOTE_DIR=/www/review-images
CAFE24_IMAGE_BASE_URL=https://example.com/review-images
CAFE24_UPLOAD_PROTOCOL=sftp
CAFE24_FTP_PORT=8012
```

실제 등록 전에 권한을 먼저 확인한다. 이 명령은 리뷰를 생성하거나 수정하지 않는다.

```bash
python -m review_migrator check-crema-permissions \
  --env-file .env \
  --output out/crema_permission_checks.csv
```

`크리마 상품 조회 권한(Permission denied)`이 나오면 크리마 관리자/API 앱에 아래 권한을 추가한다.

- Product API 상품 조회 권한: `GET /v1/products`
- Review API 리뷰 조회 권한: `GET /v1/reviews`
- Review API 리뷰 생성 권한: `POST /v1/reviews`
- Review API 리뷰 수정 권한: `PATCH /v1/reviews`

권한 추가 후에는 새 access token을 발급하거나 `.env`의 `CREMA_ACCESS_TOKEN`을 갱신하고, 같은 권한 확인 명령을 다시 실행한다. 실행 중 access token이 만료되어 401 응답을 받으면 도구가 `CREMA_APP_ID`와 `CREMA_SECRET`으로 새 토큰을 발급하고 `.env`의 `CREMA_ACCESS_TOKEN=` 줄을 자동 갱신한다.

실제 등록:

```bash
python -m review_migrator upload-crema \
  --payload out/crema_payloads.jsonl \
  --mode create-or-update \
  --approve
```

`--approve` 없이는 실제 API 등록을 하지 않는다.
`crema_payloads.jsonl`과 같은 폴더에 검토 필요 산출물이 남아 있으면 위 명령도 기본 중단된다. 일부 payload만 의도적으로 올리는 예외 상황에서는 `--allow-partial-upload`을 붙일 수 있지만, 일반 운영에서는 쓰지 않는다.

## 8. 등록 검증

```bash
python -m review_migrator verify-crema \
  --payload out/crema_payloads.jsonl \
  --output reports/run_latest.html
```

검증 리포트는 등록 수, 상품 매핑, 작성일, 별점, 본문 해시, display, 이미지 수를 비교한다.
