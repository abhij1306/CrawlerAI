"""Declared artifact reads shared by recipe compilation and execution."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import variant_policy
from app.core.config.extraction_rules import DETAIL_JSONLD_STRUCTURED_ATTRIBUTES
from app.core.records.html_helpers import embedded_state_payloads
from app.core.records.structured_variant_state import expand_embedded_state_payload
from app.extraction.contracts import ExtractionRequest


def read_recipe_json_artifact(
    request: ExtractionRequest, artifact_id: str | None
) -> Any:
    value = str(artifact_id or "")
    artifact = next(
        (row for row in request.capture.artifacts if row.artifact_id == value), None
    )
    if artifact is not None:
        if artifact.artifact_type in {"rendered_html", "http_html"}:
            return _embedded_script_payload(request, artifact.artifact_id)
        return request.artifact_reader.read_json(artifact)
    if not value.startswith("jsonld:"):
        return None
    if value.startswith("jsonld:attr:"):
        return _structured_attribute_payload(request, value)
    try:
        index = int(value.partition(":")[2])
    except ValueError:
        return None
    html_artifact = next(
        (
            row
            for row in request.capture.artifacts
            if row.artifact_type in {"rendered_html", "http_html"}
        ),
        None,
    )
    if html_artifact is None:
        return None
    nodes = request.artifact_reader.document_store.html(
        html_artifact.artifact_id
    ).safe_css("script[type='application/ld+json']")
    if index < 0 or index >= len(nodes):
        return None
    try:
        return json.loads(nodes[index].text())
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _structured_attribute_payload(
    request: ExtractionRequest, artifact_id: str
) -> object | None:
    try:
        index = int(artifact_id.rsplit(":", 1)[-1])
    except ValueError:
        return None
    html_artifact = next(
        (
            row
            for row in request.capture.artifacts
            if row.artifact_type in {"rendered_html", "http_html"}
        ),
        None,
    )
    if html_artifact is None:
        return None
    document = request.artifact_reader.document_store.html(html_artifact.artifact_id)
    values = [
        value
        for attribute in DETAIL_JSONLD_STRUCTURED_ATTRIBUTES
        for node in document.safe_css(f"[{attribute}]")
        if (value := node.attribute(attribute))
    ]
    if index < 0 or index >= len(values):
        return None
    try:
        return json.loads(values[index])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _embedded_script_payload(
    request: ExtractionRequest, artifact_id: str
) -> dict[str, object]:
    document = request.artifact_reader.document_store.html(artifact_id)
    payload: dict[str, object] = {}
    rows = embedded_state_payloads(
        document,
        selector=variant_policy.EMBEDDED_STATE_SCRIPT_SELECTOR,
        global_keys=variant_policy.EMBEDDED_STATE_GLOBAL_KEYS,
        json_call_keys=variant_policy.EMBEDDED_STATE_JSON_CALL_KEYS,
        max_scripts=variant_policy.EMBEDDED_STATE_MAX_SCRIPTS,
        max_script_chars=variant_policy.EMBEDDED_STATE_MAX_SCRIPT_CHARS,
    )
    for root_path, value in rows:
        for expanded_path, expanded in expand_embedded_state_payload(root_path, value):
            _set_pointer(payload, expanded_path, expanded)
    return payload


def _set_pointer(root: dict[str, object], pointer: str, value: object) -> None:
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer.split("/")
        if part
    ]
    current = root
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    if parts:
        current[parts[-1]] = value
