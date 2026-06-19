from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.services.extraction.documents import DocumentStore, HtmlDocument
from app.services.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    Evidence,
    SourceLocator,
)
from app.services.extraction.ids import stable_id


def first_artifact(bundle: CaptureBundle, artifact_type: str):
    return next((item for item in bundle.artifacts if item.artifact_type == artifact_type), None)


def html_doc(bundle: CaptureBundle, reader) -> tuple[str, HtmlDocument]:
    artifact = first_artifact(bundle, "rendered_html") or first_artifact(bundle, "http_html")
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
    eid = stable_id("ev", bundle.bundle_id, artifact_id, collector_id, fact_type, value, locator.value, group_id)
    subject_id = str(kwargs.get("subject_id") or _subject_id(bundle, fact_type, value, group_id, hint))
    parent_subject_id = kwargs.get("parent_subject_id")
    return Evidence(
        evidence_id=eid,
        bundle_id=bundle.bundle_id,
        artifact_id=artifact_id,
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=locator,
        entity_hint=hint,
        group_id=group_id,
        directness=directness,  # type: ignore[arg-type]
        confidence=confidence,
        subject_id=subject_id,
        parent_subject_id=str(parent_subject_id) if parent_subject_id else None,
    )


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
        return stable_id("subject", bundle.bundle_id, "variant", group_id or hint.variant_id or product_key)
    if hint is not None and hint.entity_type == "offer":
        return stable_id("subject", bundle.bundle_id, "offer", group_id or product_key)
    if hint is not None and hint.entity_type == "asset":
        return stable_id("subject", bundle.bundle_id, "asset", group_id or value)
    if hint is not None and hint.entity_type == "job":
        return stable_id("subject", bundle.bundle_id, "job", product_key)
    if fact_type.startswith("variant."):
        return stable_id("subject", bundle.bundle_id, "variant", group_id or product_key)
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
