from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.persistence.artifacts import ArtifactRepository
from app.persistence.contracts import (
    ArtifactManifest,
    ArtifactReference,
    ExtractionArtifactSet,
)


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
    extraction = extraction_result.model_dump(mode="json", exclude_none=True)
    extraction["record_count"] = int(record_count or 0)

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

    screenshot = _screenshot_bytes(
        _mapping(getattr(acquisition_result, "artifacts", {})),
        root_dir=repository.root_dir,
    )
    if screenshot:
        references.append(
            repository.persist_bytes(
                run_id=run_id,
                url_result_id=url_result_id,
                name="screenshot.png",
                content=screenshot,
            )
        )

    references.append(
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name="summary.json",
            payload=_summary_payload(
                acquisition_result=acquisition_result,
                extraction=extraction,
            ),
        )
    )
    references.append(
        _persist_json(
            repository,
            run_id=run_id,
            url_result_id=url_result_id,
            name="records.json",
            payload={
                "records": extraction.get("records", []),
                "provenance": list(record_provenance),
            },
        )
    )

    if str(extraction.get("verdict") or "").strip().lower() != "success":
        references.append(
            _persist_json(
                repository,
                run_id=run_id,
                url_result_id=url_result_id,
                name="debug.json",
                payload=_debug_payload(
                    acquisition_result=acquisition_result,
                    extraction=extraction,
                ),
            )
        )

    bundle_id = str(getattr(extraction_result, "bundle_id", "") or "").strip()
    if not bundle_id:
        bundle_id = f"run-{max(int(run_id or 0), 0)}-result-{int(url_result_id)}"
    manifest = ArtifactManifest(
        run_id=run_id,
        url_result_id=url_result_id,
        bundle_id=bundle_id,
        extraction=ExtractionArtifactSet(artifacts=tuple(references)),
    )
    reference = repository.persist_manifest(manifest)
    return PublishedUrlArtifacts(manifest=manifest, reference=reference)


def _summary_payload(
    *,
    acquisition_result: Any,
    extraction: Mapping[str, object],
) -> dict[str, object]:
    acquisition_diagnostics = _mapping(
        getattr(acquisition_result, "acquisition_diagnostics", {})
    )
    acquisition_result_diagnostics = _mapping(acquisition_diagnostics.get("result"))
    browser_diagnostics = _mapping(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    decisions = _object_list(extraction.get("decisions"))
    return {
        "schema_version": "url-diagnostics.v2",
        "acquisition": {
            "final_url": str(getattr(acquisition_result, "final_url", "") or ""),
            "method": str(getattr(acquisition_result, "method", "") or ""),
            "status_code": getattr(acquisition_result, "status_code", None),
            "content_type": str(getattr(acquisition_result, "content_type", "") or ""),
            "blocked": bool(getattr(acquisition_result, "blocked", False)),
            "platform_family": getattr(acquisition_result, "platform_family", None),
            "adapter_name": getattr(acquisition_result, "adapter_name", None),
            "selected_attempt_id": acquisition_result_diagnostics.get(
                "selected_attempt_id"
            ),
            "attempts": acquisition_result_diagnostics.get("attempts", []),
            "browser_outcome": browser_diagnostics.get("browser_outcome"),
            "failure_reason": browser_diagnostics.get("failure_reason")
            or acquisition_result_diagnostics.get("failure_reason"),
        },
        "extraction": {
            "bundle_id": extraction.get("bundle_id"),
            "target": extraction.get("target", {}),
            "findings": extraction.get("findings", []),
            "decisions": decisions,
            "verdict": extraction.get("verdict"),
            "retry_request": extraction.get("retry_request"),
            "metrics": extraction.get("metrics", {}),
            "record_count": extraction.get("record_count", 0),
        },
    }


def _debug_payload(
    *,
    acquisition_result: Any,
    extraction: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "url-debug.v2",
        "acquisition": {
            "browser_diagnostics": _mapping(
                getattr(acquisition_result, "browser_diagnostics", {})
            ),
            "acquisition_diagnostics": _mapping(
                getattr(acquisition_result, "acquisition_diagnostics", {})
            ),
            "response": getattr(acquisition_result, "json_data", None),
            "network_payloads": list(
                getattr(acquisition_result, "network_payloads", []) or []
            ),
            "runtime_artifacts": {
                key: value
                for key, value in _mapping(
                    getattr(acquisition_result, "artifacts", {})
                ).items()
                if not isinstance(value, bytes)
            },
        },
        "extraction": dict(extraction),
    }


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
