from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.extraction.documents import DocumentStore, HtmlDocument
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    Evidence,
    SourceLocator,
)
from app.extraction.ids import stable_id


def first_artifact(bundle: CaptureBundle, artifact_type: str):
    return next(
        (item for item in bundle.artifacts if item.artifact_type == artifact_type), None
    )


def html_doc(bundle: CaptureBundle, reader) -> tuple[str, HtmlDocument]:
    artifact = first_artifact(bundle, "rendered_html") or first_artifact(
        bundle, "http_html"
    )
    html = reader.read_text(artifact) if artifact else ""
    artifact_id = artifact.artifact_id if artifact else "html"
    store = getattr(reader, "document_store", None)
    if isinstance(store, DocumentStore):
        return html, store.html(artifact_id)
    return html, DocumentStore({artifact_id: html}).html(artifact_id)


def evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    collector_id: str,
    fact_type: str,
    value: Any,
    locator: SourceLocator,
    **kwargs: Any,
) -> Evidence:
    group_id = kwargs.get("group_id")
    hint = kwargs.get("hint")
    directness = str(kwargs.get("directness") or "direct")
    confidence = float(kwargs.get("confidence", 0.7))
    canonical_value = _canonical_evidence_value(fact_type, value)
    eid = stable_id(
        "ev",
        bundle.bundle_id,
        artifact_id,
        collector_id,
        fact_type,
        canonical_value,
        locator.value,
        group_id,
    )
    subject_id = str(
        kwargs.get("subject_id")
        or _subject_id(bundle, fact_type, canonical_value, group_id, hint)
    )
    parent_subject_id = kwargs.get("parent_subject_id")
    subject_scope = str(kwargs.get("subject_scope") or _subject_scope(fact_type, hint))
    relation_type = kwargs.get("relation_type") or _relation_type(
        subject_scope,
        parent_subject_id=parent_subject_id,
        parent_scope=kwargs.get("parent_scope"),
    )
    return Evidence(
        evidence_id=eid,
        bundle_id=bundle.bundle_id,
        artifact_id=artifact_id,
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=canonical_value,
        locator=locator,
        entity_hint=hint,
        group_id=group_id,
        directness=directness,  # type: ignore[arg-type]
        confidence=confidence,
        subject_id=subject_id,
        parent_subject_id=str(parent_subject_id) if parent_subject_id else None,
        subject_scope=subject_scope,  # type: ignore[arg-type]
        relation_type=str(relation_type) if relation_type else None,  # type: ignore[arg-type]
    )


def _subject_scope(fact_type: str, hint: EntityHint | None) -> str:
    prefix = fact_type.split(".", 1)[0]
    if prefix in {"product", "variant", "offer", "asset", "job"}:
        return prefix
    if hint is not None:
        return hint.entity_type
    return "unknown"


def _relation_type(
    subject_scope: str,
    *,
    parent_subject_id: object,
    parent_scope: object,
) -> str | None:
    if not parent_subject_id:
        return None
    parent = str(parent_scope or "unknown")
    if subject_scope == "variant" and parent == "product":
        return "product_variant"
    if subject_scope == "offer":
        if parent == "variant":
            return "variant_offer"
        if parent == "product":
            return "product_offer"
        return None
    if subject_scope == "asset":
        if parent == "variant":
            return "variant_asset"
        if parent == "job":
            return "job_asset"
        if parent == "product":
            return "product_asset"
    return None


def _canonical_evidence_value(fact_type: str, value: Any) -> Any:
    if fact_type != "offer.availability":
        return value
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if isinstance(value, (int, float)):
        return "in_stock" if value > 0 else "out_of_stock"
    text = str(value or "").strip()
    token = text.casefold().rstrip("/").rsplit("/", 1)[-1]
    normalized = "".join(ch for ch in token if ch.isalnum() or ch == "_")
    mapping = {
        "instock": "in_stock",
        "in_stock": "in_stock",
        "available": "in_stock",
        "availableforsale": "in_stock",
        "true": "in_stock",
        "1": "in_stock",
        "outofstock": "out_of_stock",
        "out_of_stock": "out_of_stock",
        "soldout": "out_of_stock",
        "unavailable": "out_of_stock",
        "false": "out_of_stock",
        "0": "out_of_stock",
        "limitedavailability": "limited_stock",
        "limitedstock": "limited_stock",
        "lowstock": "limited_stock",
        "low_stock": "limited_stock",
        "preorder": "preorder",
        "pre_order": "preorder",
        "backorder": "backorder",
        "back_order": "backorder",
        "discontinued": "discontinued",
    }
    return mapping.get(normalized, text)


def _subject_id(
    bundle: CaptureBundle,
    fact_type: str,
    value: Any,
    group_id: object,
    hint: EntityHint | None,
) -> str:
    product_key = (
        getattr(hint, "product_id", None)
        or getattr(hint, "sku", None)
        or getattr(hint, "url", None)
        or bundle.final_url
        or bundle.requested_url
    )
    if hint is not None and hint.entity_type == "variant":
        return stable_id(
            "subject",
            bundle.bundle_id,
            "variant",
            group_id or hint.variant_id or product_key,
        )
    if hint is not None and hint.entity_type == "offer":
        return stable_id("subject", bundle.bundle_id, "offer", group_id or product_key)
    if hint is not None and hint.entity_type == "asset":
        return stable_id("subject", bundle.bundle_id, "asset", group_id or value)
    if hint is not None and hint.entity_type == "job":
        return stable_id("subject", bundle.bundle_id, "job", product_key)
    if fact_type.startswith("variant."):
        return stable_id(
            "subject", bundle.bundle_id, "variant", group_id or product_key
        )
    if fact_type.startswith("offer."):
        return stable_id("subject", bundle.bundle_id, "offer", group_id or product_key)
    if fact_type.startswith("asset."):
        return stable_id("subject", bundle.bundle_id, "asset", group_id or value)
    return stable_id("subject", bundle.bundle_id, "product", product_key)


def json_objects(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        yield "", value
        for key, child in value.items():
            for path, obj in json_objects(child):
                yield f"/{key}{path}", obj
    elif isinstance(value, list):
        for index, child in enumerate(value):
            for path, obj in json_objects(child):
                yield f"/{index}{path}", obj


def loads_jsonish(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def text_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or value.get("url")
    if isinstance(value, list):
        return " ".join(text_value(item) for item in value if text_value(item)).strip()
    return str(value or "").strip()
