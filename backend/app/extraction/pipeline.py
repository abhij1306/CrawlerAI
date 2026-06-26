from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
import json
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
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
    DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS,
)
from app.core.config.extraction_rules import (
    AVAILABILITY_URL_MAP,
    CURRENCY_SYMBOL_MAP,
    DETAIL_BRAND_BOILERPLATE_VALUES,
    DETAIL_BRAND_CATEGORY_PATTERN,
    DETAIL_DESCRIPTION_HARD_BOUNDARY_LENGTHS,
    DETAIL_DESCRIPTION_INCOMPLETE_ENDING_PATTERN,
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
    DETAIL_TITLE_SEO_POLLUTION_PATTERN,
    DETAIL_TITLE_SEO_PREFIXES,
    DETAIL_TITLE_SEO_PREFIX_MIN_WORDS,
    DETAIL_TITLE_SHORT_NAVIGATION_PATTERN,
    DETAIL_TITLE_STYLE_ONLY_MAX_WORDS,
    DETAIL_TITLE_STYLE_ONLY_TOKENS,
    DETAIL_TITLE_TRAILING_CODE_PATTERN,
    DETAIL_TITLE_UI_INSTRUCTION_MIN_HITS,
    DETAIL_TITLE_UI_INSTRUCTION_TOKENS,
    DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP,
    INVALID_AVAILABILITY_EVIDENCE_FLAG,
    NORMALIZER_AVAILABILITY_TOKENS,
    VARIANT_COLOR_BRAND_CONFLICT_FLAG,
)
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    CommerceDetailRecord,
    Evidence,
    FACT_TYPES,
)
from app.extraction.ids import stable_id
from app.extraction.materialization import materialize
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_url_looks_like_product,
    semantic_detail_identity_tokens,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce_price import repair_price_unit
from app.core.shared.field_coerce_text import (
    coerce_brand_text,
    infer_brand_from_page_identity,
    infer_brand_from_product_url,
    infer_brand_from_title_host,
    infer_brand_from_title_marker,
)
from app.extraction.entities import EntitySet


