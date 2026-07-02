from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.acquisition.acquirer import PageEvidence
from app.core.config.extraction_recipes import (
    ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID,
    ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID,
)

from app.extraction.contracts import (
    ArtifactRef,
    CaptureBundle,
    ExecutionManifestContext,
    ExtractionRequest,
    RequestContext,
)
from app.core.records.field_policy import normalize_field_key
from app.extraction.documents import DocumentStore, HtmlDocument
from app.core.shared.ids import content_sha256, stable_id
from app.extraction.surfaces import Surface


class MemoryArtifactReader:
    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        html_documents: dict[str, HtmlDocument] | None = None,
    ):
        self._payloads = payloads
        self.document_store = DocumentStore(
            payloads,
            html_documents=html_documents,
        )

    def read_text(self, artifact: ArtifactRef) -> str:
        return str(self._payloads.get(artifact.artifact_id) or "")

    def read_json(self, artifact: ArtifactRef) -> Any:
        return self._payloads.get(artifact.artifact_id)

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self._payloads


def fixture_bundle_from_inputs(
    html: str,
    page_url: str,
    requested_url: str | None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    html_document: HtmlDocument | None = None,
) -> tuple[CaptureBundle, MemoryArtifactReader]:
    payloads: dict[str, Any] = {"html": html}
    refs = [
        ArtifactRef(
            artifact_id="html",
            artifact_type="rendered_html",
            content_sha256=content_sha256(html),
            storage_uri="memory://html",
            media_type="text/html",
        )
    ]
    js_state = (artifacts or {}).get("js_state_objects")
    if isinstance(js_state, dict):
        payloads["js_state"] = js_state
        refs.append(
            ArtifactRef(
                artifact_id="js_state",
                artifact_type="js_state",
                content_sha256=content_sha256(
                    json.dumps(js_state, sort_keys=True, default=str)
                ),
                storage_uri="memory://js_state",
                media_type="application/json",
            )
        )
    for index, payload in enumerate(network_payloads or []):
        artifact_id = f"network_{index}"
        body = payload.get("body") if isinstance(payload, dict) else payload
        payloads[artifact_id] = body
        refs.append(
            ArtifactRef(
                artifact_id=artifact_id,
                artifact_type="network_json",
                content_sha256=content_sha256(
                    json.dumps(body, sort_keys=True, default=str)
                ),
                storage_uri=f"memory://{artifact_id}",
                media_type="application/json",
            )
        )
    adapter_value = (artifacts or {}).get("adapter_artifacts")
    adapter_artifacts = list(adapter_value) if isinstance(adapter_value, list) else []
    if adapter_artifacts:
        payloads["adapter_artifacts"] = adapter_artifacts
    for index, artifact in enumerate(adapter_artifacts):
        if not isinstance(artifact, dict):
            continue
        artifact_id = f"adapter_{index}"
        body = artifact.get("body", artifact)
        payloads[artifact_id] = body
        refs.append(
            ArtifactRef(
                artifact_id=artifact_id,
                artifact_type="network_json",
                content_sha256=content_sha256(
                    json.dumps(body, sort_keys=True, default=str)
                ),
                storage_uri=f"memory://{artifact_id}",
                media_type="application/json",
            )
        )
    css_value = (artifacts or {}).get("css_field_rules")
    css_rows = css_value if isinstance(css_value, list) else []
    css_rules = [dict(row) for row in css_rows if isinstance(row, dict)]
    if css_rules:
        payloads["css_field_rules"] = css_rules
        refs.append(
            ArtifactRef(
                artifact_id="css_field_rules",
                artifact_type="css_recipe",
                content_sha256=content_sha256(
                    json.dumps(css_rules, sort_keys=True, default=str)
                ),
                storage_uri="memory://css_field_rules",
                media_type="application/json",
            )
        )
    listing_artifacts = artifacts or {}
    fragments = listing_artifacts.get(ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID)
    fragment_values = (
        [str(value).strip() for value in fragments if str(value or "").strip()]
        if isinstance(fragments, list)
        else []
    )
    visual_html = str(
        listing_artifacts.get(ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID) or ""
    ).strip()
    for artifact_id, artifact_html in (
        (
            ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID,
            f"<main>{''.join(fragment_values)}</main>" if fragment_values else "",
        ),
        (ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID, visual_html),
    ):
        if artifact_html:
            payloads[artifact_id] = artifact_html
            refs.append(
                ArtifactRef(
                    artifact_id=artifact_id,
                    artifact_type="rendered_html",
                    content_sha256=content_sha256(artifact_html),
                    storage_uri=f"memory://{artifact_id}",
                    media_type="text/html",
                )
            )
    bundle = CaptureBundle(
        schema_version="capture.v1",
        bundle_id=stable_id("bundle", requested_url or page_url, page_url, html[:80]),
        run_id=0,
        requested_url=requested_url or page_url,
        final_url=page_url,
        request_context=RequestContext(
            context_id=stable_id("ctx", requested_url or page_url)
        ),
        artifacts=tuple(refs),
        acquisition_outcome="ok",
    )
    return bundle, MemoryArtifactReader(
        payloads,
        html_documents={"html": html_document} if html_document is not None else None,
    )


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
    runtime_snapshot: dict[str, object] | None = None,
) -> ExtractionRequest:
    html = str(getattr(acquisition_result, "html", "") or "")
    final_url = str(getattr(acquisition_result, "final_url", "") or requested_url)
    run_id = int(
        getattr(getattr(acquisition_result, "request", None), "run_id", 0) or 0
    )
    network_payloads = list(getattr(acquisition_result, "network_payloads", []) or [])
    artifacts = dict(getattr(acquisition_result, "artifacts", {}) or {})
    html_document = getattr(acquisition_result, "html_document", None)
    if selector_rules:
        artifacts["css_field_rules"] = list(selector_rules)
    blocked = PageEvidence.from_acquisition_result(acquisition_result).indicates_block
    raw_acquisition_diagnostics = getattr(
        acquisition_result, "acquisition_diagnostics", {}
    )
    bundle, reader = _bundle_from_runtime_inputs(
        html,
        final_url,
        requested_url,
        run_id=run_id,
        status_code=getattr(acquisition_result, "status_code", None),
        method=str(getattr(acquisition_result, "method", "") or ""),
        blocked=blocked,
        network_payloads=network_payloads,
        artifacts=artifacts,
        acquisition_diagnostics=(
            dict(raw_acquisition_diagnostics)
            if isinstance(raw_acquisition_diagnostics, Mapping)
            else {}
        ),
        html_document=html_document
        if isinstance(html_document, HtmlDocument)
        else None,
    )
    return ExtractionRequest(
        surface=surface,
        capture=bundle,
        artifact_reader=reader,
        requested_fields=requested_fields,
        max_records=max_records,
        runtime_snapshot=runtime_snapshot or {},
        user_controlled_fields=_selector_controlled_fields(selector_rules),
        manifest_context=_manifest_context(runtime_snapshot or {}),
    )


