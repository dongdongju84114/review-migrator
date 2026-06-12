from __future__ import annotations

import os
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Callable

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
from review_migrator.harness.approval_gate import ensure_apply_allowed
from review_migrator.harness.audit_log import append_event
from review_migrator.images.additional_csv import (
    merge_additional_image_urls,
    write_additional_image_import,
)
from review_migrator.images.downloader import download_review_images, write_download_manifest
from review_migrator.images.ftp_storage import (
    FtpStorageConfig,
    has_any_cafe24_ftp_setting,
    missing_cafe24_ftp_settings,
    stage_or_upload_matches_to_ftp,
)
from review_migrator.images.matcher import match_images, write_image_matches
from review_migrator.images.url_checker import check_public_image_urls, write_public_image_url_checks
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
from review_migrator.schemas import ValidationIssue
from review_migrator.storage.sqlite_registry import IdempotencyRegistry
from review_migrator.transform.crema_csv import write_crema_csv
from review_migrator.transform.crema_payload import build_payloads, write_payloads
from review_migrator.utils import now_kst, write_csv, write_jsonl
from review_migrator.verification.report import write_report
from review_migrator.verification.verifier import verify_payloads


LogFunc = Callable[[str], None]


@dataclass(frozen=True)
class RunAllOptions:
    naver_export_path: Path
    product_mapping_path: Path | None = None
    image_dir: Path | None = None
    additional_image_csv_path: Path | None = None
    image_base_url: str | None = None
    image_public_dir: Path | None = None
    download_images_from_excel: bool = True
    output_base_dir: Path = Path("operator_runs")
    env_file: Path = Path(".env")
    approve_upload: bool = False
    duplicate_mode: str = "update"
    display: bool = True
    run_id: str | None = None
    auto_build_mapping: bool = False
    crema_products_json: Path | None = None
    crema_products_csv: Path | None = None
    cafe24_products_csv: Path | None = None


@dataclass
class RunAllSummary:
    run_id: str
    output_dir: Path
    apply_requested: bool = False
    normalized_count: int = 0
    low_score_or_warning_count: int = 0
    normalize_error_count: int = 0
    mapped_count: int = 0
    failed_mapping_count: int = 0
    auto_image_match_count: int = 0
    additional_image_merged_count: int = 0
    additional_image_skipped_count: int = 0
    downloaded_image_count: int = 0
    ftp_image_planned_count: int = 0
    ftp_image_uploaded_count: int = 0
    image_public_url_failed_count: int = 0
    review_required_image_count: int = 0
    payload_count: int = 0
    payload_error_count: int = 0
    payload_warning_count: int = 0
    dry_run_payload_count: int = 0
    upload_blocked_count: int = 0
    uploaded_or_skipped_count: int = 0
    upload_failed_count: int = 0
    verification_failed_count: int | None = None
    files: dict[str, Path] = field(default_factory=dict)
    blocking_messages: list[str] = field(default_factory=list)

    @property
    def ok_for_upload(self) -> bool:
        return not self.blocking_messages

    @property
    def status_label(self) -> str:
        if self.upload_failed_count:
            return "등록 실패"
        if self.verification_failed_count:
            return "등록 후 검증 실패"
        if self.blocking_messages:
            return "검토 필요"
        return "업로드 가능"


