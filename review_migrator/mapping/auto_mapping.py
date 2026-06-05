from __future__ import annotations

import json
import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from review_migrator.schemas import NormalizedReview, ProductMapping
from review_migrator.utils import write_csv


@dataclass(frozen=True)
class CremaProduct:
    id: int | None
    code: str | None
    name: str


@dataclass(frozen=True)
class MappingCandidate:
    naver_product_no: str
    naver_product_name: str
    crema_product_id: int | None
    crema_product_code: str | None
    crema_product_name: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class AutoMappingResult:
    mappings: list[ProductMapping]
    candidate_rows: list[dict[str, object]]
    review_required_rows: list[dict[str, object]]


def load_crema_products_from_json(path: str | Path) -> list[CremaProduct]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("products", data.get("items", []))
    return [_product_from_api(item) for item in data]


def load_crema_products_from_csv(path: str | Path) -> list[CremaProduct]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
    if not rows:
        return []
    headers = list(rows[0].keys())
    id_column = _detect_product_column(headers, ["상품 번호", "product_id", "id", "상품번호"])
    code_column = _detect_product_column(headers, ["상품 코드", "product_code", "code", "상품코드"])
    name_column = _detect_product_column(headers, ["상품명", "상품 이름", "product_name", "name"])
    if not name_column:
        raise ValueError("상품명/name 컬럼을 찾을 수 없습니다.")

    products: list[CremaProduct] = []
    for row in rows:
        product_id_raw = str(row.get(id_column) or "").strip() if id_column else ""
        products.append(
            CremaProduct(
                id=int(float(product_id_raw)) if product_id_raw else None,
                code=str(row.get(code_column) or "").strip() if code_column else None,
                name=str(row.get(name_column) or "").strip(),
            )
        )
    return [product for product in products if product.name]


def is_marketplus_product_csv(path: str | Path) -> bool:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
    return _detect_product_column(headers, ["마켓상품코드"]) is not None and _detect_product_column(headers, ["상품코드"]) is not None


def extract_marketplus_cafe24_product_codes(path: str | Path) -> list[str]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        cafe24_code_column = _detect_product_column(headers, ["상품코드"])
        if not cafe24_code_column:
            return []
        return sorted(
            {
                clean_export_value(row.get(cafe24_code_column))
                for row in reader
                if clean_export_value(row.get(cafe24_code_column))
            }
        )


def load_cafe24_product_no_by_product_code_csv(path: str | Path) -> dict[str, str]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        code_column = _detect_product_column(headers, ["상품코드", "product_code", "code"])
        product_no_column = _detect_product_column(headers, ["상품번호", "product_no", "product_id"])
        if not code_column or not product_no_column:
            raise ValueError("카페24 상품 CSV에서 상품코드/상품번호 컬럼을 찾을 수 없습니다.")

        mapping: dict[str, str] = {}
        for row in reader:
            product_code = clean_export_value(row.get(code_column))
            product_no = clean_export_value(row.get(product_no_column))
            if product_code and product_no:
                mapping[product_code] = product_no
    return mapping