def _selector_controlled_fields(
    selector_rules: list[dict[str, object]] | None,
) -> tuple[str, ...]:
    fields: set[str] = set()
    for row in selector_rules or []:
        if not isinstance(row, dict) or not bool(row.get("is_active", True)):
            continue
        if not str(row.get("css_selector") or "").strip():
            continue
        field = normalize_field_key(str(row.get("field_name") or ""))
        if field:
            fields.add(field)
    return tuple(sorted(fields))


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
    acquisition_diagnostics: dict[str, object] | None = None,
    html_document: HtmlDocument | None = None,
) -> tuple[CaptureBundle, MemoryArtifactReader]:
    bundle, reader = fixture_bundle_from_inputs(
        html,
        page_url,
        requested_url,
        network_payloads=network_payloads,
        artifacts=artifacts,
        html_document=html_document,
    )
    refs = tuple(
        ref.model_copy(
            update={
                "storage_uri": ref.storage_uri.replace("memory://", "acquisition://", 1)
            }
        )
        for ref in bundle.artifacts
    )
    outcome = (
        "blocked" if blocked else "error" if _is_error_status(status_code) else "ok"
    )
    return (
        bundle.model_copy(
            update={
                "bundle_id": stable_id("bundle", run_id, requested_url, page_url),
                "run_id": run_id,
                "http_status": int(status_code)
                if isinstance(status_code, int)
                else None,
                "acquisition_method": method or None,
                "artifacts": refs,
                "acquisition_outcome": outcome,
                "browser_attempted": method == "browser",
                "blocked": blocked,
                "acquisition_diagnostics": dict(acquisition_diagnostics or {}),
            }
        ),
        reader,
    )


def _is_error_status(status_code: object) -> bool:
    return isinstance(status_code, int) and status_code >= 500


def _manifest_context(snapshot: dict[str, object]) -> ExecutionManifestContext:
    return ExecutionManifestContext(
        release_snapshot_id=_optional_text(snapshot.get("_release_snapshot_id")),
        execution_manifest_id=_optional_text(snapshot.get("_execution_manifest_id")),
        template_id=_optional_text(snapshot.get("_template_id")),
        manifest_version=_optional_text(snapshot.get("_manifest_version")),
        locale_policy_ref=_optional_text(snapshot.get("_locale_policy_ref")),
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