def collect_ecommerce_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Evidence, ...]:
    return (
        tuple(
            ev
            for collector in default_collectors()
            for ev in collector.collect(bundle, reader)
            if ev.fact_type in FACT_TYPES
        )
        + tuple(css_recipe_evidence(bundle, reader))
        + collect_requested_fields(bundle, reader, requested_fields)
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
    evidence: tuple[Evidence, ...], *, page_url: str
) -> tuple[Evidence, ...]:
    normalized = tuple(normalize_evidence(ev, page_url=page_url) for ev in evidence)
    derived = tuple(
        row
        for ev in normalized
        for row in (
            _currency_from_price_symbol(ev),
            _brand_from_title_host(ev, page_url=page_url),
            _brand_from_product_url(ev, page_url=page_url),
            _brand_from_title_marker(ev),
            _availability_from_stock_quantity(ev),
        )
        if row is not None
    )
    normalized_derived = tuple(
        normalize_evidence(row, page_url=page_url) for row in derived
    )
    page_brand = _brand_from_page_identity(normalized, page_url=page_url)
    normalized_page_brand = (
        normalize_evidence(page_brand, page_url=page_url) if page_brand else None
    )
    combined = (
        normalized
        + normalized_derived
        + ((normalized_page_brand,) if normalized_page_brand else ())
    )
    return _dedupe_equivalent(
        _flag_ambiguous_dom_prices(
            _flag_brand_conflicts(combined, page_brand=normalized_page_brand)
        )
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
        if len(values) >= 4
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
    brand_rows = tuple(
        row
        for row in evidence
        if row.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE
    )
    brands = {
        str(row.value).strip().casefold()
        for row in brand_rows
        if str(row.value).strip()
    }
    structured_brands = {
        str(row.value).strip().casefold()
        for row in brand_rows
        if row.collector_id in {"adapter", "jsonld", "js_state", "network"}
        and str(row.value).strip()
    }
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
        normalized = " ".join(re.findall(DETAIL_LOWER_ALNUM_TOKEN_PATTERN, value))
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


def _brand_from_page_identity(
    evidence: tuple[Evidence, ...], *, page_url: str
) -> Evidence | None:
    title = next(
        (
            row
            for row in evidence
            if row.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE
        ),
        None,
    )
    if title is None:
        return None
    brand = infer_brand_from_page_identity(
        url=page_url,
        title=title.value,
        evidence_values=tuple(
            row.value
            for row in evidence
            if row.fact_type
            not in {
                field_mappings.PRODUCT_TITLE_FACT_TYPE,
                field_mappings.PRODUCT_URL_FACT_TYPE,
                "variant.url",
            }
        ),
        existing_brands=tuple(
            row.value
            for row in evidence
            if row.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE
        ),
    )
    if not brand:
        return None
    return title.model_copy(
        update={
            "evidence_id": stable_id("ev", title.evidence_id, "page_brand", brand),
            "fact_type": field_mappings.PRODUCT_BRAND_FACT_TYPE,
            "raw_value": brand,
            "value": brand,
            "confidence": min(float(title.confidence), 0.82),
            "directness": "inferred",
            "metadata": {**dict(title.metadata), "derived_by": "page_identity"},
        }
    )


def _preferred_price_currency(rows: tuple[Evidence, ...]) -> str | None:
    priority = {
        collector_id: index
        for index, collector_id in enumerate(DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY)
    }
    valid = tuple(
        row
        for row in rows
        if str(row.value or "").strip() and "invalid_currency" not in row.flags
    )
    if not valid:
        return None
    best_rank = min(priority.get(row.collector_id, len(priority)) for row in valid)
    values = {
        str(row.value).strip().upper()
        for row in valid
        if priority.get(row.collector_id, len(priority)) == best_rank
    }
    return next(iter(values)) if len(values) == 1 else None


def normalize_ecommerce_price_units(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> tuple[Evidence, ...]:
    by_id = {row.evidence_id: row for row in evidence}
    offer_by_evidence = {
        eid: offer
        for offer in entities.offers
        for ids in offer.fact_evidence.values()
        for eid in ids
    }
    currency_rows_by_offer = {
        offer.entity_id: tuple(
            by_id[eid]
            for eid in offer.fact_evidence.get(
                field_mappings.OFFER_CURRENCY_FACT_TYPE, ()
            )
            if eid in by_id and "invalid_currency" not in by_id[eid].flags
        )
        for offer in entities.offers
    }
    product_currency_rows = {
        product.entity_id: tuple(
            row
            for offer in entities.offers
            if offer.product_entity_id == product.entity_id
            for row in currency_rows_by_offer.get(offer.entity_id, ())
        )
        for product in entities.products
    }
    price_rows = tuple(
        row
        for row in evidence
        if row.fact_type
        in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
        }
    )
    currency_by_evidence: dict[str, str] = {}
    for row in price_rows:
        offer = offer_by_evidence.get(row.evidence_id)
        if offer is None:
            continue
        currency = _preferred_price_currency(
            currency_rows_by_offer.get(offer.entity_id, ())
        ) or _preferred_price_currency(
            product_currency_rows.get(offer.product_entity_id, ())
        )
        if currency:
            currency_by_evidence[row.evidence_id] = currency
    peer_values: dict[str, object] = {}
    for row in price_rows:
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency_by_evidence.get(row.evidence_id, ""),
        )
        peer_values[row.evidence_id] = repaired[0] if repaired else row.value
    repaired_rows: list[Evidence] = []
    for row in evidence:
        offer = offer_by_evidence.get(row.evidence_id)
        currency = currency_by_evidence.get(row.evidence_id)
        if (
            offer is None
            or currency is None
            or row.fact_type
            not in {
                field_mappings.OFFER_PRICE_FACT_TYPE,
                field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
            }
        ):
            repaired_rows.append(row)
            continue
        peers = tuple(
            peer_values[other.evidence_id]
            for other in price_rows
            if other.evidence_id != row.evidence_id
            and other.fact_type == row.fact_type
            and (
                (
                    (other_offer := offer_by_evidence.get(other.evidence_id))
                    is not None
                    and other_offer.product_entity_id == offer.product_entity_id
                    and (
                        other.collector_id != row.collector_id
                        or other_offer.entity_id == offer.entity_id
                    )
                )
                or (
                    offer_by_evidence.get(other.evidence_id) is None
                    and other.collector_id in DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS
                    and "invalid_decimal" not in other.flags
                )
            )
        )
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency,
            corroborating_values=peers,
        )
        if repaired is None:
            repaired_rows.append(row)
            continue
        value, rule_id = repaired
        repaired_rows.append(
            row.model_copy(
                update={
                    "value": value,
                    "flags": tuple(sorted(set(row.flags) | {rule_id})),
                    "metadata": {
                        **dict(row.metadata),
                        "price_unit_rule": rule_id,
                        "price_unit_source_key": row.locator.value,
                    },
                }
            )
        )
    return tuple(repaired_rows)


