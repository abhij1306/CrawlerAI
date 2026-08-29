from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from app.core.database import SessionLocal
from app.core.security import hash_password, verify_password
from app.models.crawl_run import CrawlRun
from app.models.user import User
from app.crawl.batch_runtime import process_run
from app.crawl.crud import create_crawl_run, get_run_records
from app.crawl.pipeline.extraction_loop import process_single_url
from app.crawl.pipeline.types import URLMetrics, URLProcessingConfig
from app.acquisition.platform_policy import configured_adapter_names
from app.core.config.public_record_policy import PUBLIC_RECORD_LEGACY_VARIANT_FIELDS
from app.core.config.variant_policy import (
    PUBLIC_FLAT_VARIANT_FIELDS,
    PUBLIC_VARIANT_AXIS_FIELDS,
)
from sqlalchemy import select

from harness import site_sets as _site_sets
from harness.challenge_classifier import (
    _challenge_summary_from_diagnostics,
    _looks_like_detail_identity_mismatch,
    _looks_like_placeholder_or_wrong_content,
    _looks_like_promo_or_wrong_page,
    _looks_like_utility_chrome_success,
    _looks_like_utility_record,
    classify_failure_mode as _classify_failure_mode,
)

build_explicit_sites = _site_sets.build_explicit_sites
load_site_set = _site_sets.load_site_set
parse_test_sites_markdown = _site_sets.parse_test_sites_markdown
require_explicit_surface = _site_sets.require_explicit_surface

logger = logging.getLogger(__name__)


def unavailable_configured_adapters() -> set[str]:
    return set(configured_adapter_names())


def classify_failure_mode(result: dict[str, object]) -> str:
    return _classify_failure_mode(
        result, missing_registrations=unavailable_configured_adapters()
    )


HARNESS_MODE_ACQUISITION_ONLY = "acquisition_only"
HARNESS_MODE_FULL_PIPELINE = "full_pipeline"
DEFAULT_SITE_SET_PATH = (
    Path(__file__).resolve().parent / "test_site_sets" / "commerce_browser_heavy.json"
)
DEFAULT_HARNESS_EMAIL = "admin@admin.com"
DEFAULT_HARNESS_PASSWORD = "AdminPassword123!"  # nosec B105 # skipcq: SCT-A000 - local harness bootstrap placeholder only.
_VARIANT_AXIS_FIELDS = tuple(
    dict.fromkeys(
        str(token).strip().lower()
        for token in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
        if str(token).strip()
    )
)


def _field_name_tuple(value: object, config_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"{config_name} must be an iterable of field names")
    fields = tuple(str(token).strip() for token in value if str(token).strip())
    if not fields:
        raise TypeError(f"{config_name} must contain at least one field name")
    return fields


_PUBLIC_RECORD_LEGACY_VARIANT_FIELDS = _field_name_tuple(
    PUBLIC_RECORD_LEGACY_VARIANT_FIELDS,
    "PUBLIC_RECORD_LEGACY_VARIANT_FIELDS",
)
if not _VARIANT_AXIS_FIELDS:
    logger.warning(
        "PUBLIC_VARIANT_AXIS_FIELDS is empty; using default axis fields for "
        "_quality_variant_artifacts_ok and _variant_row_has_axis"
    )
    _VARIANT_AXIS_FIELDS = ("color", "size")
_HIGH_DENOMINATION_PRICE_CURRENCIES = {"INR", "JPY", "KRW", "VND", "IDR", "HUF", "CLP"}
_MIN_SANE_PRICE = 0.01

_ALLOWED_GENDERS = {"Men", "Women", "Unisex", "Kids", "Boys", "Girls"}
_ALLOWED_GENDERS_LOWER = frozenset(g.lower() for g in _ALLOWED_GENDERS)
_BARCODE_LENGTHS = {8, 12, 13, 14}
_INTERNAL_IDENTITY_TOKENS = {
    "plp",
    "pdp",
    "specification",
    "specifications",
    "description",
    "details",
    "overview",
    "reviews",
}


def timeout_owner_for_mode(mode: str) -> str:
    return (
        "batch_runtime" if mode == HARNESS_MODE_FULL_PIPELINE else "acquisition_runtime"
    )