def run_all(options: RunAllOptions, log: LogFunc | None = None) -> RunAllSummary:
    logger = log or (lambda message: None)
    run_id = options.run_id or now_kst().strftime("run_%Y%m%d_%H%M%S")
    output_dir = options.output_base_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = RunAllSummary(run_id=run_id, output_dir=output_dir)
    summary.apply_requested = options.approve_upload

    paths = {
        "normalized_jsonl": output_dir / "reviews_normalized.jsonl",
        "normalized_csv": output_dir / "reviews_normalized.csv",
        "normalize_issues": output_dir / "normalize_issues.jsonl",
        "smartstore_image_targets": output_dir / "smartstore_image_targets.csv",
        "product_mapping_generated": output_dir / "product_mapping.generated.csv",
        "product_mapping_candidates": output_dir / "product_mapping_candidates.csv",
        "product_mapping_review_required": output_dir / "product_mapping_review_required.csv",
        "failed_mapping": output_dir / "failed_mapping.csv",
        "image_matches": output_dir / "image_matches.csv",
        "image_review_required": output_dir / "image_matches_review_required.csv",
        "additional_image_import": output_dir / "additional_image_import.csv",
        "downloaded_images_dir": output_dir / "downloaded_images",
        "downloaded_image_manifest": output_dir / "downloaded_image_manifest.csv",
        "image_public_url_checks": output_dir / "image_public_url_checks.csv",
        "crema_csv": output_dir / "crema_other_reviews_upload.csv",
        "payloads": output_dir / "crema_payloads.jsonl",
        "payload_issues": output_dir / "payload_issues.jsonl",
        "audit_log": output_dir / "audit_log.jsonl",
        "api_responses": output_dir / "api_responses.jsonl",
        "failed_records": output_dir / "failed_records.csv",
        "registry": output_dir / "idempotency.sqlite3",
        "crema_permission_checks": output_dir / "crema_permission_checks.csv",
        "summary_md": output_dir / "run_summary.md",
        "summary_html": output_dir / "run_summary.html",
        "verification_html": output_dir / "verification_report.html",
    }
    summary.files = paths

    logger("1/6 네이버 리뷰 엑셀을 읽고 표준화합니다.")
    normalize_result = normalize_naver_export(options.naver_export_path)
    if options.additional_image_csv_path:
        logger("  - 추가 이미지 CSV를 병합합니다.")
        additional_image_result = merge_additional_image_urls(
            normalize_result.records,
            options.additional_image_csv_path,
        )
        normalize_result.records = additional_image_result.reviews
        write_additional_image_import(paths["additional_image_import"], additional_image_result.rows)
        summary.additional_image_merged_count = additional_image_result.merged_count
        summary.additional_image_skipped_count = additional_image_result.skipped_count
    else:
        write_additional_image_import(paths["additional_image_import"], [])
    write_normalized_outputs(normalize_result.records, paths["normalized_jsonl"], paths["normalized_csv"])
    write_smartstore_image_targets(paths["smartstore_image_targets"], normalize_result.records)
    write_jsonl(paths["normalize_issues"], normalize_result.issues)
    summary.normalized_count = len(normalize_result.records)
    summary.normalize_error_count = normalize_result.error_count
    summary.low_score_or_warning_count = normalize_result.warning_count
    if normalize_result.error_count:
        summary.blocking_messages.append(f"엑셀 검증 오류 {normalize_result.error_count}건")

    logger("2/6 상품 매핑을 준비하고 실패 건을 분리합니다.")
    mapping_path = options.product_mapping_path
    if options.auto_build_mapping:
        logger("  - 크리마 상품 목록을 읽어서 상품 매핑 CSV를 자동 생성합니다.")
        if options.crema_products_csv and is_marketplus_product_csv(options.crema_products_csv):
            crema_products = []
            try:
                logger("  - 크리마 상품 API 기준 id/code로 마켓플러스 매핑을 보정합니다.")
                crema_products = _load_crema_products_for_marketplus_resolution(options)
            except Exception as error:
                summary.blocking_messages.append(f"크리마 상품 목록 조회 실패: {error}")
            cafe24_product_no_by_code = _load_cafe24_product_no_mapping_for_marketplus(
                options.crema_products_csv,
                options.env_file,
                logger,
                cafe24_products_csv=options.cafe24_products_csv,
            )
            auto_mapping = build_mapping_from_marketplus_csv(
                normalize_result.records,
                options.crema_products_csv,
                crema_products=crema_products,
                cafe24_product_no_by_code=cafe24_product_no_by_code,
            )
        else:
            try:
                crema_products = _load_crema_products_for_mapping(options)
            except Exception as error:
                crema_products = []
                summary.blocking_messages.append(f"크리마 상품 목록 조회 실패: {error}")
            auto_mapping = build_auto_mapping(normalize_result.records, crema_products)
        write_auto_mapping_outputs(
            mapping_path=paths["product_mapping_generated"],
            candidates_path=paths["product_mapping_candidates"],
            review_required_path=paths["product_mapping_review_required"],
            result=auto_mapping,
        )
        mapping_path = paths["product_mapping_generated"]
        if auto_mapping.review_required_rows:
            summary.blocking_messages.append(f"자동 상품 매핑 검토 필요 {len(auto_mapping.review_required_rows)}건")

    if mapping_path is None:
        raise ValueError("상품 매핑 CSV가 필요합니다. mapping path를 지정하거나 auto_build_mapping을 켜주세요.")
    mappings = load_product_mappings(mapping_path)
    mapping_result = apply_product_mapping(normalize_result.records, mappings)
    write_csv(
        paths["failed_mapping"],
        mapping_result.failed_rows,
        ["naver_review_id", "naver_product_no", "idempotency_code", "reason"],
    )
    summary.mapped_count = len(mapping_result.mapped)
    summary.failed_mapping_count = len(mapping_result.failed_rows)
    if mapping_result.failed_rows:
        summary.blocking_messages.append(f"상품 매핑 실패 {len(mapping_result.failed_rows)}건")

    if options.approve_upload:
        logger("2-1/6 크리마 API 권한을 확인합니다.")
        checks = _check_crema_permissions(
            options,
            require_product_read=_requires_product_read_for_upload(mapping_result.mapped),
        )
        write_permission_checks_csv(paths["crema_permission_checks"], checks)
        permission_failures = required_permission_failures(checks)
        if permission_failures:
            summary.blocking_messages.append(
                "크리마 권한 확인 실패: " + ", ".join(f"{check.label}({check.message})" for check in permission_failures)
            )

    logger("3/6 이미지 파일을 준비합니다.")
    image_matches = {}
    downloaded_matches = []
    public_url_checks = []
    image_source_count = sum(len(review.source_image_urls) for review in normalize_result.records)
    load_env_file(options.env_file)
    image_base_url = options.image_base_url
    if not image_base_url:
        image_base_url = os.getenv("CAFE24_IMAGE_BASE_URL")
    if options.download_images_from_excel and image_source_count:
        logger("  - 네이버 엑셀의 포토/영상 URL을 로컬에 다운로드합니다.")
        downloaded_matches, manifest_rows = download_review_images(
            normalize_result.records,
            download_dir=paths["downloaded_images_dir"],
            public_dir=options.image_public_dir,
            public_base_url=image_base_url,
        )
        summary.downloaded_image_count = len(manifest_rows)
        failed_download_count = sum(1 for row in manifest_rows if row.get("status") == "failed")
        if failed_download_count:
            summary.blocking_messages.append(f"이미지 다운로드 실패 {failed_download_count}건")

        ftp_missing_settings = missing_cafe24_ftp_settings(public_base_url=image_base_url)
        if not ftp_missing_settings:
            try:
                ftp_config = FtpStorageConfig.from_env(public_base_url=image_base_url)
                upload_to_ftp = options.approve_upload and not summary.blocking_messages
                if upload_to_ftp:
                    logger("  - Cafe24 FTP로 리뷰 이미지를 업로드합니다.")
                elif options.approve_upload:
                    logger("  - 검토 필요 항목이 있어 Cafe24 FTP 업로드를 보류하고 예정 URL만 계산합니다.")
                else:
                    logger("  - Cafe24 FTP 업로드 예정 URL을 계산합니다. 실제 업로드는 등록 승인 때 실행됩니다.")
                downloaded_matches, manifest_rows = stage_or_upload_matches_to_ftp(
                    downloaded_matches,
                    manifest_rows,
                    config=ftp_config,
                    upload=upload_to_ftp,
                )
                if upload_to_ftp:
                    summary.ftp_image_uploaded_count = sum(1 for row in manifest_rows if row.get("status") == "uploaded")
                    public_urls = [
                        str(row.get("public_url"))
                        for row in manifest_rows
                        if row.get("status") == "uploaded" and row.get("public_url")
                    ]
                    if public_urls:
                        logger("  - 업로드된 이미지 공개 URL을 확인합니다.")
                        public_url_checks = check_public_image_urls(public_urls)
                        failed_public_urls = {check.url: check for check in public_url_checks if not check.ok}
                        summary.image_public_url_failed_count = len(failed_public_urls)
                        if failed_public_urls:
                            summary.blocking_messages.append(
                                f"이미지 공개 URL 접근 실패 {len(failed_public_urls)}건: CAFE24_IMAGE_BASE_URL 확인 필요"
                            )
                            for row in manifest_rows:
                                public_url = row.get("public_url")
                                if public_url in failed_public_urls:
                                    row["status"] = "public_url_failed"
                                    row["warning"] = failed_public_urls[str(public_url)].error
                else:
                    summary.ftp_image_planned_count = sum(1 for row in manifest_rows if row.get("status") == "planned")
            except Exception as error:
                summary.blocking_messages.append(f"Cafe24 FTP 이미지 업로드 실패: {error}")
        elif has_any_cafe24_ftp_setting():
            summary.blocking_messages.append("Cafe24 FTP 설정 누락: " + ", ".join(ftp_missing_settings))

        write_download_manifest(paths["downloaded_image_manifest"], manifest_rows)
        write_public_image_url_checks(paths["image_public_url_checks"], public_url_checks)
        image_matches.update({match.idempotency_code: match for match in downloaded_matches})
        missing_public_url_count = sum(1 for row in manifest_rows if row.get("status") not in {"failed"} and not row.get("public_url"))
        if missing_public_url_count:
            summary.blocking_messages.append("이미지 공개 URL이 없어 이미지는 로컬 다운로드까지만 완료됨")

    if options.image_dir and options.image_dir.exists():
        logger("  - 선택한 이미지 폴더도 함께 확인합니다.")
        confirmed, review_required = match_images(
            normalize_result.records,
            options.image_dir,
            base_url=image_base_url,
        )
        image_matches.update({match.idempotency_code: match for match in confirmed})
        write_image_matches(paths["image_review_required"], review_required)
        summary.review_required_image_count = len(review_required)
    else:
        write_image_matches(paths["image_review_required"], [])
    if not paths["image_public_url_checks"].exists():
        write_public_image_url_checks(paths["image_public_url_checks"], [])
    write_image_matches(paths["image_matches"], list(image_matches.values()))
    summary.auto_image_match_count = len(image_matches)

    logger("4/6 크리마 CSV와 API payload를 생성합니다.")
    payloads, payload_issues = build_payloads(
        mapping_result.mapped,
        image_matches=image_matches,
        display=options.display,
    )
    write_crema_csv(paths["crema_csv"], payloads)
    write_payloads(paths["payloads"], payloads)
    write_jsonl(paths["payload_issues"], [*mapping_result.issues, *payload_issues])
    summary.payload_count = len(payloads)
    summary.payload_error_count = _issue_count(payload_issues, "error")
    summary.payload_warning_count = _issue_count(payload_issues, "warning")
    if summary.payload_error_count:
        summary.blocking_messages.append(f"payload 오류 {summary.payload_error_count}건")

    logger("5/6 dry-run audit log를 남깁니다." if not options.approve_upload else "5/6 승인된 실제 크리마 등록을 실행합니다.")
    if options.approve_upload and summary.blocking_messages:
        logger("  - 검토 필요 항목이 있어 실제 등록을 보류합니다.")
        summary.upload_blocked_count = len(payloads)
    elif options.approve_upload:
        _upload_payloads(options, paths, payloads, summary, logger)
    else:
        for payload in payloads:
            append_event(paths["audit_log"], "dry_run_payload", {"code": payload.code, "product_code": payload.product_code})
        summary.dry_run_payload_count = len(payloads)
        summary.uploaded_or_skipped_count = len(payloads)

    logger("6/6 실행 요약 리포트를 생성합니다.")
    write_run_summary(summary)
    return summary


