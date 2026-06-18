from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup

from app.services.extraction_v2.contracts import (
    CaptureBundle,
    EntityHint,
    Evidence,
    SourceLocator,
)
from app.services.extraction_v2.ids import stable_id


def first_artifact(bundle: CaptureBundle, artifact_type: str):
    return next((item for item in bundle.artifacts if item.artifact_type == artifact_type), None)


def html_soup(bundle: CaptureBundle, reader) -> tuple[str, BeautifulSoup]:
    artifact = first_artifact(bundle, "rendered_html") or first_artifact(bundle, "http_html")
    html = reader.read_text(artifact) if artifact else ""
    return html, BeautifulSoup(html, "html.parser")


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
    )


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