def status_for_result(result: dict[str, object]) -> str:
    if "ok" in result:
        return "PASS" if bool(result.get("ok")) else "FAIL"
    return "PASS" if classify_failure_mode(result) == "success" else "FAIL"


async def run_site_harness(*, url: str, surface: str, mode: str) -> dict[str, object]:
    async with SessionLocal() as session:
        run = await create_crawl_run(
            session,
            await _ensure_harness_user_id(session),
            {
                "run_type": "crawl",
                "url": url,
                "surface": surface,
                "settings": {"max_pages": 5, "max_scrolls": 5},
            },
        )
        if mode == HARNESS_MODE_FULL_PIPELINE:
            await process_run(session, run.id)
            await session.refresh(run)
            rows, total_records = await get_run_records(session, run.id, 1, 100)
            return _persisted_run_result(
                run=run,
                rows=rows,
                total_records=total_records,
                requested_url=url,
                run_source="live_run",
            )
        url_result = await process_single_url(
            session=session,
            run=run,
            url=url,
            config=URLProcessingConfig.from_acquisition_plan(
                run.settings_view.acquisition_plan(surface=surface),
                update_run_state=False,
                persist_run_events=False,
                prefetch_only=True,
            ),
        )
        metrics: URLMetrics = url_result.url_metrics or URLMetrics()
        challenge_summary = _challenge_summary_from_diagnostics(
            dict(metrics.get("browser_diagnostics") or {})
        )
        return {
            "run_id": run.id,
            "status": run.status,
            "requested_url": url,
            "verdict": str(url_result.verdict or ""),
            "method": str(metrics.get("method") or "").strip() or None,
            "platform_family": str(metrics.get("platform_family") or "").strip()
            or None,
            "status_code": metrics.get("status_code"),
            "blocked": bool(metrics.get("blocked")),
            "browser_diagnostics": dict(metrics.get("browser_diagnostics") or {}),
            "records": int(metrics.get("record_count", 0) or 0),
            "sample_title": "",
            "populated_fields": 0,
            "challenge_summary": challenge_summary,
            "run_source": "live_run",
            "error": str(metrics.get("error") or "").strip() or None,
        }


