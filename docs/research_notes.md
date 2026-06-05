# Research Notes

확인일: 2026-06-04

## 네이버 커머스API

- 공식 문서: <https://apicenter.commerce.naver.com/docs/introduction>
- 확인 버전: 문서 상단 기준 `2.79.0 (2026-05-26)`.
- 공식 문서는 커머스API가 스마트스토어의 주요 기능/콘텐츠를 HTTP API로 호출하는 구조이며, API 사용에는 커머스API센터 가입과 애플리케이션 등록/인증이 필요하다고 안내한다.
- REST 문서의 운영 호스트는 `https://api.commerce.naver.com/external`이고, 날짜/시간은 KST ISO 8601 규격을 따른다.
- 공식 문서 검색 기준으로 스마트스토어 리뷰를 조회/다운로드하는 Review API 항목은 확인되지 않았다. 따라서 1차 구현은 네이버 커머스API를 사용하지 않고, 사람이 관리자에서 다운로드한 엑셀 파일을 입력으로 받는다.
- 비공식 리뷰 크롤링, 관리자 로그인 자동화, 캡차/2FA 우회는 구현 범위에서 제외한다.

## CREMA API

- 시작하기: <https://dev.cre.ma/crema-api/getting-started>
- OAuth: <https://dev.cre.ma/crema-api/authentication>
- Product API: <https://dev.cre.ma/crema-api/product>
- Review API: <https://dev.cre.ma/crema-api/review>
- 모든 CREMA API 요청은 `api.cre.ma` host를 사용하며 `access_token`이 필요하다.
- OAuth는 client credentials 방식이며 `POST https://api.cre.ma/oauth/token`로 access token을 발급한다.
- Access token은 만료될 수 있고, 401 응답 시 재발급 후 재요청해야 한다.
- Product API는 `GET /v1/products`, code 기반 단일 상품 조회를 지원한다.
- Review API는 `POST /v1/reviews`로 리뷰 생성, `GET /v1/reviews?code=...`로 code 기반 조회, `PATCH /v1/reviews?code=...`로 수정할 수 있다.
- Review API의 이미지 입력은 `image_urls[]` 형태로 사용할 수 있으므로, 본 도구는 공개 접근 가능한 이미지 URL만 payload에 포함한다.
- 실제 등록 전 크리마 API 앱에 최소한 Product API 상품 조회 권한(`GET /v1/products`)과 Review API 조회/생성/수정 권한(`GET/POST/PATCH /v1/reviews`)이 있어야 한다.

## Implementation Decision

1차 구현은 다음 전제로 고정한다.

- 입력 source of truth는 사람이 다운로드한 네이버 리뷰 엑셀이다.
- 상품 매핑 없이 추측 등록하지 않는다.
- 크리마 product_id 또는 product_code 중 하나 이상이 확인된 리뷰만 payload를 만든다.
- 이미지 파일명만으로 확실히 매칭되는 경우만 자동 등록 후보로 삼고, 불확실한 후보는 review-required CSV로 분리한다.
- API 실제 등록은 approval gate 뒤에서만 실행한다.
