"""Read access to the persisted root-cause diagnostics artifacts.

The per-URL writer (:mod:`app.persistence.url_result_artifacts`) emits one
``diagnose.json`` per result, and the run-complete callback
(:mod:`app.observability.run_report`) folds them into a single
``runs/{run_id}/report.json``. This module is the read side: it loads those
already-written artifacts back for the API, never re-deriving extraction state.

``report.json`` may not exist yet (the run-complete callback has not fired, or
the run is still in progress), so the run report falls back to building the
fold on-demand from whatever ``diagnose.json`` files are already on disk —
the same deterministic computation, just not yet persisted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.observability.run_report import build_run_report
from app.persistence.artifacts import ArtifactRepository


def load_result_diagnosis(
    *,
    run_id: int,
    url_result_id: int,
) -> dict[str, Any] | None:
    """Return the persisted ``diagnose.json`` for one URL result, or ``None``.

    ``None`` means the artifact was never written (e.g. the result predates the
    artifact writer, or acquisition produced nothing) — the caller maps that to
    a 404, distinct from an empty-but-present diagnosis.
    """
    repository = ArtifactRepository(root_dir=settings.artifacts_dir)
    uri = (
        Path("runs")
        / str(max(int(run_id or 0), 0))
        / "results"
        / str(int(url_result_id))
        / "diagnose.json"
    ).as_posix()
    try:
        payload = repository.read_json(uri)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def load_run_report(*, run_id: int) -> dict[str, Any]:
    """Return the run-level ``report.json``, building it on-demand if unwritten.

    The persisted file is authoritative once the run-complete callback has run.
    Before then we recompute the identical deterministic fold from the
    ``diagnose.json`` files already on disk so the endpoint is useful mid-run.
    """
    persisted = (
        Path(settings.artifacts_dir)
        / "runs"
        / str(max(int(run_id or 0), 0))
        / "report.json"
    )
    try:
        payload = json.loads(persisted.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict):
        return payload
    return build_run_report(run_id)
