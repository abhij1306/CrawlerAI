from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from urllib.parse import urljoin

from app.extraction.collectors._helpers import evidence as make_evidence
from app.extraction.collectors.dom import DomCollector, collect_requested_fields
from app.extraction.collectors.jsonld import JsonLdCollector
from app.extraction.collectors.js_state import JsStateCollector
from app.extraction.collectors.metadata import MicrodataCollector, NetworkCollector, OpenGraphCollector
from app.extraction.collectors.url import UrlCollector
from app.core.config.field_mappings import ECOMMERCE_DETAIL_FIELD_FACT_TYPES
from app.core.config.extraction_rules import (
    AVAILABILITY_URL_MAP,
    CURRENCY_SYMBOL_MAP,
    NORMALIZER_AVAILABILITY_TOKENS,
)
from app.extraction.contracts import ArtifactReader, CaptureBundle, EntityHint, Evidence, FACT_TYPES, SourceLocator
from app.extraction.contracts import CommerceDetailRecord
from app.extraction.ids import stable_id
from app.extraction.materialization import materialize
from app.core.records.field_policy import normalize_field_key
from app.core.records.url_identity import detail_title_from_url


def collect_ecommerce_detail(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Evidence, ...]:
    return tuple(
        ev
        for collector in default_collectors()
        for ev in collector.collect(bundle, reader)
        if ev.fact_type in FACT_TYPES
    ) + tuple(_css_recipe_evidence(bundle, reader)) + collect_requested_fields(
        bundle,
        reader,
        requested_fields,
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
    evidence: tuple[Evidence, ...],
    *,
    page_url: str,
) -> tuple[Evidence, ...]:
    normalized = tuple(normalize_evidence(ev, page_url=page_url) for ev in evidence)
    return _dedupe_equivalent(
        normalized + tuple(
            derived
            for ev in normalized
            for derived in (_currency_from_price_symbol(ev),)
            if derived is not None
        )
    )


def materialize_ecommerce_detail(
    entities,
    resolution,
    evidence: tuple[Evidence, ...],
    *,
    canonical_url: str,
) -> CommerceDetailRecord:
    return materialize(entities, resolution, evidence, canonical_url=canonical_url)


def assess_ecommerce_detail_quality(
    record: dict[str, object],
    resolution,
    bundle: CaptureBundle,
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
    if (
        record.get("url")
        and record.get("title")
        and _has_complete_public_offer(record)
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
    if any(record.get(field) not in (None, "", [], {}, ()) for field in commerce_fields):
        return False
    return title.casefold() == detail_title_from_url(url).casefold()


def _has_complete_public_offer(record: dict[str, object]) -> bool:
    if record.get("price") not in (None, "", [], {}, ()) and record.get("currency") not in (
        None,
        "",
        [],
        {},
        (),
    ):
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


def normalize_evidence(evidence: Evidence, *, page_url: str) -> Evidence:
    value = evidence.value
    flags = set(evidence.flags)
    if isinstance(value, str):
        value = re.sub(r"\s+", " ", value).strip()
    if evidence.fact_type in {"product.url", "variant.url", "asset.image_url"} and isinstance(value, str):
        value = urljoin(page_url, value)
    if evidence.fact_type == "offer.currency" and isinstance(value, str):
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            flags.add("invalid_currency")
    if evidence.fact_type in {"offer.price", "offer.original_price"}:
        value = _money(value, flags)
    if evidence.fact_type == "offer.availability" and isinstance(value, str):
        value = _availability(value)
    if evidence.fact_type in {"product.gtin", "variant.gtin"} and isinstance(value, str):
        value = re.sub(r"\D+", "", value)
        if value and len(value) not in {8, 12, 13, 14}:
            flags.add("invalid_gtin")
    if isinstance(value, str) and value.lower() in {"n/a", "none", "null", "undefined"}:
        flags.add("placeholder_text")
    return evidence.model_copy(update={"value": value, "flags": tuple(sorted(flags))})


def _availability(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    key = text.casefold()
    mapped = AVAILABILITY_URL_MAP.get(key)
    if mapped:
        return mapped
    normalized = re.sub(r"[^a-z0-9]+", " ", key).strip()
    for public_value, tokens in NORMALIZER_AVAILABILITY_TOKENS.items():
        if normalized in {re.sub(r"[^a-z0-9]+", " ", token).strip() for token in tokens}:
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
    rules = reader.read_json(next((ref for ref in bundle.artifacts if ref.artifact_id == "css_field_rules"), None)) if any(ref.artifact_id == "css_field_rules" for ref in bundle.artifacts) else []
    if not isinstance(rules, list):
        return ()
    doc = reader.document_store.html("html")
    product_subject_id = stable_id("subject", bundle.bundle_id, "product", bundle.final_url)
    rows: list[Evidence] = []
    for row in rules:
        if not isinstance(row, dict) or not bool(row.get("is_active", True)):
            continue
        selector = str(row.get("css_selector") or "").strip()
        fact_type = ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(
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
                subject_id = stable_id("subject", bundle.bundle_id, "offer", bundle.final_url)
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
                        kind="css_selector",
                        value=selector,
                        preview=str(value)[:120],
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
