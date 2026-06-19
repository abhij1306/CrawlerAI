from __future__ import annotations

import json
from typing import Any

from app.services.extraction.contracts import (
    ArtifactRef,
    CaptureBundle,
    ExtractionRequest,
    ReplayArtifact,
    RequestContext,
)
from app.services.extraction.documents import DocumentStore
from app.services.extraction.ids import content_sha256, stable_id
from app.services.extraction.surfaces import Surface


class MemoryArtifactReader:
    def __init__(self, payloads: dict[str, Any]):
        self._payloads = payloads
        self.document_store = DocumentStore(payloads)

    def read_text(self, artifact: ArtifactRef) -> str:
        return str(self._payloads.get(artifact.artifact_id) or "")

    def read_json(self, artifact: ArtifactRef) -> Any:
        return self._payloads.get(artifact.artifact_id)


def bundle_from_inputs(html: str, page_url: str, requested_url: str | None, network_payloads: list[dict[str, object]] | None = None, artifacts: dict[str, object] | None = None) -> tuple[CaptureBundle, MemoryArtifactReader]:
    payloads: dict[str, Any] = {"html": html}
    refs = [ArtifactRef(artifact_id="html", artifact_type="rendered_html", content_sha256=content_sha256(html), storage_uri="memory://html", media_type="text/html")]
    js_state = (artifacts or {}).get("js_state_objects")
    if isinstance(js_state, dict):
        payloads["js_state"] = js_state
        refs.append(ArtifactRef(artifact_id="js_state", artifact_type="js_state", content_sha256=content_sha256(json.dumps(js_state, sort_keys=True, default=str)), storage_uri="memory://js_state", media_type="application/json"))
    for index, payload in enumerate(network_payloads or []):
        artifact_id = f"network_{index}"
        body = payload.get("body") if isinstance(payload, dict) else payload
        payloads[artifact_id] = body
        refs.append(ArtifactRef(artifact_id=artifact_id, artifact_type="network_json", content_sha256=content_sha256(json.dumps(body, sort_keys=True, default=str)), storage_uri=f"memory://{artifact_id}", media_type="application/json"))
    adapter_artifacts = list((artifacts or {}).get("adapter_artifacts") or [])
    if adapter_artifacts:
        payloads["adapter_artifacts"] = adapter_artifacts
    for index, artifact in enumerate(adapter_artifacts):
        if not isinstance(artifact, dict):
            continue
        artifact_id = f"adapter_{index}"
        body = artifact.get("body", artifact)
        payloads[artifact_id] = body
        refs.append(ArtifactRef(artifact_id=artifact_id, artifact_type="network_json", content_sha256=content_sha256(json.dumps(body, sort_keys=True, default=str)), storage_uri=f"memory://{artifact_id}", media_type="application/json"))
    css_rules = [
        dict(row)
        for row in list((artifacts or {}).get("css_field_rules") or [])
        if isinstance(row, dict)
    ]
    if css_rules:
        payloads["css_field_rules"] = css_rules
        refs.append(ArtifactRef(artifact_id="css_field_rules", artifact_type="css_recipe", content_sha256=content_sha256(json.dumps(css_rules, sort_keys=True, default=str)), storage_uri="memory://css_field_rules", media_type="application/json"))
    bundle = CaptureBundle(schema_version="capture.v1", bundle_id=stable_id("bundle", requested_url or page_url, page_url, html[:80]), run_id=0, requested_url=requested_url or page_url, final_url=page_url, request_context=RequestContext(context_id=stable_id("ctx", requested_url or page_url)), artifacts=tuple(refs), acquisition_outcome="ok")
    return bundle, MemoryArtifactReader(payloads)


def request_from_inputs(
    surface: Surface,
    html: str,
    page_url: str,
    *,
    requested_url: str | None = None,
    max_records: int = 1,
    requested_fields: tuple[str, ...] = (),
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
) -> ExtractionRequest:
    bundle, reader = bundle_from_inputs(
        html,
        page_url,
        requested_url,
        network_payloads=network_payloads,
        artifacts=artifacts,
    )
    return ExtractionRequest(
        surface=surface,
        capture=bundle,
        artifact_payloads=dict(reader._payloads),
        requested_fields=requested_fields,
        max_records=max_records,
    )


def to_jsonable(artifact: ReplayArtifact) -> dict[str, Any]:
    return artifact.model_dump(mode="json")
