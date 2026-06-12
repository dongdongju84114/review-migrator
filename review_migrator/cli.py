from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from review_migrator.cafe24.admin import Cafe24AdminClient, Cafe24AdminSettings
from review_migrator.config import Settings, crema_token_refresh_callback, load_env_file
from review_migrator.crema.auth import TokenProvider
from review_migrator.crema.client import CremaClient
from review_migrator.crema.errors import error_response_body_text, error_status_code
from review_migrator.crema.permissions import (
    required_permission_failures,
    run_crema_permission_checks,
    write_permission_checks_csv,
)
from review_migrator.crema.products import ProductService
from review_migrator.crema.reviews import ReviewService
from review_migrator.harness.approval_gate import ApprovalError, ensure_apply_allowed
from review_migrator.harness.audit_log import append_event
from review_migrator.images.matcher import match_images, write_image_matches
from review_migrator.mapping.auto_mapping import (
    build_auto_mapping,
    build_mapping_from_marketplus_csv,
    extract_marketplus_cafe24_product_codes,
    fetch_crema_products,
    is_marketplus_product_csv,
    load_cafe24_product_no_by_product_code_csv,
    load_crema_products_from_csv,
    load_crema_products_from_json,
    write_auto_mapping_outputs,
)
from review_migrator.mapping.product_mapping import apply_product_mapping, load_product_mappings
from review_migrator.naver_export.normalizer import normalize_naver_export, write_normalized_outputs
from review_migrator.pipeline import RunAllOptions, run_all
from review_migrator.schemas import CremaReviewPayload, NormalizedReview
from review_migrator.storage.sqlite_registry import IdempotencyRegistry
from review_migrator.smartstore.review_images import (
    collect_smartstore_review_images_from_export,
    extract_smartstore_review_image_rows,
    write_smartstore_review_image_rows,
    write_smartstore_review_status_rows,
)
from review_migrator.transform.crema_csv import write_crema_csv
from review_migrator.transform.crema_payload import build_payloads, load_image_matches, write_payloads
from review_migrator.utils import read_jsonl, write_csv, write_jsonl
from review_migrator.verification.report import write_report
from review_migrator.verification.verifier import verify_payloads


def load_reviews(path: str | Path) -> list[NormalizedReview]:
    return [NormalizedReview.model_validate(row) for row in read_jsonl(path)]


def load_payloads(path: str | Path) -> list[CremaReviewPayload]:
    return [CremaReviewPayload.model_validate(row) for row in read_jsonl(path)]


def _mapped_from_files(input_path: str | Path, mapping_path: str | Path):
    reviews = load_reviews(input_path)
    mappings = load_product_mappings(mapping_path)
    return reviews, apply_product_mapping(reviews, mappings)


def _crema_review_service(settings: Settings, env_file: str | Path) -> ReviewService:
    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    return ReviewService(client)


def command_normalize(args: argparse.Namespace) -> int:
    result = normalize_naver_export(args.input)
    write_normalized_outputs(result.records, args.output, args.csv_output)
    if args.issues_output:
        write_jsonl(args.issues_output, result.issues)
    print(f"normalized={len(result.records)} errors={result.error_count} warnings={result.warning_count}")
    return 1 if result.error_count else 0


def command_validate_naver_export(args: argparse.Namespace) -> int:
    result = normalize_naver_export(args.input)
    mappings = load_product_mappings(args.mapping)
    mapping_result = apply_product_mapping(result.records, mappings)
    if args.failed_mapping_output:
        write_csv(
            args.failed_mapping_output,
            mapping_result.failed_rows,
            ["naver_review_id", "naver_product_no", "idempotency_code", "reason"],
        )
    error_count = result.error_count + len(mapping_result.failed_rows)
    warning_count = result.warning_count
    print(
        " ".join(
            [
                f"valid_reviews={len(mapping_result.mapped)}",
                f"failed_mapping={len(mapping_result.failed_rows)}",
                f"errors={error_count}",
                f"warnings={warning_count}",
            ]
        )
    )
    return 1 if error_count else 0


