"""Observe-only LLM run diagnosis (Slice 6, Phase 2).

On flagged runs only, and only when the run enabled LLM AND active config allows
it, ask an LLM to explain the run: where each high-value field came from, why a
field is missing, and which flagged root cause is most likely. Reuses the normal
LLM task plumbing (`run_prompt_task`) — no forked client.

Hard contract (INVARIANT Rule 6 + Rule 10): diagnosis is observe-only. It never
writes extraction fields, verdicts, records, selector memory, or the baseline.
Output is written to ``runs/<id>/audit/llm_diagnosis.json`` and referenced from
``flags.json``. LLM disabled/unavailable is recorded as a diagnostic, never an error.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.services.config import observability as obs_config
from app.services.config.llm_runtime import llm_runtime_settings
from app.services.db_utils import mapping_or_empty
from app.services.domain_utils import normalize_domain
from app.services.field_policy import repair_target_fields_for_surface
from app.services.llm.prompt_rendering import truncate_html, truncate_json_literal
from app.services.llm.tasks import run_prompt_task

logger = logging.getLogger(__name__)

_DIAGNOSIS_TASK = "run_diagnosis"


def diagnosis_enabled(run: CrawlRun) -> bool:
    """Both run setting AND a usable LLM config snapshot must be present."""
    settings_view = getattr(run, "settings_view", None)
    if settings_view is None:
        return False
    return bool(settings_view.llm_enabled()) and bool(
        settings_view.has_llm_config_snapshot()
    )


async def diagnose_run(
    session: AsyncSession,
    run: CrawlRun,
    records: list[CrawlRecord],
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce an LLM diagnosis for a flagged run. Always returns a payload.

    When LLM is disabled/unavailable, returns a skip diagnostic (never raises).
    """
    run_id = int(getattr(run, "id", 0) or 0)
    if not flags:
        return _skip("no_flags")
    if not diagnosis_enabled(run):
        return _skip("llm_disabled")

    surface = str(getattr(run, "surface", "") or "").strip().lower()
    primary = next((r for r in records if isinstance(r, CrawlRecord)), None)
    url = str(getattr(primary, "source_url", "") or getattr(run, "url", "") or "")
    domain = normalize_domain(url)
    high_value = repair_target_fields_for_surface(
        surface, list(getattr(run, "requested_fields", []) or [])
    )
    record_fields = _record_field_presence(primary)
    trace_payload = _load_trace(run_id, url)
    html_snippet = _load_html_snippet(primary, anchors=high_value)

    try:
        result = await run_prompt_task(
            session,
            task_type=_DIAGNOSIS_TASK,
            run_id=run_id,
            domain=domain,
            variables={
                "url": url,
                "surface": surface,
                "verdict": _verdict(run),
                "high_value_fields_json": json.dumps(high_value),
                "run_trace_json": truncate_json_literal(
                    trace_payload, llm_runtime_settings.candidate_evidence_max_chars
                ),
                "flags_json": truncate_json_literal(
                    flags, llm_runtime_settings.candidate_evidence_max_chars
                ),
                "record_fields_json": truncate_json_literal(
                    record_fields, llm_runtime_settings.existing_values_max_chars
                ),
                "html_snippet": truncate_html(
                    html_snippet,
                    llm_runtime_settings.html_snippet_max_chars,
                    anchors=high_value,
                ),
            },
            budget_scope=f"{_DIAGNOSIS_TASK}:{run_id}",
        )
    except Exception:
        logger.exception("LLM diagnosis call failed for run=%s", run_id)
        return _skip("llm_error")

    if result.error_message:
        return {
            "status": "unavailable",
            "reason": result.error_message,
            "provider": result.provider,
            "model": result.model,
        }
    payload = result.payload if isinstance(result.payload, dict) else {}
    return {
        "status": "ok",
        "provider": result.provider,
        "model": result.model,
        "diagnosis": payload,
    }


def write_diagnosis(run_id: int, diagnosis: dict[str, Any]) -> str:
    audit_dir = (
        Path(settings.artifacts_dir)
        / "runs"
        / str(max(int(run_id or 0), 0))
        / obs_config.AUDIT_ARTIFACT_SUBDIR
    )
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / obs_config.LLM_DIAGNOSIS_FILENAME
    path.write_text(
        json.dumps(diagnosis, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(path)


def _skip(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason}


def _verdict(run: CrawlRun) -> str:
    summary = mapping_or_empty(getattr(run, "result_summary", {}))
    return str(summary.get("extraction_verdict") or "").strip().lower()


def _record_field_presence(record: CrawlRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    data = mapping_or_empty(getattr(record, "data", {}))
    presence: dict[str, Any] = {}
    for key, value in data.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, str) and len(value) > 80:
            presence[str(key)] = f"<present:{len(value)} chars>"
        elif isinstance(value, (list, dict)):
            presence[str(key)] = f"<present:{type(value).__name__}:{len(value)}>"
        else:
            presence[str(key)] = value
    return presence


def _load_trace(run_id: int, url: str) -> dict[str, Any]:
    pages_dir = (
        Path(settings.artifacts_dir) / "runs" / str(max(int(run_id or 0), 0)) / "pages"
    )
    if not pages_dir.is_dir():
        return {}
    traces = sorted(pages_dir.glob("*.trace.json"))
    fallback_payload: dict[str, Any] | None = None
    for trace_path in traces:
        payload = _read_json(trace_path)
        if isinstance(payload, dict):
            if not url or payload.get("url") == url:
                return payload
            if fallback_payload is None:
                fallback_payload = payload
    # fall back to the first trace if no exact URL match
    if fallback_payload is not None:
        return fallback_payload
    return {}


def _load_html_snippet(record: CrawlRecord | None, *, anchors: list[str]) -> str:
    if record is None:
        return ""
    raw_html_path = str(getattr(record, "raw_html_path", "") or "").strip()
    if not raw_html_path:
        return ""
    try:
        artifacts_root = Path(settings.artifacts_dir).resolve()
        resolved = Path(raw_html_path).resolve()
    except OSError:
        return ""
    # Path-traversal guard: only read files inside the artifacts directory. A
    # poisoned raw_html_path must never let the diagnosis read arbitrary local
    # files and forward them to the LLM (INVARIANT Rule 10 — observe-only).
    if not resolved.is_relative_to(artifacts_root):
        logger.warning(
            "Refusing to read raw_html_path outside artifacts dir: %s", raw_html_path
        )
        return ""
    try:
        return resolved.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


__all__ = ["diagnose_run", "diagnosis_enabled", "write_diagnosis"]
