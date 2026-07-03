from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.extraction.collectors.dom import (
    DomCollector,
    collect_requested_fields,
    css_recipe_evidence,
)
from app.extraction.collectors.jsonld import JsonLdCollector
from app.extraction.collectors.js_state import JsStateCollector
from app.extraction.collectors.metadata import (
    MicrodataCollector,
    NetworkCollector,
    OpenGraphCollector,
)
from app.extraction.collectors.url import UrlCollector
from app.core.config import field_mappings
from app.core.config.extraction_price_rules import (
    DETAIL_AMBIGUOUS_DOM_PRICE_VALUE_THRESHOLD,
)
from app.core.config.locale_format_rules import (
    locale_hint_from_page_url,
    money_has_ambiguous_decimal,
    parse_money,
    validate_gtin,
)
from app.core.config.extraction_rules import (
    AVAILABILITY_CANONICAL_ENUM,
    DETAIL_BRAND_BOILERPLATE_VALUES,
    DETAIL_BRAND_CATEGORY_PATTERN,
    DETAIL_DESCRIPTION_HARD_BOUNDARY_LENGTHS,
    DETAIL_DESCRIPTION_INCOMPLETE_ENDING_PATTERN,
    DETAIL_DESCRIPTION_MIN_GROUNDED_PROSE_LENGTH,
    DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN,
    DETAIL_DESCRIPTION_NON_PRODUCT_LOCATOR_TOKENS,
    DETAIL_DESCRIPTION_PROMOTIONAL_PATTERNS,
    DETAIL_DESCRIPTION_UI_PATTERNS,
    DETAIL_LOWER_ALNUM_TOKEN_PATTERN,
    DETAIL_NON_LOWER_ALNUM_PATTERN,
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
    DETAIL_TITLE_CODE_ONLY_PATTERN,
    DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN,
    DETAIL_TITLE_GENERIC_CATEGORY_VALUES,
    DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN,
    DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN,
    DETAIL_TITLE_MEASUREMENT_FLAG,
    DETAIL_TITLE_NON_PRODUCT_LOCATOR_TOKENS,
    DETAIL_TITLE_MEASUREMENT_PATTERN,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
    DETAIL_TITLE_REJECTION_FLAGS,
    DETAIL_TITLE_REJECT_SUFFIXES,
    DETAIL_TITLE_REJECT_VALUES,
    DETAIL_TITLE_SHORT_NAVIGATION_PATTERN,
    DETAIL_TITLE_STYLE_ONLY_MAX_WORDS,
    DETAIL_TITLE_STYLE_ONLY_TOKENS,
    DETAIL_TITLE_TRAILING_CODE_PATTERN,
    DETAIL_TITLE_UI_INSTRUCTION_MIN_HITS,
    DETAIL_TITLE_UI_INSTRUCTION_TOKENS,
    DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP,
    INVALID_AVAILABILITY_EVIDENCE_FLAG,
    normalize_availability_value,
    VARIANT_COLOR_BRAND_CONFLICT_FLAG,
)
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    CollectorOutcome,
    Evidence,
    FACT_TYPES,
    HarvestResult,
)
from app.extraction.surfaces import Surface
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_title_has_seo_pollution,
    detail_title_is_url_corroborated_style_code,
    detail_url_looks_like_product,
    normalize_detail_marketplace_title,
    semantic_detail_identity_tokens,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce_text import (
    coerce_brand_text,
)
from app.core.shared.text_coerce import coerce_long_text, coerce_text


def collect_ecommerce_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Evidence, ...]:
    return harvest_ecommerce_detail(
        bundle,
        reader,
        requested_fields=requested_fields,
    ).evidence


