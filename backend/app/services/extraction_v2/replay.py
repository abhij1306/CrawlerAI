from __future__ import annotations

import json
from typing import Any

from app.services.extraction_v2.contracts import ArtifactRef, CaptureBundle, ReplayArtifact, RequestContext
from app.services.extraction_v2.ids import content_sha256, stable_id


class MemoryArtifactReader:
    def __init__(self, payloads: dict[str, Any]):
        self._payloads = payloads

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
    bundle = CaptureBundle(schema_version="capture.v1", bundle_id=stable_id("bundle", requested_url or page_url, page_url, html[:80]), run_id=0, requested_url=requested_url or page_url, final_url=page_url, request_context=RequestContext(context_id=stable_id("ctx", requested_url or page_url)), artifacts=tuple(refs), acquisition_outcome="ok")
    return bundle, MemoryArtifactReader(payloads)


def to_jsonable(artifact: ReplayArtifact) -> dict[str, Any]:
    return artifact.model_dump(mode="json")