def build_mapping_from_marketplus_csv(
    reviews: list[NormalizedReview],
    path: str | Path,
    *,
    crema_products: list[CremaProduct] | None = None,
    cafe24_product_no_by_code: dict[str, str] | None = None,
    allow_marketplus_code_fallback: bool = False,
    auto_confidence_threshold: float = 0.94,
    review_confidence_threshold: float = 0.72,
) -> AutoMappingResult:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        headers = reader.fieldnames or []

    market_code_column = _detect_product_column(headers, ["마켓상품코드"])
    cafe24_code_column = _detect_product_column(headers, ["상품코드"])
    internal_code_column = _detect_product_column(headers, ["자체상품코드"])
    name_column = _detect_product_column(headers, ["상품명", "product_name", "name"])
    if not market_code_column or not cafe24_code_column or not name_column:
        raise ValueError("마켓플러스 CSV에서 마켓상품코드/상품코드/상품명 컬럼을 찾을 수 없습니다.")

    unique_naver_products: dict[str, str] = {}
    for review in reviews:
        unique_naver_products.setdefault(review.naver_product_no, review.naver_product_name)

    market_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        market_product_no = clean_export_value(row.get(market_code_column))
        if market_product_no:
            market_rows.setdefault(market_product_no, []).append(row)

    mappings: list[ProductMapping] = []
    candidate_rows: list[dict[str, object]] = []
    review_required_rows: list[dict[str, object]] = []

    for naver_product_no, naver_product_name in sorted(unique_naver_products.items()):
        matched_rows = market_rows.get(naver_product_no, [])
        product_codes = sorted({clean_export_value(row.get(cafe24_code_column)) for row in matched_rows if clean_export_value(row.get(cafe24_code_column))})
        if len(product_codes) == 1:
            row = matched_rows[0]
            cafe24_product_code = product_codes[0]
            market_product_name = clean_export_value(row.get(name_column))
            internal_product_code = clean_export_value(row.get(internal_code_column)) if internal_code_column else None
            if crema_products is not None:
                cafe24_product_no = (cafe24_product_no_by_code or {}).get(cafe24_product_code)
                result = _resolve_marketplus_row_with_crema_products(
                    naver_product_no=naver_product_no,
                    naver_product_name=naver_product_name,
                    market_product_name=market_product_name,
                    cafe24_product_no=cafe24_product_no,
                    internal_product_code=internal_product_code,
                    crema_products=crema_products,
                    auto_confidence_threshold=auto_confidence_threshold,
                    review_confidence_threshold=review_confidence_threshold,
                )
                mappings.append(result.mappings[0])
                candidate_rows.extend(result.candidate_rows)
                review_required_rows.extend(result.review_required_rows)
                continue

            if not allow_marketplus_code_fallback:
                mappings.append(
                    ProductMapping(
                        naver_product_no=naver_product_no,
                        crema_product_id=None,
                        crema_product_code=None,
                        internal_product_code=internal_product_code or None,
                        product_name=market_product_name or naver_product_name,
                        enabled=False,
                    )
                )
                candidate_rows.append(
                    {
                        "naver_product_no": naver_product_no,
                        "naver_product_name": naver_product_name,
                        "crema_product_id": "",
                        "crema_product_code": cafe24_product_code,
                        "crema_product_name": market_product_name or naver_product_name,
                        "confidence": 0,
                        "reason": "marketplus_code_is_not_crema_key",
                    }
                )
                review_required_rows.append(
                    {
                        "naver_product_no": naver_product_no,
                        "naver_product_name": market_product_name or naver_product_name,
                        "best_crema_product_id": "",
                        "best_crema_product_code": cafe24_product_code,
                        "best_crema_product_name": "",
                        "best_confidence": 0,
                        "reason": "crema_products_required_for_marketplus",
                    }
                )
                continue

            mappings.append(
                ProductMapping(
                    naver_product_no=naver_product_no,
                    crema_product_id=None,
                    crema_product_code=cafe24_product_code,
                    internal_product_code=internal_product_code or None,
                    product_name=market_product_name or naver_product_name,
                    enabled=True,
                )
            )
            candidate_rows.append(
                {
                    "naver_product_no": naver_product_no,
                    "naver_product_name": naver_product_name,
                    "crema_product_id": "",
                    "crema_product_code": cafe24_product_code,
                    "crema_product_name": market_product_name or naver_product_name,
                    "confidence": 1.0,
                    "reason": "marketplus_code_exact",
                }
            )
            continue

        mappings.append(
            ProductMapping(
                naver_product_no=naver_product_no,
                crema_product_id=None,
                crema_product_code=None,
                internal_product_code=None,
                product_name=naver_product_name,
                enabled=False,
            )
        )
        review_required_rows.append(
            {
                "naver_product_no": naver_product_no,
                "naver_product_name": naver_product_name,
                "best_crema_product_id": "",
                "best_crema_product_code": ", ".join(product_codes),
                "best_crema_product_name": "",
                "best_confidence": 0,
                "reason": "marketplus_not_found" if not matched_rows else "marketplus_ambiguous_product_code",
            }
        )

    return AutoMappingResult(
        mappings=mappings,
        candidate_rows=candidate_rows,
        review_required_rows=review_required_rows,
    )


