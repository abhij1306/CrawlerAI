from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from urllib.parse import urljoin

from app.services.extraction.collectors._helpers import evidence as make_evidence
from app.services.extraction.collectors import default_collectors
from app.services.extraction.contracts import EntityHint, Evidence, FACT_TYPES, ReplayArtifact, SourceLocator
from app.services.extraction.entities import build_entities
from app.services.extraction.ids import stable_id
from app.services.extraction.materialization import materialize
from app.services.extraction.quality import quality_verdict
from app.services.extraction.replay import bundle_from_inputs
from app.services.extraction.resolution import resolve
from app.services.extraction.validation import validate
from app.services.field_policy import normalize_field_key


def extract_ecommerce_detail(html: str, page_url: str, *, requested_page_url: str | None = None, network_payloads: list[dict[str, object]] | None = None, artifacts: dict[str, object] | None = None) -> tuple[dict[str, object] | None, ReplayArtifact]:
    bundle, reader = bundle_from_inputs(html, page_url, requested_page_url, network_payloads, artifacts)
    evidence = tuple(
        ev
        for collector in default_collectors()
        for ev in collector.collect(bundle, reader)
        if ev.fact_type in FACT_TYPES
    ) + tuple(_css_recipe_evidence(bundle, reader))
    normalized = _dedupe_equivalent(
        tuple(normalize_evidence(ev, page_url=page_url) for ev in evidence)
    )
    entities = build_entities(bundle, normalized)
    findings = validate(normalized, entities)
    resolution = resolve(normalized, entities, findings)
    record = materialize(entities, resolution, normalized)
    verdict = quality_verdict(record, resolution, bundle.acquisition_outcome)
    record["_quality_verdict"] = verdict
    replay = ReplayArtifact(bundle=bundle, evidence=evidence, normalized_evidence=normalized, findings=findings, resolution=resolution, record=record, verdict=verdict)
    return (record if verdict in {"success", "partial", "review"} else None), replay


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
    if evidence.fact_type in {"product.gtin", "variant.gtin"} and isinstance(value, str):
        value = re.sub(r"\D+", "", value)
        if value and len(value) not in {8, 12, 13, 14}:
            flags.add("invalid_gtin")
    if isinstance(value, str) and value.lower() in {"n/a", "none", "null", "undefined"}:
        flags.add("placeholder_text")
    return evidence.model_copy(update={"value": value, "flags": tuple(sorted(flags))})


def _money(value: Any, flags: set[str]) -> str:
    text = re.sub(r"[^0-9.,-]", "", str(value or "")).replace(",", "")
    try:
        return str(Decimal(text))
    except (InvalidOperation, ValueError):
        flags.add("invalid_decimal")
        return str(value or "")


def _dedupe_equivalent(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    seen: set[tuple[object, ...]] = set()
    out: list[Evidence] = []
    for ev in evidence:
        hint = ev.entity_hint.model_dump(mode="json") if ev.entity_hint else None
        key = (ev.fact_type, _freeze(ev.value), ev.collector_id, ev.directness, str(hint))
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
    field_to_fact = {
        "title": "product.title",
        "name": "product.title",
        "brand": "product.brand",
        "description": "product.description",
        "category": "product.category",
        "sku": "product.sku",
        "mpn": "product.mpn",
        "gtin": "product.gtin",
        "price": "offer.price",
        "currency": "offer.currency",
        "original_price": "offer.original_price",
        "availability": "offer.availability",
        "image": "asset.image_url",
        "image_url": "asset.image_url",
        "url": "product.url",
    }
    for row in rules:
        if not isinstance(row, dict) or not bool(row.get("is_active", True)):
            continue
        selector = str(row.get("css_selector") or "").strip()
        fact_type = field_to_fact.get(normalize_field_key(str(row.get("field_name") or "")))
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
            parent_subject_id = None
            group_id = "product"
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
