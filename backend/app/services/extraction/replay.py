from __future__ import annotations

import json
from typing import Any

from app.services.extraction.contracts import (
    ArtifactRef,
    CaptureBundle,
    ExtractionRequest,
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

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self._payloads


def fixture_bundle_from_inputs(html: str, page_url: str, requested_url: str | None, network_payloads: list[dict[str, object]] | None = None, artifacts: dict[str, object] | None = None) -> tuple[CaptureBundle, MemoryArtifactReader]:
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


def fixture_request_from_inputs(
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
    bundle, reader = fixture_bundle_from_inputs(
        html,
        page_url,
        requested_url,
        network_payloads=network_payloads,
        artifacts=artifacts,
    )
    return ExtractionRequest(
        surface=surface,
        capture=bundle,
        artifact_reader=reader,
        requested_fields=requested_fields,
        max_records=max_records,
    )


def request_from_acquisition_result(
    surface: Surface,
    acquisition_result: Any,
    *,
    requested_url: str,
    max_records: int,
    requested_fields: tuple[str, ...] = (),
    selector_rules: list[dict[str, object]] | None = None,
) -> ExtractionRequest:
    html = str(getattr(acquisition_result, "html", "") or "")
    final_url = str(getattr(acquisition_result, "final_url", "") or requested_url)
    run_id = int(getattr(getattr(acquisition_result, "request", None), "run_id", 0) or 0)
    network_payloads = list(getattr(acquisition_result, "network_payloads", []) or [])
    artifacts = dict(getattr(acquisition_result, "artifacts", {}) or {})
    if selector_rules:
        artifacts["css_field_rules"] = list(selector_rules)
    bundle, reader = _bundle_from_runtime_inputs(
        html,
        final_url,
        requested_url,
        run_id=run_id,
        status_code=getattr(acquisition_result, "status_code", None),
        method=str(getattr(acquisition_result, "method", "") or ""),
        blocked=bool(getattr(acquisition_result, "blocked", False)),
        network_payloads=network_payloads,
        artifacts=artifacts,
    )
    return ExtractionRequest(
        surface=surface,
        capture=bundle,
        artifact_reader=reader,
        requested_fields=requested_fields,
        max_records=max_records,
    )


def _bundle_from_runtime_inputs(
    html: str,
    page_url: str,
    requested_url: str,
    *,
    run_id: int,
    status_code: object,
    method: str,
    blocked: bool,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
) -> tuple[CaptureBundle, MemoryArtifactReader]:
    bundle, reader = fixture_bundle_from_inputs(
        html,
        page_url,
        requested_url,
        network_payloads=network_payloads,
        artifacts=artifacts,
    )
    refs = tuple(
        ref.model_copy(
            update={
                "storage_uri": ref.storage_uri.replace("memory://", "acquisition://", 1)
            }
        )
        for ref in bundle.artifacts
    )
    outcome = "blocked" if blocked else "error" if _is_error_status(status_code) else "ok"
    return (
        bundle.model_copy(
            update={
                "bundle_id": stable_id("bundle", run_id, requested_url, page_url),
                "run_id": run_id,
                "http_status": int(status_code) if isinstance(status_code, int) else None,
                "acquisition_method": method or None,
                "artifacts": refs,
                "acquisition_outcome": outcome,
                "browser_attempted": method == "browser",
                "blocked": blocked,
            }
        ),
        reader,
    )


def _is_error_status(status_code: object) -> bool:
    return isinstance(status_code, int) and status_code >= 500
