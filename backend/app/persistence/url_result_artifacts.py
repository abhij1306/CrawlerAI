from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.config.extraction_recipes import ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID
from app.persistence.artifacts import ArtifactRepository
from app.persistence.contracts import (
    ArtifactManifest,
    ArtifactReference,
    AttemptArtifactSet,
    ExtractionArtifactSet,
)

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True, slots=True)
class PublishedUrlArtifacts:
    manifest: ArtifactManifest
    reference: ArtifactReference


def publish_url_result_artifacts(
    *,
    run_id: int,
    url_result_id: int,
    acquisition_result: Any,
    extraction_result: Any,
    record_count: int,
    record_provenance: Sequence[Mapping[str, object]] = (),
    root_dir: Path | None = None,
) -> PublishedUrlArtifacts:
    repository = ArtifactRepository(root_dir=root_dir or settings.artifacts_dir)
    acquisition_artifacts = _persist_acquisition_artifacts(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        acquisition_result=acquisition_result,
    )
    attempts = _persist_attempt_sets(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        acquisition_result=acquisition_result,
        acquisition_artifacts=acquisition_artifacts,
    )
    extraction_artifacts = _persist_extraction_artifacts(
        repository,
        run_id=run_id,
        url_result_id=url_result_id,
        extraction_result=extraction_result,
        record_count=record_count,
        record_provenance=record_provenance,
    )
    bundle_id = str(getattr(extraction_result, "bundle_id", "") or "").strip()
    if not bundle_id:
        bundle_id = f"run-{max(int(run_id or 0), 0)}-result-{int(url_result_id)}"
    manifest = ArtifactManifest(
        run_id=run_id,
        url_result_id=url_result_id,
        bundle_id=bundle_id,
        attempts=attempts,
        extraction=ExtractionArtifactSet(artifacts=extraction_artifacts),
    )
    reference = repository.persist_manifest(manifest)
    return PublishedUrlArtifacts(manifest=manifest, reference=reference)


def _persist_acquisition_artifacts(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    acquisition_result: Any,
) -> tuple[ArtifactReference, ...]:
    references: list[ArtifactReference] = []
    html = str(getattr(acquisition_result, "html", "") or "")
    if html:
        references.append(
            _persist_text(
                repository,
                run_id=run_id,
                url_result_id=url_result_id,
                name="page.html",
                content=html,
            )
        )

    browser_diagnostics = _mapping(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    acquisition_diagnostics = _mapping(
        getattr(acquisition_result, "acquisition_diagnostics", {})
    )
    references.append(
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name="acquisition.json",
            payload={
                "final_url": str(getattr(acquisition_result, "final_url", "") or ""),
                "method": str(getattr(acquisition_result, "method", "") or ""),
                "status_code": getattr(acquisition_result, "status_code", None),
                "content_type": str(
                    getattr(acquisition_result, "content_type", "") or ""
                ),
                "blocked": bool(getattr(acquisition_result, "blocked", False)),
                "platform_family": getattr(acquisition_result, "platform_family", None),
                "adapter_name": getattr(acquisition_result, "adapter_name", None),
                "browser_diagnostics": browser_diagnostics,
                "acquisition_diagnostics": acquisition_diagnostics,
            },
        )
    )

    json_data = getattr(acquisition_result, "json_data", None)
    if json_data is not None:
        references.append(
            _persist_json(
                repository,
                run_id=run_id,
                url_result_id=url_result_id,
                name="response.json",
                payload=json_data,
            )
        )
    network_payloads = list(getattr(acquisition_result, "network_payloads", []) or [])
    if network_payloads:
        references.append(
            _persist_json(
                repository,
                run_id=run_id,
                url_result_id=url_result_id,
                name="network.json",
                payload=network_payloads,
            )
        )

    artifacts = _mapping(getattr(acquisition_result, "artifacts", {}))
    references.extend(
        _persist_runtime_artifacts(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            artifacts=artifacts,
        )
    )
    screenshot = _screenshot_bytes(artifacts, root_dir=repository.root_dir)
    if screenshot:
        references.append(
            repository.persist_bytes(
                run_id=run_id,
                url_result_id=url_result_id,
                name="screenshot.png",
                content=screenshot,
            )
        )
    return tuple(references)


def _persist_runtime_artifacts(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    artifacts: Mapping[str, object],
) -> tuple[ArtifactReference, ...]:
    references: list[ArtifactReference] = []
    text_artifacts = {
        "traversal_composed_html": "traversal.html",
        "full_rendered_html": "rendered.html",
        ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID: "listing-visual.html",
    }
    json_artifacts = {
        "rendered_listing_fragments": "listing-fragments.json",
        "listing_visual_elements": "listing-visual-elements.json",
    }
    for key, name in text_artifacts.items():
        content = str(artifacts.get(key) or "")
        if content:
            references.append(
                _persist_text(
                    repository,
                    run_id=run_id,
                    url_result_id=url_result_id,
                    name=name,
                    content=content,
                )
            )
    for key, name in json_artifacts.items():
        payload = artifacts.get(key)
        if payload not in (None, "", [], {}):
            references.append(
                _persist_json(
                    repository,
                    run_id=run_id,
                    url_result_id=url_result_id,
                    name=name,
                    payload=payload,
                )
            )
    return tuple(references)