def command_build_crema_csv(args: argparse.Namespace) -> int:
    _, mapping_result = _mapped_from_files(args.input, args.mapping)
    image_matches = load_image_matches(args.image_matches)
    payloads, issues = build_payloads(mapping_result.mapped, image_matches=image_matches, display=args.display)
    write_crema_csv(args.output, payloads)
    if args.failed_mapping_output:
        write_csv(
            args.failed_mapping_output,
            mapping_result.failed_rows,
            ["naver_review_id", "naver_product_no", "idempotency_code", "reason"],
        )
    print(
        f"csv_rows={len(payloads)} failed_mapping={len(mapping_result.failed_rows)} "
        f"errors={sum(1 for issue in issues if issue.severity == 'error')} "
        f"warnings={sum(1 for issue in issues if issue.severity == 'warning')}"
    )
    return 1 if mapping_result.failed_rows or any(issue.severity == "error" for issue in issues) else 0


def command_build_crema_payload(args: argparse.Namespace) -> int:
    _, mapping_result = _mapped_from_files(args.input, args.mapping)
    image_matches = load_image_matches(args.image_matches)
    payloads, issues = build_payloads(mapping_result.mapped, image_matches=image_matches, display=args.display)
    write_payloads(args.output, payloads)
    if args.failed_mapping_output:
        write_csv(
            args.failed_mapping_output,
            mapping_result.failed_rows,
            ["naver_review_id", "naver_product_no", "idempotency_code", "reason"],
        )
    if args.issues_output:
        write_jsonl(args.issues_output, [*mapping_result.issues, *issues])
    print(
        f"payloads={len(payloads)} dry_run={args.dry_run} failed_mapping={len(mapping_result.failed_rows)} "
        f"warnings={sum(1 for issue in issues if issue.severity == 'warning')}"
    )
    return 1 if mapping_result.failed_rows or any(issue.severity == "error" for issue in issues) else 0


def command_match_images(args: argparse.Namespace) -> int:
    reviews = load_reviews(args.reviews)
    confirmed, review_required = match_images(reviews, args.image_dir, base_url=args.base_url)
    write_image_matches(args.output, confirmed)
    review_required_path = Path(args.output).with_name(f"{Path(args.output).stem}_review_required.csv")
    write_image_matches(review_required_path, review_required)
    print(f"auto_matches={len(confirmed)} review_required={len(review_required)}")
    return 0


def command_collect_smartstore_images(args: argparse.Namespace) -> int:
    status_output = args.status_output or str(Path(args.output).with_name(f"{Path(args.output).stem}_status.csv"))
    collection = collect_smartstore_review_images_from_export(
        args.input,
        store_id=args.store_id,
        sort=args.sort,
        max_scrolls=args.max_scrolls,
        wait_after_scroll_ms=args.wait_after_scroll_ms,
        headless=args.headless,
        browser_channel=args.browser_channel,
        browser_user_data_dir=Path(args.browser_user_data_dir) if args.browser_user_data_dir else None,
        product_limit=args.product_limit,
        log=print,
    )
    write_smartstore_review_image_rows(args.output, collection.rows)
    write_smartstore_review_status_rows(status_output, collection.status_rows)
    matched_review_count = len({str(row["naver_review_id"]) for row in collection.rows})
    print(
        " ".join(
            [
                f"products={collection.product_count}",
                f"target_reviews={collection.target_review_count}",
                f"matched_reviews={matched_review_count}",
                f"image_urls={len(collection.rows)}",
                f"output={args.output}",
                f"status_output={status_output}",
            ]
        )
    )
    return 0


def command_parse_smartstore_html(args: argparse.Namespace) -> int:
    rows = []
    for input_path in args.input:
        html = Path(input_path).read_text(encoding=args.encoding, errors="replace")
        rows.extend(
            extract_smartstore_review_image_rows(
                html,
                naver_product_no=args.product_no or "",
            )
        )
    write_smartstore_review_image_rows(args.output, rows)
    matched_review_count = len({str(row["naver_review_id"]) for row in rows})
    print(f"matched_reviews={matched_review_count} image_urls={len(rows)} output={args.output}")
    return 0