def _upload_payloads(
    options: RunAllOptions,
    paths: dict[str, Path],
    payloads: list,
    summary: RunAllSummary,
    logger: LogFunc,
) -> None:
    load_env_file(options.env_file)
    settings = Settings.from_env()
    ensure_apply_allowed(
        env=settings.env,
        dry_run=False,
        approve=options.approve_upload,
        validation_error_count=len(summary.blocking_messages),
    )
    if summary.blocking_messages:
        raise RuntimeError("실제 등록 전 해결 필요: " + ", ".join(summary.blocking_messages))

    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(options.env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    service = ReviewService(client)
    registry = IdempotencyRegistry(paths["registry"])
    responses = []
    failed = []

    for payload in payloads:
        try:
            if registry.seen(payload.code) and options.duplicate_mode == "skip":
                response = {"status": "skipped_registry", "code": payload.code}
            else:
                response = service.create_or_update(payload, duplicate_mode=options.duplicate_mode)
                registry.record(payload.code, status="uploaded", run_id=summary.run_id)
            responses.append({"code": payload.code, "response": response})
            append_event(paths["audit_log"], "upload_success", {"code": payload.code, "response": response})
            logger(f"등록 완료: {payload.code}")
        except Exception as error:
            registry.record(payload.code, status="failed", run_id=summary.run_id)
            failed_row = _failed_upload_row(payload.code, error)
            failed.append(failed_row)
            append_event(paths["audit_log"], "upload_failed", failed_row)
            detail = f" - {failed_row['response_body']}" if failed_row["response_body"] else ""
            logger(f"등록 실패: {payload.code} - {error}{detail}")

    write_jsonl(paths["api_responses"], responses)
    write_csv(paths["failed_records"], failed, ["code", "error", "status_code", "response_body"])
    registry.close()
    summary.uploaded_or_skipped_count = len(responses)
    summary.upload_failed_count = len(failed)

    if not failed:
        report = verify_payloads(
            payloads=payloads,
            get_review_by_code=service.get_by_code,
            run_id=summary.run_id,
            attempts=6,
            sleep_seconds=5,
        )
        write_report(paths["verification_html"], report)
        write_report(paths["verification_html"].with_suffix(".md"), report)
        summary.verification_failed_count = report.failed_count


def _load_crema_products_for_mapping(options: RunAllOptions) -> list:
    if options.crema_products_json:
        return load_crema_products_from_json(options.crema_products_json)
    if options.crema_products_csv:
        return load_crema_products_from_csv(options.crema_products_csv)
    load_env_file(options.env_file)
    settings = Settings.from_env()
    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(options.env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    from review_migrator.crema.products import ProductService

    return fetch_crema_products(ProductService(client))


def _load_crema_products_for_marketplus_resolution(options: RunAllOptions) -> list:
    if options.crema_products_json:
        return load_crema_products_from_json(options.crema_products_json)
    load_env_file(options.env_file)
    settings = Settings.from_env()
    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(options.env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    return fetch_crema_products(ProductService(client))


def _check_crema_permissions(
    options: RunAllOptions,
    *,
    require_product_read: bool,
) -> list:
    load_env_file(options.env_file)
    settings = Settings.from_env()
    provider = TokenProvider(
        base_url=settings.crema_api_base_url,
        app_id=settings.crema_app_id,
        secret=settings.crema_secret,
        access_token=settings.crema_access_token,
        on_token_refresh=crema_token_refresh_callback(options.env_file),
    )
    client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
    return run_crema_permission_checks(
        review_service=ReviewService(client),
        product_service=ProductService(client),
        require_product_read=require_product_read,
    )


def _load_cafe24_product_no_mapping_for_marketplus(
    marketplus_csv: Path,
    env_file: Path,
    logger: LogFunc,
    cafe24_products_csv: Path | None = None,
) -> dict[str, str]:
    load_env_file(env_file)
    product_codes = extract_marketplus_cafe24_product_codes(marketplus_csv)
    if not product_codes:
        return {}
    if cafe24_products_csv:
        try:
            mapping = load_cafe24_product_no_by_product_code_csv(cafe24_products_csv)
        except Exception as error:
            logger(f"  - 카페24 상품 CSV 읽기 실패: {error}")
            return {}
        filtered = {code: product_no for code, product_no in mapping.items() if code in set(product_codes)}
        logger(f"  - 카페24 상품 CSV로 상품코드 {len(filtered)}건을 product_no로 보정했습니다.")
        missing_count = len(set(product_codes) - set(filtered))
        if missing_count:
            logger(f"  - 카페24 상품 CSV에서 product_no 미확인 {missing_count}건은 상품명 후보로 보정합니다.")
        return filtered

    settings = Cafe24AdminSettings.from_env()
    if not settings.is_configured:
        logger("  - Cafe24 Admin API 설정이 없어 상품코드(P000...) → product_no 보정을 건너뜁니다.")
        return {}
    try:
        client = Cafe24AdminClient(
            mall_id=str(settings.mall_id),
            access_token=str(settings.access_token),
            api_version=settings.api_version,
        )
        mapping = client.product_no_by_product_code(product_codes, shop_no=settings.shop_no)
    except Exception as error:
        logger(f"  - Cafe24 상품코드 → product_no 조회 실패: {error}")
        return {}
    logger(f"  - Cafe24 상품코드 {len(mapping)}건을 product_no로 보정했습니다.")
    missing_count = len(set(product_codes) - set(mapping))
    if missing_count:
        logger(f"  - Cafe24 product_no 미확인 {missing_count}건은 상품명 후보로 보정합니다.")
    return mapping


def _requires_product_read_for_upload(mapped_reviews: list) -> bool:
    return any(mapping.crema_product_id is None for _, mapping in mapped_reviews)


def write_run_summary(summary: RunAllSummary) -> None:
    md = render_run_summary_markdown(summary)
    summary.files["summary_md"].write_text(md, encoding="utf-8")
    summary.files["summary_html"].write_text(render_run_summary_html(summary), encoding="utf-8")


def render_run_summary_markdown(summary: RunAllSummary) -> str:
    processing_lines = _summary_processing_lines(summary)
    lines = [
        f"# 리뷰 이전 실행 요약: {summary.run_id}",
        "",
        f"- 상태: {summary.status_label}",
        f"- 표준화 리뷰: {summary.normalized_count}건",
        f"- 낮은 별점/경고: {summary.low_score_or_warning_count}건",
        f"- 상품 매핑 성공: {summary.mapped_count}건",
        f"- 상품 매핑 실패: {summary.failed_mapping_count}건",
        f"- 추가 이미지 병합: {summary.additional_image_merged_count}건",
        f"- 추가 이미지 제외: {summary.additional_image_skipped_count}건",
        f"- 이미지 자동 매칭: {summary.auto_image_match_count}건",
        f"- Cafe24 FTP 업로드 예정 이미지: {summary.ftp_image_planned_count}건",
        f"- Cafe24 FTP 업로드 완료 이미지: {summary.ftp_image_uploaded_count}건",
        f"- 이미지 공개 URL 실패: {summary.image_public_url_failed_count}건",
        f"- 이미지 확인 필요: {summary.review_required_image_count}건",
        f"- 크리마 payload: {summary.payload_count}건",
        *processing_lines,
    ]
    if summary.verification_failed_count is not None:
        lines.append(f"- 등록 후 검증 실패: {summary.verification_failed_count}건")
    if summary.blocking_messages:
        lines.extend(["", "## 실제 등록 전 해결 필요"])
        lines.extend(f"- {message}" for message in summary.blocking_messages)
    lines.extend(["", "## 주요 파일"])
    for label, path in summary.files.items():
        if label in {"registry"}:
            continue
        lines.append(f"- {label}: `{path}`")
    return "\n".join(lines) + "\n"


def render_run_summary_html(summary: RunAllSummary) -> str:
    blockers = "".join(f"<li>{escape(message)}</li>" for message in summary.blocking_messages)
    processing_rows = "".join(
        f"<dt>{escape(label)}</dt><dd>{count}건</dd>"
        for label, count in _summary_processing_items(summary)
    )
    files = "".join(
        f"<li>{escape(label)}: <code>{escape(str(path))}</code></li>"
        for label, path in summary.files.items()
        if label != "registry"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>리뷰 이전 실행 요약 {escape(summary.run_id)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #1f2933; }}
    dl {{ display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px; }}
    dt {{ font-weight: 700; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  </style>
</head>
<body>
  <h1>리뷰 이전 실행 요약</h1>
  <p>run_id: <code>{escape(summary.run_id)}</code></p>
  <dl>
    <dt>상태</dt><dd>{escape(summary.status_label)}</dd>
    <dt>표준화 리뷰</dt><dd>{summary.normalized_count}건</dd>
    <dt>상품 매핑 성공</dt><dd>{summary.mapped_count}건</dd>
    <dt>상품 매핑 실패</dt><dd>{summary.failed_mapping_count}건</dd>
    <dt>추가 이미지 병합</dt><dd>{summary.additional_image_merged_count}건</dd>
    <dt>추가 이미지 제외</dt><dd>{summary.additional_image_skipped_count}건</dd>
    <dt>이미지 자동 매칭</dt><dd>{summary.auto_image_match_count}건</dd>
    <dt>Cafe24 FTP 업로드 예정</dt><dd>{summary.ftp_image_planned_count}건</dd>
    <dt>Cafe24 FTP 업로드 완료</dt><dd>{summary.ftp_image_uploaded_count}건</dd>
    <dt>이미지 공개 URL 실패</dt><dd>{summary.image_public_url_failed_count}건</dd>
    <dt>이미지 확인 필요</dt><dd>{summary.review_required_image_count}건</dd>
    <dt>payload</dt><dd>{summary.payload_count}건</dd>
    {processing_rows}
  </dl>
  <h2>실제 등록 전 해결 필요</h2>
  <ul>{blockers or "<li>없음</li>"}</ul>
  <h2>주요 파일</h2>
  <ul>{files}</ul>
</body>
</html>
"""


def _summary_processing_lines(summary: RunAllSummary) -> list[str]:
    return [f"- {label}: {count}건" for label, count in _summary_processing_items(summary)]


def _summary_processing_items(summary: RunAllSummary) -> list[tuple[str, int]]:
    if summary.apply_requested:
        return [
            ("실제 등록 보류", summary.upload_blocked_count),
            ("실제 등록 성공/스킵", summary.uploaded_or_skipped_count),
            ("등록 실패", summary.upload_failed_count),
        ]
    return [
        ("dry-run payload 기록", summary.dry_run_payload_count),
    ]


def _issue_count(issues: list[ValidationIssue], severity: str) -> int:
    return sum(1 for issue in issues if issue.severity == severity)


def _failed_upload_row(code: str, error: Exception) -> dict[str, object]:
    return {
        "code": code,
        "error": str(error),
        "status_code": error_status_code(error) or "",
        "response_body": error_response_body_text(error),
    }


def write_smartstore_image_targets(path: Path, reviews: list) -> int:
    rows = [
        {
            "naver_product_no": review.naver_product_no,
            "naver_review_id": review.naver_review_id,
            "created_at": review.created_at_kst.isoformat(),
            "reviewer_name": review.reviewer_name,
            "score": review.score,
            "idempotency_code": review.idempotency_code,
        }
        for review in reviews
        if review.has_image or review.source_image_urls
    ]
    return write_csv(
        path,
        rows,
        [
            "naver_product_no",
            "naver_review_id",
            "created_at",
            "reviewer_name",
            "score",
            "idempotency_code",
        ],
    )
