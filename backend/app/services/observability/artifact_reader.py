"""Read-only reader for a run's observability artifacts (Slice 7).

Surfaces the per-run audit flags, per-URL traces, and the LLM diagnosis for the
frontend "Run Trace" tab. Read-only: this module only reads files written by the
trace/audit layers. It never recomputes or mutates anything.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.config import observability as obs_config

logger = logging.getLogger(__name__)


def _normalize_run_id(run_id: int) -> int:
    return max(int(run_id or 0), 0)


def _run_dir(run_id: int) -> Path:
    return Path(settings.artifacts_dir) / "runs" / str(_normalize_run_id(run_id))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Could not read observability artifact %s", path, exc_info=True)
        return None


def read_run_observability(run_id: int) -> dict[str, Any]:
    """Return the flags, per-URL traces, and LLM diagnosis for a run.

    Missing artifacts yield empty/None values rather than errors so the frontend
    can render a partial view for runs that predate this feature.
    """
    normalized_run_id = _normalize_run_id(run_id)
    run_dir = _run_dir(normalized_run_id)
    audit_dir = run_dir / obs_config.AUDIT_ARTIFACT_SUBDIR
    pages_dir = run_dir / "pages"

    flags = _read_json(audit_dir / obs_config.FLAGS_FILENAME)
    diagnosis = _read_json(audit_dir / obs_config.LLM_DIAGNOSIS_FILENAME)

    traces: list[dict[str, Any]] = []
    if pages_dir.is_dir():
        for trace_path in sorted(pages_dir.glob("*.trace.json")):
            payload = _read_json(trace_path)
            if isinstance(payload, dict):
                traces.append(payload)

    return {
        "run_id": normalized_run_id,
        "flags": flags if isinstance(flags, dict) else None,
        "traces": traces,
        "llm_diagnosis": diagnosis if isinstance(diagnosis, dict) else None,
    }


__all__ = ["read_run_observability"]