def materialize_ecommerce_detail(
    entities, resolution, evidence: tuple[Evidence, ...], *, canonical_url: str
) -> CommerceDetailRecord:
    return materialize(entities, resolution, evidence, canonical_url=canonical_url)


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
    if any(
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


def normalize_evidence(evidence: Evidence, *, page_url: str) -> Evidence:
    value = evidence.value
    flags = set(evidence.flags)
    if isinstance(value, str):
        value = re.sub(r"\s+", " ", value).strip()
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
        value = _money(value, flags)
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
        if value and len(value) not in {8, 12, 13, 14}:
            flags.add("invalid_gtin")
    if isinstance(value, str) and value.lower() in {"n/a", "none", "null", "undefined"}:
        flags.add("placeholder_text")
    if evidence.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE and isinstance(
        value, str
    ):
        title_locator = str(evidence.locator.value or "").casefold()
        if any(
            token in title_locator for token in DETAIL_TITLE_NON_PRODUCT_LOCATOR_TOKENS
        ):
            flags.add("generic_title")
        flags.update(_title_flags(evidence, value=value, page_url=page_url))
    return evidence.model_copy(update={"value": value, "flags": tuple(sorted(flags))})


def _normalize_availability_value(value: Any, flags: set[str]) -> Any:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if isinstance(value, (int, float)) and value in {0, 1}:
        return "in_stock" if value == 1 else "out_of_stock"
    if isinstance(value, str):
        return _availability(value)
    flags.add(INVALID_AVAILABILITY_EVIDENCE_FLAG)
    return value


def _normalize_brand_value(value: str, flags: set[str]) -> str:
    normalized = coerce_brand_text(_normalize_brand_hierarchy(value)) or value
    parsed_brand = urlsplit(normalized)
    if parsed_brand.scheme.casefold() in {"http", "https"} and parsed_brand.netloc:
        flags.add("brand_url")
    if normalized.casefold() in DETAIL_BRAND_BOILERPLATE_VALUES:
        flags.add("brand_boilerplate")
    if re.fullmatch(DETAIL_BRAND_CATEGORY_PATTERN, normalized, re.IGNORECASE):
        flags.add("category_as_brand")
    return normalized


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
    if (
        re.fullmatch(DETAIL_TITLE_CODE_ONLY_PATTERN, value.strip())
        or re.fullmatch(DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN, value.strip())
        or re.fullmatch(
            DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN, value.strip(), re.IGNORECASE
        )
    ):
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
    if re.search(DETAIL_TITLE_SEO_POLLUTION_PATTERN, value, re.IGNORECASE) or (
        len(words) >= DETAIL_TITLE_SEO_PREFIX_MIN_WORDS
        and value.casefold().startswith(DETAIL_TITLE_SEO_PREFIXES)
    ):
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
            "title_url_match" if overlap >= required_overlap else "title_url_mismatch"
        )
    return flags


def _availability(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    key = text.casefold()
    mapped = AVAILABILITY_URL_MAP.get(key)
    if mapped:
        return mapped
    normalized = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, " ", key).strip()
    for public_value, tokens in NORMALIZER_AVAILABILITY_TOKENS.items():
        if normalized in {
            re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, " ", token).strip()
            for token in tokens
        }:
            return public_value
    return text


def _money(value: Any, flags: set[str]) -> str:
    text = re.sub(r"[^0-9.,-]", "", str(value or "")).replace(",", "")
    try:
        return str(Decimal(text))
    except (InvalidOperation, ValueError):
        flags.add("invalid_decimal")
        return str(value or "")


def _availability_from_stock_quantity(evidence: Evidence) -> Evidence | None:
    if evidence.fact_type != "offer.stock_quantity":
        return None
    try:
        quantity = Decimal(str(evidence.value).strip())
    except (InvalidOperation, ValueError):
        return None
    availability = "in_stock" if quantity > 0 else "out_of_stock"
    return evidence.model_copy(
        update={
            "evidence_id": stable_id(
                "ev",
                evidence.bundle_id,
                evidence.evidence_id,
                "availability_from_stock_quantity",
                availability,
            ),
            "fact_type": "offer.availability",
            "raw_value": availability,
            "value": availability,
            "confidence": min(float(evidence.confidence), 0.85),
            "metadata": {
                **dict(evidence.metadata),
                "derived_by": "availability_from_stock_quantity",
                "input_evidence_id": evidence.evidence_id,
            },
        }
    )