def _resolve_marketplus_row_with_crema_products(
    *,
    naver_product_no: str,
    naver_product_name: str,
    market_product_name: str,
    cafe24_product_no: str | None = None,
    internal_product_code: str | None,
    crema_products: list[CremaProduct],
    auto_confidence_threshold: float,
    review_confidence_threshold: float,
) -> AutoMappingResult:
    match_name = market_product_name or naver_product_name
    exact_code_candidates = [
        MappingCandidate(
            naver_product_no=naver_product_no,
            naver_product_name=match_name,
            crema_product_id=product.id,
            crema_product_code=product.code,
            crema_product_name=product.name,
            confidence=1.0,
            reason="cafe24_product_no_exact",
        )
        for product in crema_products
        if cafe24_product_no and str(product.code or "").strip() == str(cafe24_product_no).strip()
    ]
    if len(exact_code_candidates) == 1:
        best = exact_code_candidates[0]
        return AutoMappingResult(
            mappings=[
                ProductMapping(
                    naver_product_no=naver_product_no,
                    crema_product_id=best.crema_product_id,
                    crema_product_code=best.crema_product_code,
                    internal_product_code=internal_product_code or None,
                    product_name=match_name,
                    enabled=True,
                )
            ],
            candidate_rows=[_candidate_row(best)],
            review_required_rows=[],
        )

    candidates = find_candidates(naver_product_no, match_name, crema_products)
    if exact_code_candidates:
        candidates = [*exact_code_candidates, *candidates]
    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    auto_enabled = bool(
        best
        and best.confidence >= auto_confidence_threshold
        and (second is None or best.confidence - second.confidence >= 0.06)
    )

    candidate_rows = [
        _candidate_row(candidate)
        for candidate in candidates
        if candidate.confidence >= review_confidence_threshold
    ]
    if auto_enabled and best:
        return AutoMappingResult(
            mappings=[
                ProductMapping(
                    naver_product_no=naver_product_no,
                    crema_product_id=best.crema_product_id,
                    crema_product_code=best.crema_product_code,
                    internal_product_code=internal_product_code or None,
                    product_name=match_name,
                    enabled=True,
                )
            ],
            candidate_rows=candidate_rows,
            review_required_rows=[],
        )

    return AutoMappingResult(
        mappings=[
            ProductMapping(
                naver_product_no=naver_product_no,
                crema_product_id=None,
                crema_product_code=None,
                internal_product_code=internal_product_code or None,
                product_name=match_name,
                enabled=False,
            )
        ],
        candidate_rows=candidate_rows,
        review_required_rows=[
            {
                "naver_product_no": naver_product_no,
                "naver_product_name": match_name,
                "best_crema_product_id": best.crema_product_id if best else "",
                "best_crema_product_code": best.crema_product_code if best else "",
                "best_crema_product_name": best.crema_product_name if best else "",
                "best_confidence": round(best.confidence, 4) if best else 0,
                "reason": "marketplus_crema_no_candidate" if not best else "marketplus_crema_ambiguous_or_low_confidence",
            }
        ],
    )


def fetch_crema_products(product_service: Any, *, max_pages: int = 50, limit: int = 100) -> list[CremaProduct]:
    products: list[CremaProduct] = []
    seen: set[tuple[int | None, str | None]] = set()
    for page in range(1, max_pages + 1):
        response = product_service.client.get("/v1/products", params={"limit": limit, "page": page})
        if not response:
            break
        if not isinstance(response, list):
            response = response.get("products", response.get("items", []))
        page_products = [_product_from_api(item) for item in response]
        new_products = []
        for product in page_products:
            key = (product.id, product.code)
            if key in seen:
                continue
            seen.add(key)
            new_products.append(product)
        products.extend(new_products)
        if len(page_products) < limit:
            break
    return products


def build_auto_mapping(
    reviews: list[NormalizedReview],
    crema_products: list[CremaProduct],
    *,
    auto_confidence_threshold: float = 0.94,
    review_confidence_threshold: float = 0.72,
) -> AutoMappingResult:
    unique_naver_products: dict[str, str] = {}
    for review in reviews:
        unique_naver_products.setdefault(review.naver_product_no, review.naver_product_name)

    mappings: list[ProductMapping] = []
    candidate_rows: list[dict[str, object]] = []
    review_required_rows: list[dict[str, object]] = []

    for naver_product_no, naver_product_name in sorted(unique_naver_products.items()):
        candidates = find_candidates(naver_product_no, naver_product_name, crema_products)
        candidate_rows.extend(_candidate_row(candidate) for candidate in candidates)
        best = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        auto_enabled = bool(
            best
            and best.confidence >= auto_confidence_threshold
            and (second is None or best.confidence - second.confidence >= 0.06)
        )

        if auto_enabled and best:
            mappings.append(
                ProductMapping(
                    naver_product_no=naver_product_no,
                    crema_product_id=best.crema_product_id,
                    crema_product_code=best.crema_product_code,
                    internal_product_code=None,
                    product_name=naver_product_name,
                    enabled=True,
                )
            )
            continue

        mappings.append(
            ProductMapping(
                naver_product_no=naver_product_no,
                crema_product_id=None,
                crema_product_code=None,
                internal_product_code=None,
                product_name=naver_product_name,
                enabled=False,
            )
        )
        review_required_rows.append(
            {
                "naver_product_no": naver_product_no,
                "naver_product_name": naver_product_name,
                "best_crema_product_id": best.crema_product_id if best else "",
                "best_crema_product_code": best.crema_product_code if best else "",
                "best_crema_product_name": best.crema_product_name if best else "",
                "best_confidence": round(best.confidence, 4) if best else 0,
                "reason": "no_candidate" if not best else "ambiguous_or_low_confidence",
            }
        )

    return AutoMappingResult(
        mappings=mappings,
        candidate_rows=[
            row for row in candidate_rows if float(row["confidence"]) >= review_confidence_threshold
        ],
        review_required_rows=review_required_rows,
    )