async def review_saved_run(
    *,
    run_id: int,
    requested_url: str | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        run = (
            await session.execute(
                select(CrawlRun).where(CrawlRun.id == int(run_id)).limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            raise RuntimeError(f"Saved harness run {run_id} was not found")
        rows, total_records = await get_run_records(session, run.id, 1, 100)
        return _persisted_run_result(
            run=run,
            rows=rows,
            total_records=total_records,
            requested_url=str(requested_url or run.url or "").strip(),
            run_source="artifact_review",
        )


def _populated_field_count(record: dict[str, object]) -> int:
    return sum(
        1
        for key, value in record.items()
        if value not in (None, "", [], {}) and not str(key).startswith("_")
    )


def _sample_records(rows: Sequence[object]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for row in (rows or [])[:3]:
        data = dict(getattr(row, "data", {}) or {})
        samples.append(
            {
                "title": str(data.get("title") or "")[:160],
                "url": str(data.get("url") or "")[:240],
                "populated_fields": _populated_field_count(data),
                "price_present": data.get("price") not in (None, "", [], {}),
            }
        )
    return samples


def _sample_record_audit(sample_records: list[dict[str, object]]) -> dict[str, object]:
    coverage_values = [
        _safe_int(row.get("populated_fields"))
        for row in sample_records
        if isinstance(row, dict)
    ]
    utility_hits = [
        index
        for index, row in enumerate(sample_records, start=1)
        if isinstance(row, dict)
        and _looks_like_utility_record(
            title=row.get("title"),
            url=row.get("url"),
        )
    ]
    return {
        "field_coverage": {
            "avg_populated_fields": round(
                sum(coverage_values) / max(1, len(coverage_values)), 2
            ),
            "max_populated_fields": max(coverage_values, default=0),
            "min_populated_fields": min(coverage_values, default=0),
        },
        "utility_noise_hits": utility_hits,
        "looks_like_utility_chrome": bool(utility_hits),
    }


def _persisted_run_result(
    *,
    run: CrawlRun,
    rows: Sequence[object],
    total_records: int,
    requested_url: str,
    run_source: str,
) -> dict[str, object]:
    first = rows[0] if rows else None
    first_data = getattr(first, "data", {}) if first is not None else {}
    first_trace = getattr(first, "source_trace", {}) if first is not None else {}
    data = _object_dict(first_data)
    acquisition = _object_dict(_object_dict(first_trace).get("acquisition"))
    summary = run.summary_dict()
    sample_records = _sample_records(rows)
    sample_audit = _sample_record_audit(sample_records)
    challenge_summary = _challenge_summary_from_diagnostics(
        _object_dict(acquisition.get("browser_diagnostics"))
    )
    return {
        "run_id": run.id,
        "status": run.status,
        "requested_url": requested_url,
        "verdict": str(summary.get("extraction_verdict") or ""),
        "method": _summary_value(summary, "methods"),
        "platform_family": _summary_value(summary, "platform_families"),
        "status_code": acquisition.get("status_code"),
        "blocked": bool(acquisition.get("blocked")),
        "browser_diagnostics": _object_dict(acquisition.get("browser_diagnostics")),
        "records": max(total_records, _safe_int(summary.get("record_count"))),
        "sample_title": str(data.get("title") or "")[:120],
        "sample_url": str(data.get("url") or "")[:240],
        "sample_record_data": data,
        "sample_source_trace": _object_dict(first_trace),
        "sample_records": sample_records,
        "sample_semantics": _sample_semantics(data),
        "listing_contract": _listing_contract(rows),
        "populated_fields": _populated_field_count(data),
        "sample_field_coverage": sample_audit["field_coverage"],
        "sample_utility_noise_hits": sample_audit["utility_noise_hits"],
        "sample_looks_like_utility_chrome": sample_audit["looks_like_utility_chrome"],
        "challenge_summary": challenge_summary,
        "run_source": run_source,
        "error": str(summary.get("error") or "").strip() or None,
    }


def _sample_semantics(record: dict[str, object]) -> dict[str, object]:
    variants = [
        row for row in _object_list(record.get("variants")) if isinstance(row, dict)
    ]
    variant_rows_with_axes = sum(1 for row in variants if _variant_row_has_axis(row))
    variant_rows_with_price = sum(
        1 for row in variants if row.get("price") not in (None, "", [], {})
    )
    return {
        "price_present": record.get("price") not in (None, "", [], {}),
        "currency_present": record.get("currency") not in (None, "", [], {}),
        "variant_count": max(_safe_int(record.get("variant_count")), len(variants)),
        "variants_with_axes_count": variant_rows_with_axes,
        "variants_all_have_axes": bool(variants)
        and variant_rows_with_axes == len(variants),
        "variants_with_price_count": variant_rows_with_price,
        "legacy_variant_keys_present": any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in _PUBLIC_RECORD_LEGACY_VARIANT_FIELDS
        ),
    }


def _listing_contract(rows: Sequence[object]) -> dict[str, object]:
    detail_url_count = 0
    price_present_count = 0
    numeric_price_count = 0
    sampled = 0
    for row in rows or []:
        data = dict(getattr(row, "data", {}) or {})
        sampled += 1
        row_url = str(data.get("url") or "").strip()
        if row_url and not _looks_like_utility_record(
            title=data.get("title"), url=row_url
        ):
            detail_url_count += 1
        if data.get("price") not in (None, "", [], {}):
            price_present_count += 1
            if _looks_numeric_price(data.get("price")):
                numeric_price_count += 1
    return {
        "sampled_records": sampled,
        "detail_url_count": detail_url_count,
        "detail_urls_present": detail_url_count > 0,
        "price_present_count": price_present_count,
        "price_numeric_count": numeric_price_count,
    }


def evaluate_quality(
    site: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    expectations = _quality_expectations(site, result=result)
    checks = {
        "identity_ok": _quality_identity_ok(result),
        "listing_noise_ok": _quality_listing_noise_ok(
            result, expectations=expectations
        ),
        "variant_presence_ok": _quality_variant_presence_ok(
            result, expectations=expectations
        ),
        "variant_labels_ok": _quality_variant_labels_ok(
            result, expectations=expectations
        ),
        "variant_price_ok": _quality_variant_price_ok(
            result, expectations=expectations
        ),
        "price_sane_ok": _quality_price_sane_ok(result, expectations=expectations),
        "category_clean_ok": _quality_category_clean_ok(
            result, expectations=expectations
        ),
        "long_text_clean_ok": _quality_long_text_clean_ok(
            result, expectations=expectations
        ),
        "variant_artifacts_ok": _quality_variant_artifacts_ok(
            result, expectations=expectations
        ),
        "variant_currency_parity_ok": _quality_variant_currency_parity_ok(
            result, expectations=expectations
        ),
        "identifier_shapes_ok": _quality_identifier_shapes_ok(
            result, expectations=expectations
        ),
        "title_token_ok": _quality_title_token_ok(result, expectations=expectations),
        "system_artifacts_ok": _quality_system_artifacts_ok(
            result, expectations=expectations
        ),
    }
    observed_failure_mode = _observed_quality_failure_mode(
        site,
        result,
        checks=checks,
        expectations=expectations,
    )
    quality_verdict = _quality_verdict(
        result,
        checks=checks,
        expectations=expectations,
        observed_failure_mode=observed_failure_mode,
    )
    return {
        "quality_verdict": quality_verdict,
        "observed_failure_mode": observed_failure_mode,
        "quality_checks": checks,
    }


def _quality_expectations(
    site: dict[str, object],
    *,
    result: dict[str, object],
) -> dict[str, bool]:
    surface = str((site.get("surface") or result.get("surface") or "")).strip().lower()
    configured = _object_dict(site.get("quality_expectations"))
    expectations = {
        "require_identity": surface.endswith("_detail"),
        "require_listing_noise_free": surface.endswith("_listing"),
        "require_price": False,
        "require_price_sane": False,
        "require_clean_category": surface.startswith("ecommerce_"),
        "require_clean_long_text": surface == "ecommerce_detail",
        "require_clean_variants": surface == "ecommerce_detail",
        "require_clean_system_fields": surface == "ecommerce_detail",
        "require_identifier_shapes": surface == "ecommerce_detail",
        "require_title_not_internal_token": surface == "ecommerce_detail",
        "require_variant_currency_parity": surface == "ecommerce_detail",
        "expect_variants": False,
        "require_semantic_variant_labels": False,
        "require_variant_price": False,
    }
    for key in list(expectations):
        if key in configured:
            expectations[key] = bool(configured.get(key))
    return expectations


def _quality_identity_ok(result: dict[str, object]) -> bool:
    diagnostics = _object_dict(result.get("browser_diagnostics"))
    if str(result.get("failure_mode") or "").strip().lower() == "blocked":
        return False
    if _looks_like_placeholder_or_wrong_content(result, diagnostics):
        return False
    if _looks_like_detail_identity_mismatch(result):
        return False
    surface = str(result.get("surface") or "").strip().lower()
    if surface.endswith("_listing"):
        sample_records = _object_list(result.get("sample_records"))
        return any(
            isinstance(row, dict)
            and str(row.get("title") or "").strip()
            and str(row.get("url") or "").strip()
            and not _looks_like_utility_record(
                title=row.get("title"), url=row.get("url")
            )
            for row in sample_records
        )
    return not (
        _looks_like_site_shell_success(result)
        or _looks_like_promo_or_wrong_page(result)
    )


def _quality_listing_noise_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_listing_noise_free"):
        return True
    if _looks_like_utility_chrome_success(result):
        return False
    sample_records = _object_list(result.get("sample_records"))
    if sample_records and not any(
        _looks_like_real_listing_row(row) for row in sample_records[:3]
    ):
        return False
    return True


def _quality_variant_presence_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("expect_variants"):
        return True
    semantics = _object_dict(result.get("sample_semantics"))
    return _safe_int(semantics.get("variant_count")) >= 2


def _quality_variant_labels_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_semantic_variant_labels"):
        return True
    semantics = _object_dict(result.get("sample_semantics"))
    return bool(semantics.get("variants_all_have_axes"))


def _quality_variant_price_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_variant_price"):
        return True
    semantics = _object_dict(result.get("sample_semantics"))
    if bool(semantics.get("price_present")):
        return True
    return _safe_int(semantics.get("variants_with_price_count")) > 0


def _quality_price_sane_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_price_sane"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    price = _price_number(record.get("price"))
    if price is None or price < _MIN_SANE_PRICE:
        return False
    currency = str(record.get("currency") or "").strip().upper()
    max_price = 100000.0 if currency in _HIGH_DENOMINATION_PRICE_CURRENCIES else 10000.0
    return price <= max_price


def _quality_category_clean_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_clean_category"):
        return True
    category = str(_object_dict(result.get("sample_record_data")).get("category") or "")
    if not category.strip():
        return True
    if _category_has_navigation_noise(category):
        return False
    parts = [
        part.strip().lower() for part in re.split(r">\s*|/+", category) if part.strip()
    ]
    if any(_category_part_is_noise(part) for part in parts):
        return False
    return not _category_matches_product_identity(result, parts=parts)


def _category_has_navigation_noise(category: str) -> bool:
    lowered = f" {category.lower()} "
    tokens = (
        " previous ",
        " next ",
        " view all ",
        " back ",
        " best sellers ",
        " shop by ",
        "···",
        " … ",
    )
    return any(token in lowered for token in tokens)


def _category_part_is_noise(part: str) -> bool:
    return (
        part in {"home", "...", "all categories", "best sellers"}
        or part.startswith(("...", "shop by "))
        or part.endswith("...")
    )


def _category_matches_product_identity(
    result: dict[str, object], *, parts: list[str]
) -> bool:
    title = " ".join(str(result.get("sample_title") or "").strip().lower().split())
    sku = " ".join(
        str(_object_dict(result.get("sample_record_data")).get("sku") or "")
        .strip()
        .lower()
        .split()
    )
    return bool(
        (title and any(part == title for part in parts))
        or (sku and any(part == sku or part.endswith(f"sku: {sku}") for part in parts))
    )


def _quality_long_text_clean_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_clean_long_text"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    description = _normalized_space(record.get("description"))
    specifications = _normalized_space(record.get("specifications"))
    if description and specifications and description == specifications:
        return False
    for field_name in (
        "description",
        "product_details",
        "specifications",
        "materials",
        "care",
    ):
        text = _normalized_space(record.get(field_name))
        lowered = text.lower()
        if not lowered:
            continue
        if (
            lowered.endswith((" show more", " more details"))
            or " learn more about our materials" in lowered
        ):
            return False
        if any(
            token in lowered
            for token in (
                "choose from same day delivery",
                "free standard delivery",
                "shipping and returns",
                "cookie policy",
                "privacy policy",
                "add to cart",
                "size guide",
                "view size guide",
                "ask a question",
                "we aim to show you accurate product information",
            )
        ):
            return False
        if re.search(r"\{['\"][a-z0-9_ -]+['\"]\s*:", text, flags=re.I):
            return False
        if field_name == "materials" and re.search(r"\breviews?\s*\(", lowered):
            return False
    return True


def _quality_variant_artifacts_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_clean_variants"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    if any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in _PUBLIC_RECORD_LEGACY_VARIANT_FIELDS
    ):
        return False
    values: list[object] = []
    allowed_variant_keys = PUBLIC_FLAT_VARIANT_FIELDS
    for row in _object_list(record.get("variants")):
        if isinstance(row, dict):
            if any(str(key).strip() not in allowed_variant_keys for key in row.keys()):
                return False
            values.extend(row.keys())
            values.extend(row.values())
    for value in values:
        if isinstance(value, bool):
            return False
        text = _normalized_space(value).lower()
        if not text:
            continue
        if text in {"off", "on", "discount", "sale", "false", "true"}:
            return False
        if re.fullmatch(r"\d+\s*%", text) or re.fullmatch(
            # text has already been lowercased above via _normalized_space(...).lower()
            r"#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})",
            text,
        ):
            return False
    return True


def _quality_variant_currency_parity_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_variant_currency_parity"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    parent_currency = str(record.get("currency") or "").strip().upper()
    variants = [
        row for row in _object_list(record.get("variants")) if isinstance(row, dict)
    ]
    if not variants or not parent_currency:
        return True
    for row in variants:
        row_currency = str(row.get("currency") or "").strip().upper()
        if row_currency and row_currency != parent_currency:
            return False
        if row.get("price") not in (None, "", [], {}) and not row_currency:
            return False
    return True


def _quality_identifier_shapes_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_identifier_shapes"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    barcode = str(record.get("barcode") or "").strip()
    if barcode and (not barcode.isdigit() or len(barcode) not in _BARCODE_LENGTHS):
        return False
    gender = str(record.get("gender") or "").strip()
    if gender and gender.lower() not in _ALLOWED_GENDERS_LOWER:
        return False
    for field_name in ("product_id", "product_type"):
        text = str(record.get(field_name) or "").strip().lower()
        if text and any(token in text for token in _INTERNAL_IDENTITY_TOKENS):
            return False
    return True


def _quality_title_token_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_title_not_internal_token"):
        return True
    title = str(result.get("sample_title") or "").strip().lower()
    if not title:
        return True
    return title not in _INTERNAL_IDENTITY_TOKENS and "brightcove video" not in title


def _quality_system_artifacts_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_clean_system_fields"):
        return True
    record = _object_dict(result.get("sample_record_data"))
    sku = str(record.get("sku") or "").strip().lower()
    product_type = str(record.get("product_type") or "").strip().lower()
    return not (sku.startswith("copy-") or product_type in {"default", "tag", "inline"})


def _price_requirement_failed(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_price"):
        return False
    surface = str(result.get("surface") or "").strip().lower()
    if surface.endswith("_listing"):
        return not any(
            isinstance(row, dict) and bool(row.get("price_present"))
            for row in _object_list(result.get("sample_records"))
        )
    semantics = _object_dict(result.get("sample_semantics"))
    return not bool(semantics.get("price_present"))


def _observed_quality_failure_mode(
    site: dict[str, object],
    result: dict[str, object],
    *,
    checks: dict[str, bool],
    expectations: dict[str, bool],
) -> str:
    failure_mode = str(result.get("failure_mode") or "").strip().lower()
    if failure_mode == "blocked":
        return "blocked"
    if failure_mode and failure_mode != "success":
        return failure_mode
    if not checks["identity_ok"]:
        if _looks_like_promo_or_wrong_page(result):
            return "promo_or_wrong_page"
        if _looks_like_site_shell_success(result):
            return "shell_false_success"
        if _looks_like_detail_identity_mismatch(result):
            return "detail_identity_mismatch"
        return "bad_output"
    failed_check = _named_quality_failure(checks, expectations=expectations)
    if failed_check is not None:
        return failed_check
    if _price_requirement_failed(result, expectations=expectations):
        return "thin_detail"
    seeded_failure_mode = str(site.get("seed_failure_mode") or "").strip().lower()
    if (
        str(result.get("run_source") or "").strip().lower() == "artifact_review"
        and seeded_failure_mode
    ):
        return seeded_failure_mode
    return "control_good"


def _named_quality_failure(
    checks: dict[str, bool], *, expectations: dict[str, bool]
) -> str | None:
    if not checks["listing_noise_ok"]:
        return "listing_chrome_noise"
    rules = (
        ("expect_variants", "variant_presence_ok", "thin_detail"),
        ("require_semantic_variant_labels", "variant_labels_ok", "axis_pollution"),
        ("require_variant_price", "variant_price_ok", "variant_price_missing"),
        ("require_price_sane", "price_sane_ok", "price_magnitude_anomaly"),
        ("require_clean_category", "category_clean_ok", "category_pollution"),
        ("require_clean_long_text", "long_text_clean_ok", "long_text_pollution"),
        (
            "require_clean_variants",
            "variant_artifacts_ok",
            "variant_artifact_pollution",
        ),
        (
            "require_variant_currency_parity",
            "variant_currency_parity_ok",
            "variant_currency_mismatch",
        ),
        (
            "require_identifier_shapes",
            "identifier_shapes_ok",
            "identifier_shape_pollution",
        ),
        ("require_title_not_internal_token", "title_token_ok", "title_internal_token"),
        (
            "require_clean_system_fields",
            "system_artifacts_ok",
            "system_artifact_pollution",
        ),
    )
    return next(
        (
            failure_mode
            for expectation, check, failure_mode in rules
            if expectations.get(expectation) and not checks[check]
        ),
        None,
    )


def _quality_verdict(
    result: dict[str, object],
    *,
    checks: dict[str, bool],
    expectations: dict[str, bool],
    observed_failure_mode: str,
) -> str:
    if str(result.get("failure_mode") or "").strip().lower() == "blocked":
        return "blocked"
    if observed_failure_mode in {
        "bad_output",
        "detail_identity_mismatch",
        "listing_chrome_noise",
        "promo_or_wrong_page",
        "shell_false_success",
        "price_magnitude_anomaly",
        "category_pollution",
        "long_text_pollution",
        "variant_artifact_pollution",
        "variant_currency_mismatch",
        "identifier_shape_pollution",
        "title_internal_token",
        "system_artifact_pollution",
    }:
        return "bad_output"
    if _price_requirement_failed(result, expectations=expectations):
        return "usable_with_gaps"
    if not all(bool(value) for value in checks.values()):
        return "usable_with_gaps"
    return "good"


def _looks_like_site_shell_success(result: dict[str, object]) -> bool:
    surface = str(result.get("surface") or "").strip().lower()
    if not surface.endswith("_detail"):
        return False
    sample_title = " ".join(
        str(result.get("sample_title") or "").strip().lower().split()
    )
    if not sample_title:
        return True
    semantics = _object_dict(result.get("sample_semantics"))
    if (
        bool(semantics.get("price_present"))
        or _safe_int(semantics.get("variant_count")) >= 2
    ):
        return False
    title_tokens = _shell_identity_tokens(sample_title)
    host = (
        str(
            urlsplit(
                str(result.get("requested_url") or result.get("url") or "")
            ).hostname
            or ""
        )
        .strip()
        .lower()
    )
    host_tokens = _shell_identity_tokens(host.removeprefix("www."))
    return bool(
        host_tokens
        and host_tokens & title_tokens
        and _safe_int(result.get("populated_fields")) <= 6
    )


def _shell_identity_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value) if len(token) >= 3}


def _summary_value(summary: dict[str, object], key: str) -> str | None:
    values = _object_dict(summary.get("acquisition_summary")).get(key)
    return str(next(iter(values))) if isinstance(values, dict) and values else None


def _looks_like_real_listing_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    title = row.get("title")
    url = row.get("url")
    populated_fields = _safe_int(row.get("populated_fields"))
    return (
        bool(str(title or "").strip())
        and bool(str(url or "").strip())
        and (bool(row.get("price_present")) or populated_fields >= 3)
        and not _looks_like_utility_record(title=title, url=url)
    )


async def _ensure_harness_user_id(session) -> int:
    if _is_production_environment():
        raise RuntimeError(
            "Harness user access is disabled outside local/test environments"
        )
    harness_email = (
        str(os.getenv("HARNESS_EMAIL") or DEFAULT_HARNESS_EMAIL).strip().lower()
    )
    harness_password = str(
        os.getenv("HARNESS_PASSWORD") or DEFAULT_HARNESS_PASSWORD
    ).strip()
    harness_role = (
        str(os.getenv("HARNESS_ROLE") or "harness").strip().lower() or "harness"
    )
    password_sync_enabled = str(
        os.getenv("ENABLE_HARNESS_PASSWORD_SYNC") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    user = (
        await session.execute(select(User).where(User.email == harness_email).limit(1))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=harness_email,
            hashed_password=hash_password(harness_password),
            role=harness_role,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif not verify_password(harness_password, user.hashed_password):
        if not password_sync_enabled:
            logger.warning(
                "Harness password mismatch for user %s; refusing auto-sync because ENABLE_HARNESS_PASSWORD_SYNC is not enabled",
                int(user.id),
            )
            raise RuntimeError(
                "Harness user password mismatch; update the DB manually or set ENABLE_HARNESS_PASSWORD_SYNC=true"
            )
        user.hashed_password = hash_password(harness_password)
        logger.info(
            "Synchronized harness user password hash with ENABLE_HARNESS_PASSWORD_SYNC",
            extra={"user_id": int(user.id)},
        )
        await session.commit()
        await session.refresh(user)
    return int(user.id)


def _is_production_environment() -> bool:
    env_name = (
        os.getenv("APP_ENV")
        or os.getenv("FLASK_ENV")
        or os.getenv("ENV")
        or "development"
    )
    return str(env_name).strip().lower() not in {
        "",
        "development",
        "dev",
        "local",
        "test",
        "testing",
    }


def _safe_int(value: object) -> int:
    try:
        return 0 if value in (None, "") else int(str(value))
    except (TypeError, ValueError):
        return 0


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


_MISSING_NESTED_VALUE = object()


def expectation_met(site: dict[str, object], result: dict[str, object]) -> bool:
    """Evaluate one curated acceptance result without running a live smoke job."""

    expected = _object_dict(site.get("expected"))
    if expected:
        return _expected_contract_met(site, result, expected=expected)
    if site.get("quality_expectations"):
        bucket = str(site.get("bucket") or "").strip().lower()
        expected_verdict = "blocked" if bucket == "known_blocked" else "good"
        return (
            str(result.get("quality_verdict") or "").strip().lower() == expected_verdict
        )
    failure_mode = str(result.get("failure_mode") or "").strip().lower()
    bucket = str(site.get("bucket") or "").strip().lower()
    expected_failure_modes = {
        str(value or "").strip().lower()
        for value in _object_list(site.get("expected_failure_modes"))
        if str(value or "").strip()
    }
    if expected_failure_modes:
        return failure_mode in expected_failure_modes
    if bucket == "known_blocked":
        return failure_mode == "blocked"
    return failure_mode == "success"


def _expected_contract_met(
    site: dict[str, object],
    result: dict[str, object],
    *,
    expected: dict[str, object],
) -> bool:
    if _safe_int(result.get("records")) < _safe_int(expected.get("min_record_count")):
        return False
    sample_record = _object_dict(result.get("sample_record_data"))
    for field_name in _object_list(expected.get("fields_must_be_present")):
        if _nested_value(sample_record, str(field_name)) is _MISSING_NESTED_VALUE:
            return False
    for field_name in _object_list(expected.get("fields_must_not_be_null")):
        if _nested_value(sample_record, str(field_name)) in (None, "", [], {}):
            return False
    min_variant_count = _safe_int(expected.get("min_variant_count"))
    if (
        min_variant_count > 0
        and _safe_int(_object_dict(result.get("sample_semantics")).get("variant_count"))
        < min_variant_count
    ):
        return False
    if bool(expected.get("price_must_be_numeric")):
        surface = str(site.get("surface") or result.get("surface") or "").lower()
        if surface.endswith("_listing"):
            if (
                _safe_int(
                    _object_dict(result.get("listing_contract")).get(
                        "price_numeric_count"
                    )
                )
                <= 0
            ):
                return False
        elif not _looks_numeric_price(_nested_value(sample_record, "price")):
            return False
    return not bool(expected.get("detail_urls_must_be_present")) or bool(
        _object_dict(result.get("listing_contract")).get("detail_urls_present")
    )


def _nested_value(payload: dict[str, object], dotted_key: str) -> object:
    current: object = payload
    for segment in filter(None, str(dotted_key or "").split(".")):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING_NESTED_VALUE
        current = current.get(segment)
    return current


def _looks_numeric_price(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text.replace(",", "")
    elif "," in text and re.fullmatch(r"^\d+,\d+$", text):
        normalized = text.replace(",", ".")
    elif "." in text and re.fullmatch(r"^\d{1,3}(?:\.\d{3})+$", text):
        normalized = text.replace(".", "")
    return bool(re.fullmatch(r"^\d+(?:\.\d+)?$", normalized))


def _price_number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = re.sub(r"[^0-9.,]+", "", text)
    if "." in normalized and "," in normalized:
        decimal_separator = (
            "." if normalized.rfind(".") > normalized.rfind(",") else ","
        )
        thousands_separator = "," if decimal_separator == "." else "."
        normalized = normalized.replace(thousands_separator, "")
        normalized = normalized.replace(decimal_separator, ".")
    elif "," in normalized and re.fullmatch(r"\d+,\d{1,2}", normalized):
        normalized = normalized.replace(",", ".")
    else:
        normalized = normalized.replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _variant_row_has_axis(row: dict[str, object]) -> bool:
    axis_values = [
        str(row.get(field_name) or "").strip() for field_name in _VARIANT_AXIS_FIELDS
    ]
    return any(axis_values)


def _normalized_space(value: object) -> str:
    return " ".join(str(value or "").strip().split())