def _persist_attempt_sets(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    acquisition_result: Any,
    acquisition_artifacts: tuple[ArtifactReference, ...],
) -> tuple[AttemptArtifactSet, ...]:
    diagnostics = _mapping(getattr(acquisition_result, "acquisition_diagnostics", {}))
    canonical_result = _mapping(diagnostics.get("result"))
    rows = [row for row in _object_list(canonical_result.get("attempts")) if row]
    selected_attempt_id = str(canonical_result.get("selected_attempt_id") or "").strip()
    if not rows:
        attempt_id = str(getattr(acquisition_result, "method", "") or "acquisition")
        return (
            AttemptArtifactSet(
                attempt_id=attempt_id,
                artifacts=acquisition_artifacts,
            ),
        )

    attempt_ids = [
        str(row.get("attempt_id") or f"attempt-{index}")
        for index, row in enumerate(rows, start=1)
    ]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("duplicate acquisition attempt identity")
    if selected_attempt_id and selected_attempt_id not in attempt_ids:
        raise ValueError("selected acquisition attempt is absent from attempt history")

    attempts: list[AttemptArtifactSet] = []
    shared_attached = False
    for index, row in enumerate(rows, start=1):
        attempt_id = str(row.get("attempt_id") or f"attempt-{index}")
        attempt_reference = _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name=f"attempt-{index:02d}-{_safe_token(attempt_id)}.json",
            payload=row,
        )
        attach_shared = attempt_id == selected_attempt_id
        if not selected_attempt_id and index == len(rows):
            attach_shared = True
        artifacts: tuple[ArtifactReference, ...] = (attempt_reference,)
        if attach_shared:
            artifacts = (*artifacts, *acquisition_artifacts)
            shared_attached = True
        attempts.append(AttemptArtifactSet(attempt_id=attempt_id, artifacts=artifacts))
    if not shared_attached and attempts:
        last = attempts[-1]
        attempts[-1] = AttemptArtifactSet(
            attempt_id=last.attempt_id,
            artifacts=(*last.artifacts, *acquisition_artifacts),
        )
    return tuple(attempts)


def _persist_extraction_artifacts(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    extraction_result: Any,
    record_count: int,
    record_provenance: Sequence[Mapping[str, object]],
) -> tuple[ArtifactReference, ...]:
    payload = extraction_result.model_dump(mode="json", exclude_none=True)
    payload["record_count"] = int(record_count or 0)
    components = {
        "capture.json": {"bundle_id": payload.get("bundle_id")},
        "evidence.json": payload.get("evidence", []),
        "graph.json": payload.get("graph", {}),
        "target.json": payload.get("target", {}),
        "findings.json": payload.get("findings", []),
        "decisions.json": payload.get("decisions", []),
        "records.json": payload.get("records", []),
        "record-provenance.json": list(record_provenance),
        "verdict.json": {
            "verdict": payload.get("verdict"),
            "retry_request": payload.get("retry_request"),
            "metrics": payload.get("metrics", {}),
            "record_count": int(record_count or 0),
        },
        "extraction.json": payload,
    }
    return tuple(
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name=name,
            payload=component,
        )
        for name, component in components.items()
    )


def _persist_text(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    name: str,
    content: str,
) -> ArtifactReference:
    return repository.persist_bytes(
        run_id=run_id,
        url_result_id=url_result_id,
        name=name,
        content=content.encode("utf-8"),
    )


def _persist_json(
    repository: ArtifactRepository,
    *,
    run_id: int,
    url_result_id: int,
    name: str,
    payload: object,
) -> ArtifactReference:
    content = json.dumps(
        _json_safe(payload),
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return repository.persist_bytes(
        run_id=run_id,
        url_result_id=url_result_id,
        name=name,
        content=content,
    )


def _screenshot_bytes(
    artifacts: Mapping[str, object],
    *,
    root_dir: Path,
) -> bytes:
    raw_bytes = artifacts.get("browser_screenshot_png")
    if isinstance(raw_bytes, (bytes, bytearray)):
        return bytes(raw_bytes)
    raw_path = str(artifacts.get("browser_screenshot_path") or "").strip()
    if not raw_path:
        return b""
    try:
        root = Path(root_dir).resolve()
        source_path = Path(raw_path)
        path = (
            source_path.resolve()
            if source_path.is_absolute()
            else (root / source_path).resolve()
        )
    except OSError:
        return b""
    if not path.is_relative_to(root) or not path.is_file():
        return b""
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _safe_token(value: str) -> str:
    normalized = _SAFE_NAME_RE.sub("-", str(value or "").strip()).strip("-._")
    return normalized[:64] or "attempt"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json", exclude_none=True))
    return str(value)