def harvest_ecommerce_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    requested_fields: tuple[str, ...] = (),
) -> HarvestResult:
    rows: list[Evidence] = []
    outcomes: list[CollectorOutcome] = []
    admitted_source_objects = 0
    for collector in default_collectors():
        harvest_method = getattr(collector, "harvest", None)
        if callable(harvest_method):
            harvest = collector.harvest(
                bundle, reader, requested_fields=requested_fields
            )
            collector_rows = tuple(
                ev for ev in harvest.evidence if ev.fact_type in FACT_TYPES
            )
            rows.extend(collector_rows)
            admitted_source_objects += harvest.admitted_source_objects
            outcomes.extend(
                row for row in harvest.outcomes if row.outcome == "budget_limited"
            )
            outcomes.append(
                CollectorOutcome(
                    collector_id=collector.collector_id,
                    outcome="produced_evidence" if collector_rows else "no_match",
                    evidence_count=len(collector_rows),
                )
            )
            continue
        before = len(rows)
        rows.extend(
            ev for ev in collector.collect(bundle, reader) if ev.fact_type in FACT_TYPES
        )
        produced = len(rows) - before
        admitted_source_objects += len(
            {
                (row.collector_id, row.artifact_id, row.subject_id)
                for row in rows[before:]
            }
        )
        outcomes.append(
            CollectorOutcome(
                collector_id=collector.collector_id,
                outcome="produced_evidence" if produced else "no_match",
                evidence_count=produced,
            )
        )
    recipe_rows = tuple(css_recipe_evidence(bundle, reader))
    requested_rows = collect_requested_fields(bundle, reader, requested_fields)
    rows.extend(recipe_rows)
    rows.extend(requested_rows)
    admitted_source_objects += len(
        {
            (row.collector_id, row.artifact_id, row.subject_id)
            for row in (*recipe_rows, *requested_rows)
        }
    )
    if recipe_rows:
        outcomes.append(
            CollectorOutcome(
                collector_id="css_recipe",
                outcome="produced_evidence",
                evidence_count=len(recipe_rows),
            )
        )
    if requested_rows:
        outcomes.append(
            CollectorOutcome(
                collector_id="requested_fields",
                outcome="produced_evidence",
                evidence_count=len(requested_rows),
            )
        )
    return HarvestResult(
        surface=Surface.ECOMMERCE_DETAIL,
        evidence=tuple(rows),
        collector_outcomes=tuple(outcomes),
        admitted_source_objects=admitted_source_objects,
    )


def default_collectors():
    return (
        JsonLdCollector(),
        OpenGraphCollector(),
        MicrodataCollector(),
        JsStateCollector(),
        NetworkCollector(),
        DomCollector(),
        UrlCollector(),
    )


def normalize_ecommerce_detail(
    evidence: tuple[Evidence, ...], *, page_url: str, locale_hint: str | None = None
) -> tuple[Evidence, ...]:
    effective_locale_hint = locale_hint or locale_hint_from_page_url(page_url)
    normalized = tuple(
        normalize_evidence(ev, page_url=page_url, locale_hint=effective_locale_hint)
        for ev in evidence
    )
    return _flag_ambiguous_dom_prices(
        _flag_brand_conflicts(normalized, page_brand=_page_brand(normalized))
    )