def command_upload_crema(args: argparse.Namespace) -> int:
    payloads = load_payloads(args.payload)
    dry_run = not args.approve
    if args.approve and not args.allow_partial_upload:
        blockers = _upload_artifact_blockers(args.payload)
        if blockers:
            print("upload blocked: " + "; ".join(blockers), file=sys.stderr)
            print("검토 필요 산출물이 남아 있어 실제 등록을 중단했습니다.", file=sys.stderr)
            print("정말 일부 payload만 올릴 때만 --allow-partial-upload을 명시하세요.", file=sys.stderr)
            return 2

    load_env_file(args.env_file)
    settings = Settings.from_env()
    ensure_apply_allowed(
        env=settings.env,
        dry_run=dry_run,
        approve=args.approve,
        validation_error_count=0,
    )

    audit_path = Path(args.audit_log)
    registry = IdempotencyRegistry(args.registry)
    if dry_run:
        for payload in payloads:
            append_event(audit_path, "dry_run_payload", {"code": payload.code, "product_code": payload.product_code})
        print(f"dry_run_payloads={len(payloads)} approve_required=true")
        registry.close()
        return 0

    service = _crema_review_service(settings, args.env_file)
    responses = []
    failed = []
    for payload in payloads:
        if registry.seen(payload.code) and args.duplicate_mode == "skip":
            responses.append({"status": "skipped_registry", "code": payload.code})
            continue
        try:
            if args.mode == "create":
                response = service.create(payload)
            else:
                response = service.create_or_update(payload, duplicate_mode=args.duplicate_mode)
            registry.record(payload.code, status="uploaded", run_id=args.run_id)
            append_event(audit_path, "upload_success", {"code": payload.code, "response": response})
            responses.append({"code": payload.code, "response": response})
        except Exception as error:
            registry.record(payload.code, status="failed", run_id=args.run_id)
            failed_row = _failed_upload_row(payload.code, error)
            failed.append(failed_row)
            append_event(audit_path, "upload_failed", failed_row)

    write_jsonl(args.responses_output, responses)
    if args.failed_output:
        write_csv(args.failed_output, failed, ["code", "error", "status_code", "response_body"])
    registry.close()
    print(f"uploaded_or_skipped={len(responses)} failed={len(failed)}")
    return 1 if failed else 0


