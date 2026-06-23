from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.extraction.collectors._helpers import evidence as make_evidence
from app.extraction.collectors.dom import DomCollector, collect_requested_fields
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
    DETAIL_DESCRIPTION_PROMOTIONAL_PATTERNS,
    DETAIL_DESCRIPTION_UI_PATTERNS,
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_SHELL_TITLE_KEYS,
    DETAIL_TITLE_CODE_ONLY_PATTERN,
    DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN,
    DETAIL_TITLE_GENERIC_CATEGORY_VALUES,
    DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN,
    DETAIL_TITLE_MEASUREMENT_FLAG,
    DETAIL_TITLE_MEASUREMENT_PATTERN,
    DETAIL_TITLE_PATH_EXTENSION_PATTERN,
    DETAIL_TITLE_REJECT_SUFFIXES,
    DETAIL_TITLE_REJECT_VALUES,
    DETAIL_TITLE_SEO_POLLUTION_PATTERN,
    DETAIL_TITLE_SEO_PREFIXES,
    DETAIL_TITLE_SEO_PREFIX_MIN_WORDS,
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
    EntityHint,
    Evidence,
    FACT_TYPES,
    SourceLocator,
)
from app.extraction.ids import stable_id
from app.extraction.materialization import materialize
from app.core.records.field_policy import normalize_field_key
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_url_looks_like_product,
    semantic_detail_identity_tokens,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce_price import repair_price_unit
from app.core.shared.field_coerce_text import coerce_brand_text
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
        + tuple(_css_recipe_evidence(bundle, reader))
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
    normalized = _flag_variant_color_brand_conflicts(normalized)
    return _dedupe_equivalent(
        normalized
        + tuple(
            derived
            for ev in normalized
            for derived in (_currency_from_price_symbol(ev),)
            if derived is not None
        )
    )