def _flag_ambiguous_dom_prices(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    structured_subjects = {
        row.subject_id
        for row in evidence
        if row.fact_type == field_mappings.OFFER_PRICE_FACT_TYPE
        and row.collector_id in {"adapter", "jsonld", "js_state", "network"}
        and row.subject_id
    }
    dom_prices_by_subject: dict[str, set[str]] = {}
    for row in evidence:
        if (
            row.fact_type != field_mappings.OFFER_PRICE_FACT_TYPE
            or row.collector_id != "dom"
            or not row.subject_id
            or row.subject_id in structured_subjects
        ):
            continue
        dom_prices_by_subject.setdefault(row.subject_id, set()).add(str(row.value))
    ambiguous_subjects = {
        subject_id
        for subject_id, values in dom_prices_by_subject.items()
        if len(values) >= DETAIL_AMBIGUOUS_DOM_PRICE_VALUE_THRESHOLD
    }
    if not ambiguous_subjects:
        return evidence
    return tuple(
        row.model_copy(
            update={"flags": tuple(sorted(set(row.flags) | {"ambiguous_page_price"}))}
        )
        if row.fact_type == field_mappings.OFFER_PRICE_FACT_TYPE
        and row.collector_id == "dom"
        and row.subject_id in ambiguous_subjects
        else row
        for row in evidence
    )


def _flag_brand_conflicts(
    evidence: tuple[Evidence, ...], *, page_brand: Evidence | None
) -> tuple[Evidence, ...]:
    public_brand_rows = tuple(
        row
        for row in evidence
        if row.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE
        and _brand_role_can_publish(row)
    )
    brands = {
        str(row.value).strip().casefold()
        for row in public_brand_rows
        if str(row.value).strip()
    }
    structured_brands = {
        str(row.value).strip().casefold()
        for row in public_brand_rows
        if row.collector_id in {"adapter", "jsonld", "js_state", "network"}
        and str(row.value).strip()
    }
    product_url_brands = tuple(
        str(row.value).strip().casefold()
        for row in public_brand_rows
        if row.metadata.get("derived_by") == "brand_from_product_url"
        and str(row.value).strip()
    )
    subject_titles = {
        (
            row.subject_id,
            " ".join(
                re.findall(DETAIL_LOWER_ALNUM_TOKEN_PATTERN, str(row.value).casefold())
            ),
        )
        for row in evidence
        if row.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE
        and row.subject_id
        and not (set(row.flags) & DETAIL_TITLE_REJECTION_FLAGS)
    }
    color_rows = tuple(
        row for row in evidence if row.fact_type == "variant.option.color"
    )
    color_values = {
        str(row.value).strip().casefold()
        for row in color_rows
        if str(row.value).strip()
    }
    conflicting_color_axis = (
        len({row.subject_id for row in color_rows if row.subject_id}) >= 2
        and len(color_values) == 1
        and bool(color_values & brands)
    )
    page_value = str(page_brand.value).casefold() if page_brand else ""
    support_values = tuple(
        re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", str(row.value).casefold())
        for row in evidence
        if row.fact_type != field_mappings.PRODUCT_BRAND_FACT_TYPE
    )
    page_compact = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", page_value)
    page_support = sum(page_compact in candidate for candidate in support_values)

    def conflict_flag(row: Evidence) -> str | None:
        value = str(row.value).strip().casefold()
        if row.fact_type == "variant.option.color":
            return (
                VARIANT_COLOR_BRAND_CONFLICT_FLAG
                if conflicting_color_axis and value in brands
                else None
            )
        if row.fact_type != field_mappings.PRODUCT_BRAND_FACT_TYPE:
            return None
        if not _brand_role_can_publish(row):
            return "non_manufacturer_brand_role"
        normalized = " ".join(re.findall(DETAIL_LOWER_ALNUM_TOKEN_PATTERN, value))
        compact = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", value)
        host_identity_conflict = bool(
            product_url_brands
            and row.metadata.get("derived_by")
            in {"brand_from_title_host", "page_identity"}
            and any(
                compact
                == re.sub(
                    DETAIL_NON_LOWER_ALNUM_PATTERN,
                    "",
                    title.rsplit(" - ", 1)[-1].casefold(),
                )
                and any(
                    re.sub(
                        DETAIL_NON_LOWER_ALNUM_PATTERN, "", title.casefold()
                    ).startswith(re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", candidate))
                    for candidate in product_url_brands
                )
                for item in evidence
                if item.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE
                and " - " in (title := str(item.value).strip())
            )
        )
        if host_identity_conflict:
            return "brand_identity_conflict"
        partial_page_brand = bool(
            page_value
            and value != page_value
            and (
                "brand_boilerplate" in row.flags
                or normalized in page_value
                or page_value in normalized
                or (
                    row.directness == "inferred"
                    and row.collector_id != "dom"
                    and page_support >= 2
                    and page_support
                    > sum(
                        re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", value) in candidate
                        for candidate in support_values
                    )
                )
            )
        )
        if normalized and (
            (row.subject_id, normalized) in subject_titles or partial_page_brand
        ):
            return "product_name_as_brand"
        if structured_brands and value not in structured_brands:
            title_suffix = any(
                (title := str(item.value).strip().casefold()) == value
                or title.endswith(f" {value}")
                or title.endswith(f"- {value}")
                for item in evidence
                if item.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE
            )
            if value in color_values or title_suffix:
                return VARIANT_COLOR_BRAND_CONFLICT_FLAG
        return None

    return tuple(
        row.model_copy(update={"flags": tuple(sorted({*row.flags, flag}))})
        if (flag := conflict_flag(row))
        else row
        for row in evidence
    )


def _page_brand(evidence: tuple[Evidence, ...]) -> Evidence | None:
    return next(
        (
            row
            for row in evidence
            if row.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE
            and (
                row.brand_role == "site_identity"
                or row.metadata.get("derived_by") == "page_identity"
            )
        ),
        None,
    )


def _brand_role_can_publish(row: Evidence) -> bool:
    return (row.brand_role or "manufacturer") in {
        "manufacturer",
        "designer",
        "private_label",
        "vendor",
        "unknown",
    }


def assess_ecommerce_detail_quality(
    record: dict[str, object],
    resolution,
    bundle: CaptureBundle,
    *,
    requested_fields: tuple[str, ...] = (),
) -> str:
    if bundle.acquisition_outcome in {"error", "blocked"}:
        return bundle.acquisition_outcome
    if not record:
        return "empty"
    if resolution.blocking_finding_ids:
        return "invalid"
    if not resolution.primary_product_entity_id:
        return "review"
    if _only_slug_identity(record):
        return "review"
    if _title_is_review_only(resolution):
        return "review"
    requested_fields_present = all(
        record.get("image_url" if field == "image" else field)
        not in (None, "", [], {}, ())
        for field in requested_fields
    )
    if (
        record.get("url")
        and record.get("title")
        and _has_complete_public_offer(record)
        and requested_fields_present
        and not resolution.unresolved_fact_types
    ):
        return "success"
    return "partial" if record.get("title") or record.get("price") else "review"


def _only_slug_identity(record: dict[str, object]) -> bool:
    title = str(record.get("title") or "").strip()
    url = str(record.get("url") or "").strip()
    if not title or not url:
        return False
    commerce_fields = {
        "brand",
        "sku",
        "mpn",
        "gtin",
        "price",
        "currency",
        "availability",
        "image_url",
        "description",
        "variants",
    }
    if bool(record.get("variant_count")) or any(
        record.get(field) not in (None, "", [], {}, ()) for field in commerce_fields
    ):
        return False
    return title.casefold() == detail_title_from_url(url).casefold()


def _has_complete_public_offer(record: dict[str, object]) -> bool:
    if record.get("price") not in (None, "", [], {}, ()) and record.get(
        "currency"
    ) not in (None, "", [], {}, ()):
        return True
    variants = record.get("variants")
    if not isinstance(variants, (list, tuple)):
        return False
    return any(
        isinstance(row, dict)
        and row.get("price") not in (None, "", [], {}, ())
        and row.get("currency") not in (None, "", [], {}, ())
        for row in variants
    )


def _title_is_review_only(resolution) -> bool:
    return any(
        decision.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE
        and decision.entity_id == resolution.primary_product_entity_id
        and decision.status == "resolved"
        and decision.rule_id == "TITLE_URL_REVIEW_ONLY"
        for decision in resolution.decisions
    )


def normalize_evidence(
    evidence: Evidence, *, page_url: str, locale_hint: str | None = None
) -> Evidence:
    value = evidence.value
    flags = set(evidence.flags)
    if isinstance(value, str):
        value = re.sub(r"\s+", " ", value).strip()
    if evidence.fact_type in {
        field_mappings.PRODUCT_TITLE_FACT_TYPE,
        field_mappings.PRODUCT_BRAND_FACT_TYPE,
    } and isinstance(value, str):
        value = coerce_text(value) or value
    if (
        evidence.fact_type == field_mappings.PRODUCT_DESCRIPTION_FACT_TYPE
        and isinstance(value, str)
    ):
        value = coerce_long_text(value) or value
        value = _segment_grounded_description(value)
    if evidence.fact_type == field_mappings.ASSET_IMAGE_URL_FACT_TYPE and isinstance(
        value, str
    ):
        value = re.sub(r"\s+\d+(?:\.\d+)?[wx]\s*$", "", value, flags=re.IGNORECASE)
    if evidence.fact_type in {
        field_mappings.PRODUCT_URL_FACT_TYPE,
        "variant.url",
        field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
    } and isinstance(value, str):
        value = urljoin(page_url, value)
    if (
        evidence.fact_type == field_mappings.PRODUCT_URL_FACT_TYPE
        and isinstance(value, str)
        and detail_url_looks_like_product(page_url)
        and not detail_url_looks_like_product(value)
    ):
        flags.add("non_detail_product_url")
    if evidence.fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE and isinstance(
        value, str
    ):
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            flags.add("invalid_currency")
    if evidence.fact_type in {
        field_mappings.OFFER_PRICE_FACT_TYPE,
        field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    }:
        value = _money(value, flags, locale_hint=locale_hint)
    if evidence.fact_type == field_mappings.OFFER_AVAILABILITY_FACT_TYPE:
        value = _normalize_availability_value(value, flags)
    if (
        evidence.fact_type in field_mappings.ECOMMERCE_INTEGER_IDENTIFIER_FACT_TYPES
        and type(value) is int
    ):
        value = str(value)
    if (
        evidence.fact_type in field_mappings.ECOMMERCE_TYPED_STRING_FACT_TYPES
        and not isinstance(value, str)
    ):
        flags.add(field_mappings.INVALID_SCALAR_TYPE_EVIDENCE_FLAG)
    if evidence.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE and isinstance(
        value, str
    ):
        value = _normalize_brand_value(value, flags)
    if (
        evidence.fact_type == field_mappings.PRODUCT_DESCRIPTION_FACT_TYPE
        and isinstance(value, str)
    ):
        _flag_description_value(evidence, value, flags)
    if evidence.fact_type in {"product.gtin", "variant.gtin"} and isinstance(
        value, str
    ):
        value = re.sub(r"\D+", "", value)
        if value and not validate_gtin(value):
            flags.add("invalid_gtin")
    if isinstance(value, str) and value.lower() in {"n/a", "none", "null", "undefined"}:
        flags.add("placeholder_text")
    if evidence.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE and isinstance(
        value, str
    ):
        value = normalize_detail_marketplace_title(value)
        title_locator = str(evidence.locator.value or "").casefold()
        if any(
            token in title_locator for token in DETAIL_TITLE_NON_PRODUCT_LOCATOR_TOKENS
        ):
            flags.add("generic_title")
        flags.update(_title_flags(evidence, value=value, page_url=page_url))
    return evidence.model_copy(update={"value": value, "flags": tuple(sorted(flags))})


def _normalize_availability_value(value: Any, flags: set[str]) -> Any:
    normalized = normalize_availability_value(value)
    if normalized not in AVAILABILITY_CANONICAL_ENUM:
        flags.add(INVALID_AVAILABILITY_EVIDENCE_FLAG)
    return normalized


def _normalize_brand_value(value: str, flags: set[str]) -> str:
    coerced = coerce_brand_text(_normalize_brand_hierarchy(value))
    normalized = coerced or value
    if coerced is None:
        flags.add("invalid_brand_scalar")
    parsed_brand = urlsplit(normalized)
    if parsed_brand.scheme.casefold() in {"http", "https"} and parsed_brand.netloc:
        flags.add("brand_url")
    if normalized.casefold() in DETAIL_BRAND_BOILERPLATE_VALUES:
        flags.add("brand_boilerplate")
    if re.fullmatch(DETAIL_BRAND_CATEGORY_PATTERN, normalized, re.IGNORECASE):
        flags.add("category_as_brand")
    return normalized


def _segment_grounded_description(value: str) -> str:
    """Salvage the grounded prose head when a description ends in a compacted,
    separator-less feature list (``...minimalistic look.\xa0Soft Rock100%
    Cotton14ozScreen printed``). The compacted suffix trips
    ``description_missing_separator`` and used to invalidate the entire
    candidate. Keep the longest complete sentence span preceding the first
    compaction boundary and drop only the run-together tail; return the value
    unchanged when no usable prose head exists so the existing invalidity flags
    still apply."""
    match = re.search(DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN, value)
    if match is None:
        return value
    head = value[: match.start()]
    boundary = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
    if boundary == -1:
        return value
    prose = head[: boundary + 1].strip()
    if len(prose) < DETAIL_DESCRIPTION_MIN_GROUNDED_PROSE_LENGTH or " " not in prose:
        return value
    return prose


def _flag_description_value(evidence: Evidence, value: str, flags: set[str]) -> None:
    locator_value = str(evidence.locator.value or "").casefold()
    if any(
        token in locator_value
        for token in DETAIL_DESCRIPTION_NON_PRODUCT_LOCATOR_TOKENS
    ):
        flags.add("description_ui_pollution")
    if len(value) in DETAIL_DESCRIPTION_HARD_BOUNDARY_LENGTHS:
        flags.add("description_hard_boundary")
    tail = value.rstrip()
    if tail.endswith("...") or (tail and ord(tail[-1]) == 8230):
        flags.add("description_truncated_ellipsis")
    if len(value) >= 120 and re.search(
        DETAIL_DESCRIPTION_INCOMPLETE_ENDING_PATTERN, value, re.IGNORECASE
    ):
        flags.add("description_incomplete_ending")
    if re.search(DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN, value):
        flags.add("description_missing_separator")
    if re.search(r",\s*[a-z]{2,5}$", tail, re.IGNORECASE):
        flags.add("description_truncated_fragment")
    if any(
        re.search(pattern, value, re.IGNORECASE)
        for pattern in DETAIL_DESCRIPTION_UI_PATTERNS
    ):
        flags.add("description_ui_pollution")
    if any(
        re.search(pattern, value, re.IGNORECASE)
        for pattern in DETAIL_DESCRIPTION_PROMOTIONAL_PATTERNS
    ):
        flags.add("description_promotional_copy")


def _normalize_brand_hierarchy(value: str) -> str:
    parts = [part.strip() for part in value.split("/") if part.strip()]
    if len(parts) < 2 or not all(
        re.fullmatch(r"[A-Za-z0-9&'._-]+", part) for part in parts
    ):
        return value
    leaf = parts[-1]
    leaf_key = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", leaf.casefold())
    parent_keys = [
        re.sub(
            DETAIL_NON_LOWER_ALNUM_PATTERN, "", part.casefold().removesuffix("-parent")
        )
        for part in parts[:-1]
    ]
    if not leaf_key or not any(
        leaf_key == parent or leaf_key in parent for parent in parent_keys
    ):
        return value
    return " ".join(token.capitalize() for token in re.split(r"[-_]+", leaf) if token)


def _title_flags(evidence: Evidence, *, value: str, page_url: str) -> set[str]:
    flags: set[str] = set()
    key = " ".join(re.findall(DETAIL_LOWER_ALNUM_TOKEN_PATTERN, value.casefold()))
    url_title_key = " ".join(
        re.findall(
            DETAIL_LOWER_ALNUM_TOKEN_PATTERN, detail_title_from_url(page_url).casefold()
        )
    )
    if evidence.collector_id == "url":
        flags.add("url_derived_title")
    if re.search(
        DETAIL_TITLE_PATH_EXTENSION_PATTERN, str(evidence.raw_value), re.IGNORECASE
    ) or re.fullmatch(
        DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN, value.strip(), re.IGNORECASE
    ):
        flags.add("filename_title")
    url_contains_title_code = detail_title_is_url_corroborated_style_code(
        value, page_url
    )
    if (
        re.fullmatch(DETAIL_TITLE_CODE_ONLY_PATTERN, value.strip())
        or re.fullmatch(DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN, value.strip())
        or re.fullmatch(
            DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN, value.strip(), re.IGNORECASE
        )
    ) and not url_contains_title_code:
        flags.add("code_only_title")
    if re.fullmatch(DETAIL_TITLE_MEASUREMENT_PATTERN, value.strip(), re.IGNORECASE):
        flags.add(DETAIL_TITLE_MEASUREMENT_FLAG)
    if (
        evidence.collector_id == "url"
        and key == url_title_key
        and re.search(DETAIL_TITLE_TRAILING_CODE_PATTERN, value.strip(), re.IGNORECASE)
    ):
        flags.add("filename_title")
    if key in DETAIL_SHELL_TITLE_KEYS:
        flags.add(DETAIL_SHELL_TITLE_FLAG)
    if (
        key in DETAIL_TITLE_REJECT_VALUES
        or key in DETAIL_TITLE_GENERIC_CATEGORY_VALUES
        or value.casefold().endswith(DETAIL_TITLE_REJECT_SUFFIXES)
    ):
        flags.add("generic_title")
    words = re.findall(DETAIL_LOWER_ALNUM_TOKEN_PATTERN, value.casefold())
    if (
        0 < len(words) <= DETAIL_TITLE_STYLE_ONLY_MAX_WORDS
        and set(words) <= DETAIL_TITLE_STYLE_ONLY_TOKENS
    ):
        flags.add("generic_title")
    if re.fullmatch(
        DETAIL_TITLE_SHORT_NAVIGATION_PATTERN, value.strip(), re.IGNORECASE
    ):
        flags.add("generic_title")
    if detail_title_has_seo_pollution(value, str(evidence.raw_value or ""), words):
        flags.add("seo_title_pollution")
    if (
        len(set(words) & DETAIL_TITLE_UI_INSTRUCTION_TOKENS)
        >= DETAIL_TITLE_UI_INSTRUCTION_MIN_HITS
    ):
        flags.add("generic_title")
    url_tokens = set(semantic_detail_identity_tokens(page_url))
    title_tokens = set(semantic_identity_tokens(value))
    overlap = len(url_tokens & title_tokens)
    if len(title_tokens) == 1 and len(url_tokens) >= 2 and title_tokens < url_tokens:
        flags.add("truncated_title")
    if url_tokens and title_tokens:
        required_overlap = min(
            DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP,
            len(url_tokens),
            len(title_tokens),
        )
        flags.add(
            "title_url_match"
            if overlap >= required_overlap or url_contains_title_code
            else "title_url_mismatch"
        )
    return flags


def _money(value: Any, flags: set[str], *, locale_hint: str | None = None) -> str:
    parsed = parse_money(value, locale_hint=locale_hint)
    if parsed is None:
        flags.add("invalid_decimal")
        return str(value or "")
    if money_has_ambiguous_decimal(value, locale_hint=locale_hint):
        flags.add("ambiguous_decimal")
    return str(parsed)