def command_verify_crema(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    settings = Settings.from_env()
    payloads = load_payloads(args.payload)
    service = _crema_review_service(settings, args.env_file)
    report = verify_payloads(payloads=payloads, get_review_by_code=service.get_by_code, run_id=args.run_id)
    write_report(args.output, report)
    markdown_output = Path(args.output).with_suffix(".md")
    write_report(markdown_output, report)
    print(f"expected={report.expected_count} found={report.actual_found_count} failed={report.failed_count}")
    return 1 if report.failed_count else 0


def command_check_crema_permissions(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    settings = Settings.from_env()
    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(args.env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    checks = run_crema_permission_checks(
        review_service=ReviewService(client),
        product_service=ProductService(client),
        require_product_read=args.require_product_read,
    )
    if args.output:
        write_permission_checks_csv(args.output, checks)
    for check in checks:
        print(
            " ".join(
                [
                    f"{check.key}={check.severity}",
                    f"required={str(check.required).lower()}",
                    f"status_code={check.status_code or ''}",
                    f"message={check.message}",
                ]
            )
        )
    return 1 if required_permission_failures(checks) else 0


def _failed_upload_row(code: str, error: Exception) -> dict[str, object]:
    return {
        "code": code,
        "error": str(error),
        "status_code": error_status_code(error) or "",
        "response_body": error_response_body_text(error),
    }


def _upload_artifact_blockers(payload_path: str | Path) -> list[str]:
    run_dir = Path(payload_path).parent
    blockers: list[str] = []
    for filename, label in [
        ("failed_mapping.csv", "상품 매핑 실패"),
        ("product_mapping_review_required.csv", "상품 매핑 검토 필요"),
        ("image_matches_review_required.csv", "이미지 확인 필요"),
    ]:
        count = _csv_data_row_count(run_dir / filename)
        if count:
            blockers.append(f"{label} {count}건")

    payload_error_count = _jsonl_error_count(run_dir / "payload_issues.jsonl")
    if payload_error_count:
        blockers.append(f"payload 오류 {payload_error_count}건")
    return blockers


def _csv_data_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return sum(1 for _ in csv.DictReader(file))


def _jsonl_error_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for row in read_jsonl(path) if row.get("severity") == "error")


def command_run_all(args: argparse.Namespace) -> int:
    summary = run_all(
        RunAllOptions(
            naver_export_path=Path(args.input),
            product_mapping_path=Path(args.mapping) if args.mapping else None,
            image_dir=Path(args.image_dir) if args.image_dir else None,
            additional_image_csv_path=Path(args.additional_image_csv) if args.additional_image_csv else None,
            image_base_url=args.image_base_url,
            image_public_dir=Path(args.image_public_dir) if args.image_public_dir else None,
            download_images_from_excel=not args.no_download_images,
            output_base_dir=Path(args.output_dir),
            env_file=Path(args.env_file),
            approve_upload=args.approve_upload,
            duplicate_mode=args.duplicate_mode,
            display=args.display,
            auto_build_mapping=args.auto_build_mapping,
            crema_products_json=Path(args.crema_products_json) if args.crema_products_json else None,
            crema_products_csv=Path(args.crema_products_csv) if args.crema_products_csv else None,
            cafe24_products_csv=Path(args.cafe24_products_csv) if args.cafe24_products_csv else None,
        ),
        log=print,
    )
    print(f"run_id={summary.run_id}")
    print(f"output_dir={summary.output_dir}")
    print(f"payloads={summary.payload_count}")
    print(f"blocking={len(summary.blocking_messages)}")
    return 1 if summary.blocking_messages or summary.upload_failed_count else 0


def command_build_product_mapping(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    normalize_result = normalize_naver_export(args.input)
    if normalize_result.error_count:
        write_jsonl(args.issues_output, normalize_result.issues)
        print(f"normalize_errors={normalize_result.error_count}")
        return 1

    fetch_error = None
    if args.crema_products_csv and is_marketplus_product_csv(args.crema_products_csv):
        if args.crema_products_json:
            crema_products = load_crema_products_from_json(args.crema_products_json)
        else:
            settings = Settings.from_env()
            provider = TokenProvider(
                base_url=settings.crema_api_base_url,
                app_id=settings.crema_app_id,
                secret=settings.crema_secret,
                access_token=settings.crema_access_token,
                on_token_refresh=crema_token_refresh_callback(args.env_file),
            )
            client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
            try:
                crema_products = fetch_crema_products(
                    ProductService(client),
                    max_pages=args.max_pages,
                    limit=args.limit,
                )
            except Exception as error:
                fetch_error = error
                crema_products = []
        result = build_mapping_from_marketplus_csv(
            normalize_result.records,
            args.crema_products_csv,
            crema_products=crema_products,
            cafe24_product_no_by_code=_load_cafe24_product_no_mapping_for_marketplus(
                args.crema_products_csv,
                cafe24_products_csv=args.cafe24_products_csv,
            ),
            auto_confidence_threshold=args.auto_confidence_threshold,
            review_confidence_threshold=args.review_confidence_threshold,
        )
    elif args.crema_products_csv:
        crema_products = load_crema_products_from_csv(args.crema_products_csv)
        result = None
    elif args.crema_products_json:
        crema_products = load_crema_products_from_json(args.crema_products_json)
        result = None
    else:
        result = None
        settings = Settings.from_env()
        provider = TokenProvider(
            base_url=settings.crema_api_base_url,
            app_id=settings.crema_app_id,
            secret=settings.crema_secret,
            access_token=settings.crema_access_token,
            on_token_refresh=crema_token_refresh_callback(args.env_file),
        )
        client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)

        try:
            crema_products = fetch_crema_products(
                ProductService(client),
                max_pages=args.max_pages,
                limit=args.limit,
            )
        except Exception as error:
            fetch_error = error
            crema_products = []

    if result is None:
        result = build_auto_mapping(
            normalize_result.records,
            crema_products,
            auto_confidence_threshold=args.auto_confidence_threshold,
            review_confidence_threshold=args.review_confidence_threshold,
        )
    write_auto_mapping_outputs(
        mapping_path=args.output,
        candidates_path=args.candidates_output,
        review_required_path=args.review_required_output,
        result=result,
    )
    enabled_count = sum(1 for mapping in result.mappings if mapping.enabled)
    if fetch_error:
        print(f"crema_product_fetch_failed={fetch_error}")
    print(
        f"naver_products={len(result.mappings)} crema_products={len(crema_products)} "
        f"auto_enabled={enabled_count} review_required={len(result.review_required_rows)}"
    )
    return 1 if result.review_required_rows else 0


def _load_cafe24_product_no_mapping_for_marketplus(
    marketplus_csv: str | Path,
    *,
    cafe24_products_csv: str | Path | None = None,
) -> dict[str, str]:
    product_codes = extract_marketplus_cafe24_product_codes(marketplus_csv)
    if not product_codes:
        return {}
    if cafe24_products_csv:
        try:
            mapping = load_cafe24_product_no_by_product_code_csv(cafe24_products_csv)
        except Exception as error:
            print(f"cafe24_product_csv_failed={error}")
            return {}
        filtered = {code: product_no for code, product_no in mapping.items() if code in set(product_codes)}
        print(f"cafe24_product_csv_lookup={len(filtered)}")
        return filtered

    settings = Cafe24AdminSettings.from_env()
    if not settings.is_configured:
        print("cafe24_product_no_lookup=skipped missing=" + ",".join(settings.missing_keys))
        return {}
    try:
        client = Cafe24AdminClient(
            mall_id=str(settings.mall_id),
            access_token=str(settings.access_token),
            api_version=settings.api_version,
        )
        mapping = client.product_no_by_product_code(product_codes, shop_no=settings.shop_no)
    except Exception as error:
        print(f"cafe24_product_no_lookup_failed={error}")
        return {}
    print(f"cafe24_product_no_lookup={len(mapping)}")
    return mapping


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-migrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
    normalize.add_argument("--csv-output")
    normalize.add_argument("--issues-output")
    normalize.set_defaults(func=command_normalize)

    validate = subparsers.add_parser("validate-naver-export")
    validate.add_argument("--input", required=True)
    validate.add_argument("--mapping", required=True)
    validate.add_argument("--failed-mapping-output", default="out/failed_mapping.csv")
    validate.set_defaults(func=command_validate_naver_export)

    crema_csv = subparsers.add_parser("build-crema-csv")
    crema_csv.add_argument("--input", required=True)
    crema_csv.add_argument("--mapping", required=True)
    crema_csv.add_argument("--image-matches")
    crema_csv.add_argument("--output", required=True)
    crema_csv.add_argument("--failed-mapping-output", default="out/failed_mapping.csv")
    crema_csv.add_argument("--display", action=argparse.BooleanOptionalAction, default=True)
    crema_csv.set_defaults(func=command_build_crema_csv)

    payload = subparsers.add_parser("build-crema-payload")
    payload.add_argument("--input", required=True)
    payload.add_argument("--mapping", required=True)
    payload.add_argument("--image-matches")
    payload.add_argument("--dry-run", action="store_true", default=True)
    payload.add_argument("--output", required=True)
    payload.add_argument("--failed-mapping-output", default="out/failed_mapping.csv")
    payload.add_argument("--issues-output")
    payload.add_argument("--display", action=argparse.BooleanOptionalAction, default=True)
    payload.set_defaults(func=command_build_crema_payload)

    images = subparsers.add_parser("match-images")
    images.add_argument("--reviews", required=True)
    images.add_argument("--image-dir", required=True)
    images.add_argument("--base-url")
    images.add_argument("--output", required=True)
    images.set_defaults(func=command_match_images)

    collect_images = subparsers.add_parser("collect-smartstore-images")
    collect_images.add_argument("--input", required=True, help="네이버 리뷰 엑셀 경로")
    collect_images.add_argument("--output", required=True, help="생성할 additional_review_images.csv 경로")
    collect_images.add_argument("--status-output", help="리뷰별 수집 상태 CSV 경로")
    collect_images.add_argument("--store-id", default="opengallery", help="스마트스토어 ID")
    collect_images.add_argument(
        "--sort",
        choices=["latest", "ranking", "score_high", "score_low"],
        default="latest",
        help="리뷰 모달 정렬 기준",
    )
    collect_images.add_argument("--max-scrolls", type=int, default=80)
    collect_images.add_argument("--wait-after-scroll-ms", type=int, default=700)
    collect_images.add_argument("--headless", action=argparse.BooleanOptionalAction, default=False)
    collect_images.add_argument("--browser-channel", default="chrome", help="chrome, msedge 등. 빈 문자열이면 기본 Chromium")
    collect_images.add_argument("--browser-user-data-dir", help="스마트스토어 인증 쿠키를 유지할 전용 브라우저 프로필 폴더")
    collect_images.add_argument("--product-limit", type=int, help="PoC용 상품 수 제한")
    collect_images.set_defaults(func=command_collect_smartstore_images)

    parse_html = subparsers.add_parser("parse-smartstore-html")
    parse_html.add_argument("--input", nargs="+", required=True, help="스마트스토어 리뷰 모달 HTML/TXT 파일")
    parse_html.add_argument("--output", required=True, help="생성할 additional_review_images.csv 경로")
    parse_html.add_argument("--product-no", help="파일 전체에 적용할 네이버 상품번호")
    parse_html.add_argument("--encoding", default="utf-8")
    parse_html.set_defaults(func=command_parse_smartstore_html)

    upload = subparsers.add_parser("upload-crema")
    upload.add_argument("--payload", required=True)
    upload.add_argument("--mode", choices=["create", "create-or-update"], default="create-or-update")
    upload.add_argument("--duplicate-mode", choices=["skip", "update", "fail"], default="update")
    upload.add_argument("--approve", action="store_true")
    upload.add_argument("--env-file", default=".env")
    upload.add_argument("--registry", default="out/idempotency.sqlite3")
    upload.add_argument("--audit-log", default="out/audit_log.jsonl")
    upload.add_argument("--responses-output", default="out/api_responses.jsonl")
    upload.add_argument("--failed-output", default="out/failed_records.csv")
    upload.add_argument("--run-id", default="manual")
    upload.add_argument("--allow-partial-upload", action="store_true")
    upload.set_defaults(func=command_upload_crema)

    verify = subparsers.add_parser("verify-crema")
    verify.add_argument("--payload", required=True)
    verify.add_argument("--run-id", default="manual")
    verify.add_argument("--output", required=True)
    verify.add_argument("--env-file", default=".env")
    verify.set_defaults(func=command_verify_crema)

    permissions = subparsers.add_parser("check-crema-permissions")
    permissions.add_argument("--env-file", default=".env")
    permissions.add_argument("--output", default="out/crema_permission_checks.csv")
    permissions.add_argument("--require-product-read", action=argparse.BooleanOptionalAction, default=True)
    permissions.set_defaults(func=command_check_crema_permissions)

    run_all_parser = subparsers.add_parser("run-all")
    run_all_parser.add_argument("--input", required=True, help="네이버 리뷰 엑셀 경로")
    run_all_parser.add_argument("--mapping", help="상품 매핑 CSV 경로")
    run_all_parser.add_argument("--image-dir", help="사람이 다운로드한 이미지 폴더")
    run_all_parser.add_argument("--additional-image-csv", help="스마트스토어 이미지 수집기로 만든 추가 이미지 CSV")
    run_all_parser.add_argument("--image-base-url", help="이미지를 공개 접근할 수 있는 base URL. 없으면 CAFE24_IMAGE_BASE_URL 사용")
    run_all_parser.add_argument("--image-public-dir", help="FTP 대신 로컬/마운트 공개 폴더를 쓸 때만 지정")
    run_all_parser.add_argument("--no-download-images", action="store_true", help="네이버 엑셀 포토/영상 URL 다운로드를 건너뜀")
    run_all_parser.add_argument("--output-dir", default="operator_runs")
    run_all_parser.add_argument("--env-file", default=".env")
    run_all_parser.add_argument("--approve-upload", action="store_true")
    run_all_parser.add_argument("--auto-build-mapping", action="store_true", help="크리마 상품 API로 매핑 CSV를 자동 생성")
    run_all_parser.add_argument("--crema-products-json", help="테스트/오프라인용 크리마 상품 JSON")
    run_all_parser.add_argument("--crema-products-csv", help="크리마/카페24 상품 목록 CSV")
    run_all_parser.add_argument("--cafe24-products-csv", help="카페24 상품코드(P000...)와 상품번호(product_no)가 있는 CSV")
    run_all_parser.add_argument("--duplicate-mode", choices=["skip", "update", "fail"], default="update")
    run_all_parser.add_argument("--display", action=argparse.BooleanOptionalAction, default=True)
    run_all_parser.set_defaults(func=command_run_all)

    mapping = subparsers.add_parser("build-product-mapping")
    mapping.add_argument("--input", required=True, help="네이버 리뷰 엑셀 경로")
    mapping.add_argument("--output", default="config/product_mapping.generated.csv")
    mapping.add_argument("--candidates-output", default="out/product_mapping_candidates.csv")
    mapping.add_argument("--review-required-output", default="out/product_mapping_review_required.csv")
    mapping.add_argument("--issues-output", default="out/product_mapping_issues.jsonl")
    mapping.add_argument("--env-file", default=".env")
    mapping.add_argument("--crema-products-json", help="테스트/오프라인용 크리마 상품 JSON")
    mapping.add_argument("--crema-products-csv", help="크리마/카페24 상품 목록 CSV")
    mapping.add_argument("--cafe24-products-csv", help="카페24 상품코드(P000...)와 상품번호(product_no)가 있는 CSV")
    mapping.add_argument("--max-pages", type=int, default=50)
    mapping.add_argument("--limit", type=int, default=100)
    mapping.add_argument("--auto-confidence-threshold", type=float, default=0.94)
    mapping.add_argument("--review-confidence-threshold", type=float, default=0.72)
    mapping.set_defaults(func=command_build_product_mapping)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ApprovalError as error:
        print(f"approval error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