def find_candidates(
    naver_product_no: str,
    naver_product_name: str,
    crema_products: list[CremaProduct],
) -> list[MappingCandidate]:
    candidates = []
    for product in crema_products:
        confidence, reason = score_candidate(naver_product_no, naver_product_name, product)
        if confidence <= 0:
            continue
        candidates.append(
            MappingCandidate(
                naver_product_no=naver_product_no,
                naver_product_name=naver_product_name,
                crema_product_id=product.id,
                crema_product_code=product.code,
                crema_product_name=product.name,
                confidence=confidence,
                reason=reason,
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)


def score_candidate(naver_product_no: str, naver_product_name: str, product: CremaProduct) -> tuple[float, str]:
    if product.code and str(product.code).strip() == str(naver_product_no).strip():
        return 1.0, "code_exact"

    naver_name = _normalize_name(naver_product_name)
    crema_name = _normalize_name(product.name)
    if not naver_name or not crema_name:
        return 0, "empty_name"
    if naver_name == crema_name:
        return 0.97, "name_exact"
    if naver_name in crema_name or crema_name in naver_name:
        return 0.9, "name_contains"
    ratio = SequenceMatcher(None, naver_name, crema_name).ratio()
    return ratio, "name_similarity"


def write_auto_mapping_outputs(
    *,
    mapping_path: str | Path,
    candidates_path: str | Path,
    review_required_path: str | Path,
    result: AutoMappingResult,
) -> None:
    write_csv(
        mapping_path,
        [_mapping_row(mapping) for mapping in result.mappings],
        [
            "naver_product_no",
            "crema_product_id",
            "crema_product_code",
            "internal_product_code",
            "product_name",
            "enabled",
            "note",
        ],
    )
    write_csv(
        candidates_path,
        result.candidate_rows,
        [
            "naver_product_no",
            "naver_product_name",
            "crema_product_id",
            "crema_product_code",
            "crema_product_name",
            "confidence",
            "reason",
        ],
    )
    write_csv(
        review_required_path,
        result.review_required_rows,
        [
            "naver_product_no",
            "naver_product_name",
            "best_crema_product_id",
            "best_crema_product_code",
            "best_crema_product_name",
            "best_confidence",
            "reason",
        ],
    )


def _product_from_api(item: dict[str, Any]) -> CremaProduct:
    product_id = item.get("id")
    return CremaProduct(
        id=int(product_id) if product_id is not None and str(product_id).strip() else None,
        code=str(item.get("code")).strip() if item.get("code") is not None else None,
        name=str(item.get("name") or "").strip(),
    )


def clean_export_value(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    elif text.startswith("="):
        text = text[1:]
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.strip()


def _mapping_row(mapping: ProductMapping) -> dict[str, object]:
    return {
        "naver_product_no": mapping.naver_product_no,
        "crema_product_id": mapping.crema_product_id or "",
        "crema_product_code": mapping.crema_product_code or "",
        "internal_product_code": mapping.internal_product_code or "",
        "product_name": mapping.product_name,
        "enabled": "true" if mapping.enabled else "false",
        "note": "auto_enabled" if mapping.enabled else "review_required",
    }


def _candidate_row(candidate: MappingCandidate) -> dict[str, object]:
    return {
        "naver_product_no": candidate.naver_product_no,
        "naver_product_name": candidate.naver_product_name,
        "crema_product_id": candidate.crema_product_id or "",
        "crema_product_code": candidate.crema_product_code or "",
        "crema_product_name": candidate.crema_product_name,
        "confidence": round(candidate.confidence, 4),
        "reason": candidate.reason,
    }


def _normalize_name(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _detect_product_column(headers: list[str], aliases: list[str]) -> str | None:
    normalized_headers = {_normalize_header(header): header for header in headers}
    for alias in aliases:
        normalized_alias = _normalize_header(alias)
        if normalized_alias in normalized_headers:
            return normalized_headers[normalized_alias]
    for key, original in normalized_headers.items():
        if any(_normalize_header(alias) in key for alias in aliases):
            return original
    return None


def _normalize_header(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())