def _brand_from_title_host(evidence: Evidence, *, page_url: str) -> Evidence | None:
    if evidence.fact_type != field_mappings.PRODUCT_TITLE_FACT_TYPE:
        return None
    brand = infer_brand_from_title_host(title=evidence.value, url=page_url)
    if not brand:
        return None
    return evidence.model_copy(
        update={
            "evidence_id": stable_id(
                "ev",
                evidence.bundle_id,
                evidence.evidence_id,
                "brand_from_title_host",
                brand,
            ),
            "fact_type": field_mappings.PRODUCT_BRAND_FACT_TYPE,
            "raw_value": brand,
            "value": brand,
            "confidence": min(float(evidence.confidence), 0.78),
            "metadata": {
                **dict(evidence.metadata),
                "derived_by": "brand_from_title_host",
                "input_evidence_id": evidence.evidence_id,
            },
        }
    )


def _brand_from_product_url(evidence: Evidence, *, page_url: str) -> Evidence | None:
    if evidence.fact_type != field_mappings.PRODUCT_TITLE_FACT_TYPE:
        return None
    if not (brand := infer_brand_from_product_url(url=page_url, title=evidence.value)):
        return None
    return evidence.model_copy(
        update={
            "evidence_id": stable_id(
                "ev",
                evidence.bundle_id,
                evidence.evidence_id,
                "brand_from_product_url",
                brand,
            ),
            "fact_type": field_mappings.PRODUCT_BRAND_FACT_TYPE,
            "raw_value": brand,
            "value": brand,
            "confidence": min(float(evidence.confidence), 0.74),
            "directness": "inferred",
            "metadata": {
                **dict(evidence.metadata),
                "derived_by": "brand_from_product_url",
                "input_evidence_id": evidence.evidence_id,
            },
        }
    )


def _brand_from_title_marker(evidence: Evidence) -> Evidence | None:
    if evidence.fact_type != field_mappings.PRODUCT_TITLE_FACT_TYPE:
        return None
    brand = infer_brand_from_title_marker(evidence.value)
    if not brand:
        return None
    return evidence.model_copy(
        update={
            "evidence_id": stable_id(
                "ev",
                evidence.bundle_id,
                evidence.evidence_id,
                "brand_from_title_marker",
                brand,
            ),
            "fact_type": field_mappings.PRODUCT_BRAND_FACT_TYPE,
            "raw_value": brand,
            "value": brand,
            "confidence": min(float(evidence.confidence), 0.8),
            "metadata": {
                **dict(evidence.metadata),
                "derived_by": "brand_from_title_marker",
                "input_evidence_id": evidence.evidence_id,
            },
        }
    )


def _currency_from_price_symbol(evidence: Evidence) -> Evidence | None:
    if evidence.fact_type != field_mappings.OFFER_PRICE_FACT_TYPE or not isinstance(
        evidence.raw_value, str
    ):
        return None
    currencies = {
        str(currency)
        for symbol, currency in CURRENCY_SYMBOL_MAP.items()
        if str(symbol) in evidence.raw_value
    }
    if len(currencies) != 1:
        return None
    currency = currencies.pop()
    return evidence.model_copy(
        update={
            "evidence_id": stable_id(
                "ev",
                evidence.bundle_id,
                evidence.evidence_id,
                "currency_from_price_symbol",
                currency,
            ),
            "fact_type": field_mappings.OFFER_CURRENCY_FACT_TYPE,
            "raw_value": currency,
            "value": currency,
            "confidence": min(float(evidence.confidence), 0.85),
            "metadata": {
                **dict(evidence.metadata),
                "derived_by": "currency_from_price_symbol",
                "input_evidence_id": evidence.evidence_id,
            },
        }
    )


def _dedupe_equivalent(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    seen: set[tuple[object, ...]] = set()
    out: list[Evidence] = []
    for ev in evidence:
        hint = ev.entity_hint.model_dump(mode="json") if ev.entity_hint else None
        key = (
            ev.fact_type,
            _freeze(ev.value),
            ev.collector_id,
            ev.directness,
            str(hint),
            ev.locator.kind,
            ev.locator.value,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return tuple(out)


def _freeze(value: Any) -> object:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)