def _flag_variant_color_brand_conflicts(
    evidence: tuple[Evidence, ...],
) -> tuple[Evidence, ...]:
    brands = {
        str(row.value).strip().casefold()
        for row in evidence
        if row.fact_type == "product.brand" and str(row.value).strip()
    }
    color_rows = tuple(
        row for row in evidence if row.fact_type == "variant.option.color"
    )
    color_subjects = {row.subject_id for row in color_rows if row.subject_id}
    color_values = {
        str(row.value).strip().casefold()
        for row in color_rows
        if str(row.value).strip()
    }
    conflicting = (
        len(color_subjects) >= 2
        and len(color_values) == 1
        and bool(color_values & brands)
    )
    if not conflicting:
        return evidence
    return tuple(
        row.model_copy(
            update={"flags": tuple(sorted({*row.flags, VARIANT_COLOR_BRAND_CONFLICT_FLAG}))}
        )
        if row.fact_type == "variant.option.color"
        and str(row.value).strip().casefold() in brands
        else row
        for row in evidence
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
            for eid in offer.fact_evidence.get("offer.currency", ())
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
        if row.fact_type in {"offer.price", "offer.original_price"}
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
            or row.fact_type not in {"offer.price", "offer.original_price"}
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
                    (other_offer := offer_by_evidence.get(other.evidence_id)) is not None
                    and other_offer.product_entity_id == offer.product_entity_id
                    and (
                        other.collector_id != row.collector_id
                        or other_offer.entity_id == offer.entity_id
                    )
                )
                or (
                    offer_by_evidence.get(other.evidence_id) is None
                    and other.collector_id
                    in DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS
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
        decision.fact_type == "product.title"
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
    if evidence.fact_type in {
        "product.url",
        "variant.url",
        "asset.image_url",
    } and isinstance(value, str):
        value = urljoin(page_url, value)
    if (
        evidence.fact_type == "product.url"
        and isinstance(value, str)
        and detail_url_looks_like_product(page_url)
        and not detail_url_looks_like_product(value)
    ):
        flags.add("non_detail_product_url")
    if evidence.fact_type == "offer.currency" and isinstance(value, str):
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            flags.add("invalid_currency")
    if evidence.fact_type in {"offer.price", "offer.original_price"}:
        value = _money(value, flags)
    if evidence.fact_type == "offer.availability":
        if isinstance(value, bool):
            value = "in_stock" if value else "out_of_stock"
        elif isinstance(value, (int, float)) and value in {0, 1}:
            value = "in_stock" if value == 1 else "out_of_stock"
        elif isinstance(value, str):
            value = _availability(value)
        else:
            flags.add(INVALID_AVAILABILITY_EVIDENCE_FLAG)
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
    if evidence.fact_type == "product.brand" and isinstance(value, str):
        value = coerce_brand_text(_normalize_brand_hierarchy(value)) or value
        parsed_brand = urlsplit(value)
        if parsed_brand.scheme.casefold() in {"http", "https"} and parsed_brand.netloc:
            flags.add("brand_url")
        if value.casefold() in DETAIL_BRAND_BOILERPLATE_VALUES:
            flags.add("brand_boilerplate")
        if re.fullmatch(DETAIL_BRAND_CATEGORY_PATTERN, value, re.IGNORECASE):
            flags.add("category_as_brand")
    if evidence.fact_type == "product.description" and isinstance(value, str):
        if len(value) in DETAIL_DESCRIPTION_HARD_BOUNDARY_LENGTHS:
            flags.add("description_hard_boundary")
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
    if evidence.fact_type in {"product.gtin", "variant.gtin"} and isinstance(
        value, str
    ):
        value = re.sub(r"\D+", "", value)
        if value and len(value) not in {8, 12, 13, 14}:
            flags.add("invalid_gtin")
    if isinstance(value, str) and value.lower() in {"n/a", "none", "null", "undefined"}:
        flags.add("placeholder_text")
    if evidence.fact_type == "product.title" and isinstance(value, str):
        flags.update(_title_flags(evidence, value=value, page_url=page_url))
    return evidence.model_copy(update={"value": value, "flags": tuple(sorted(flags))})


def _normalize_brand_hierarchy(value: str) -> str:
    parts = [part.strip() for part in value.split("/") if part.strip()]
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9&'._-]+", part) for part in parts):
        return value
    leaf = parts[-1]
    leaf_key = re.sub(r"[^a-z0-9]+", "", leaf.casefold())
    parent_keys = [
        re.sub(r"[^a-z0-9]+", "", part.casefold().removesuffix("-parent"))
        for part in parts[:-1]
    ]
    if not leaf_key or not any(leaf_key == parent or leaf_key in parent for parent in parent_keys):
        return value
    return " ".join(token.capitalize() for token in re.split(r"[-_]+", leaf) if token)


def _title_flags(evidence: Evidence, *, value: str, page_url: str) -> set[str]:
    flags: set[str] = set()
    key = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
    url_title_key = " ".join(
        re.findall(r"[a-z0-9]+", detail_title_from_url(page_url).casefold())
    )
    if evidence.collector_id == "url":
        flags.add("url_derived_title")
    if re.search(
        DETAIL_TITLE_PATH_EXTENSION_PATTERN, str(evidence.raw_value), re.IGNORECASE
    ) or re.fullmatch(
        DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN, value.strip(), re.IGNORECASE
    ):
        flags.add("filename_title")
    if re.fullmatch(DETAIL_TITLE_CODE_ONLY_PATTERN, value.strip()) or re.fullmatch(
        DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN, value.strip()
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
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if (
        0 < len(words) <= DETAIL_TITLE_STYLE_ONLY_MAX_WORDS
        and set(words) <= DETAIL_TITLE_STYLE_ONLY_TOKENS
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
    if (
        len(title_tokens) == 1
        and len(url_tokens) >= 2
        and title_tokens < url_tokens
    ):
        flags.add("truncated_title")
    if url_tokens and title_tokens:
        required_overlap = min(
            DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP,
            len(url_tokens),
            len(title_tokens),
        )
        flags.add(
            "title_url_match"
            if overlap >= required_overlap
            else "title_url_mismatch"
        )
    return flags


def _availability(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    key = text.casefold()
    mapped = AVAILABILITY_URL_MAP.get(key)
    if mapped:
        return mapped
    normalized = re.sub(r"[^a-z0-9]+", " ", key).strip()
    for public_value, tokens in NORMALIZER_AVAILABILITY_TOKENS.items():
        if normalized in {
            re.sub(r"[^a-z0-9]+", " ", token).strip() for token in tokens
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


def _currency_from_price_symbol(evidence: Evidence) -> Evidence | None:
    if evidence.fact_type != "offer.price" or not isinstance(evidence.raw_value, str):
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
            "fact_type": "offer.currency",
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


def _css_recipe_evidence(bundle, reader) -> tuple[Evidence, ...]:
    rules_ref = next(
        (ref for ref in bundle.artifacts if ref.artifact_id == "css_field_rules"), None
    )
    rules = reader.read_json(rules_ref) if rules_ref is not None else []
    if not isinstance(rules, list):
        return ()
    doc = reader.document_store.html("html")
    product_subject_id = stable_id(
        "subject", bundle.bundle_id, "product", bundle.final_url
    )
    rows: list[Evidence] = []
    for row in rules:
        if not isinstance(row, dict) or not bool(row.get("is_active", True)):
            continue
        selector = str(row.get("css_selector") or "").strip()
        fact_type = field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(
            normalize_field_key(str(row.get("field_name") or ""))
        )
        if not selector or not fact_type:
            continue
        try:
            nodes = doc.css(selector)
        except Exception:
            continue
        for node in nodes[:3]:
            if node.is_hidden():
                continue
            value = _css_node_value(node, fact_type)
            if value in (None, "", [], {}):
                continue
            hint = EntityHint(entity_type="product")
            subject_id = product_subject_id
            parent_subject_id, group_id = None, "product"
            if fact_type.startswith("offer."):
                hint = EntityHint(entity_type="offer", url=bundle.final_url)
                subject_id = stable_id(
                    "subject", bundle.bundle_id, "offer", bundle.final_url
                )
                parent_subject_id = product_subject_id
                group_id = "offer"
            elif fact_type.startswith("asset."):
                hint = EntityHint(entity_type="asset", url=bundle.final_url)
                subject_id = stable_id("subject", bundle.bundle_id, "asset", value)
                parent_subject_id = product_subject_id
                group_id = "asset"
            rows.append(
                make_evidence(
                    bundle,
                    "css_field_rules",
                    "css_recipe",
                    fact_type,
                    value,
                    SourceLocator(
                        kind="css_selector", value=selector, preview=str(value)[:120]
                    ),
                    hint=hint,
                    group_id=group_id,
                    confidence=0.86,
                    directness="direct",
                    subject_id=subject_id,
                    parent_subject_id=parent_subject_id,
                )
            )
    return tuple(rows)


def _css_node_value(node, fact_type: str) -> str | None:
    attr_order = (
        ("href", "content", "value", "title", "aria-label")
        if fact_type == "product.url"
        else ("src", "data-src", "content", "href", "alt", "title")
        if fact_type == "asset.image_url"
        else ("content", "value", "title", "aria-label")
    )
    for attr in attr_order:
        value = str(node.attribute(attr) or "").strip()
        if value:
            return value
    text = re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()
    return text or None


def _freeze(value: Any) -> object:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)
