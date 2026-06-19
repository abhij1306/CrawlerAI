from __future__ import annotations

from app.services.extraction.contracts import ExtractionRequest, ExtractionResult
from app.services.extraction.jobs import extract_job_detail, extract_job_listing
from app.services.extraction.listing import extract_ecommerce_listing
from app.services.extraction.pipeline import extract_ecommerce_detail
from app.services.extraction.surfaces import Surface


def extract(request: ExtractionRequest) -> ExtractionResult:
    html = str(request.artifact_payloads.get("html") or "")
    page_url = request.capture.final_url
    requested_url = request.capture.requested_url
    if request.surface == Surface.ECOMMERCE_DETAIL:
        artifact_payloads = dict(request.artifact_payloads)
        if "js_state" in artifact_payloads and "js_state_objects" not in artifact_payloads:
            artifact_payloads["js_state_objects"] = artifact_payloads["js_state"]
        record, replay = extract_ecommerce_detail(
            html,
            page_url,
            requested_page_url=requested_url,
            network_payloads=_network_payloads(request),
            artifacts=artifact_payloads,
        )
        records = (record,) if isinstance(record, dict) else ()
        return ExtractionResult(
            surface=request.surface,
            records=records,
            evidence=replay.normalized_evidence,
            findings=replay.findings,
            decisions=replay.resolution.decisions,
            verdict=replay.verdict,
            replay=_detail_replay_payload(replay),
        )
    if request.surface == Surface.ECOMMERCE_LISTING:
        return extract_ecommerce_listing(
            html,
            page_url,
            requested_page_url=requested_url,
            max_records=request.max_records,
        )
    if request.surface == Surface.JOB_DETAIL:
        return extract_job_detail(
            html,
            page_url,
            requested_page_url=requested_url,
        )
    if request.surface == Surface.JOB_LISTING:
        return extract_job_listing(
            html,
            page_url,
            requested_page_url=requested_url,
            max_records=request.max_records,
        )
    return ExtractionResult(surface=request.surface, records=(), verdict="empty")


def _network_payloads(request: ExtractionRequest) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for artifact in request.capture.artifacts:
        if artifact.artifact_type != "network_json" or not artifact.artifact_id.startswith("network_"):
            continue
        rows.append({"body": request.artifact_payloads.get(artifact.artifact_id)})
    return rows


def _detail_replay_payload(replay) -> dict[str, object]:
    payload = replay.model_dump(mode="json")
    payload["surface"] = Surface.ECOMMERCE_DETAIL.value
    payload["evidence"] = list(payload.get("normalized_evidence") or payload.get("evidence") or [])
    payload["findings"] = list(payload.get("findings") or [])
    payload["decisions"] = list((payload.get("resolution") or {}).get("decisions") or [])
    payload["records"] = [payload.get("record") or {}] if payload.get("record") else []
    return payload
