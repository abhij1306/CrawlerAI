from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from urllib.parse import urljoin

from app.services.extraction_v2.collectors import default_collectors
from app.services.extraction_v2.contracts import Evidence, FACT_TYPES, ReplayArtifact
from app.services.extraction_v2.entities import build_entities
from app.services.extraction_v2.materialization import materialize
from app.services.extraction_v2.quality import quality_verdict
from app.services.extraction_v2.replay import bundle_from_inputs
from app.services.extraction_v2.resolution import resolve
from app.services.extraction_v2.validation import validate


def extract_ecommerce_detail_v2(html: str, page_url: str, *, requested_page_url: str | None = None, network_payloads: list[dict[str, object]] | None = None, artifacts: dict[str, object] | None = None) -> tuple[dict[str, object] | None, ReplayArtifact]:
    bundle, reader = bundle_from_inputs(html, page_url, requested_page_url, network_payloads, artifacts)
    evidence = tuple(ev for collector in default_collectors() for ev in collector.collect(bundle, reader) if ev.fact_type in FACT_TYPES)
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


def _freeze(value: Any) -> object:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)
