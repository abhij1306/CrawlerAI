"""From-scratch run auditor (read-only).

Runs at ``on_run_complete`` for every finished run. Reads the per-URL RunTrace
artifacts, the persisted records, and the run summary, applies deterministic
symptom rules grounded in INVARIANTS.md, and writes
``artifacts/runs/<id>/audit/flags.json``. Each flag points at the owning file
from CODEBASE_MAP plus an evidence reference into the trace.

Hard contract: observe-only. This module never mutates records, verdicts,
selector memory, domain contracts, or any extraction state. It only reads and
writes its own audit artifact.

This is written from scratch and does NOT build on
``backend/run_json_issue_audit.py`` (that script is retired; at most a secondary
record-quality input later).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.services.config import observability as obs_config
from app.services.config.audit_rules import (
    AUDIT_RULES,
    AUDIT_SCHEMA_VERSION,
    FLAG_DOM_SKIPPED_WITH_VARIANT_CUES,
    FLAG_HIGH_VALUE_FIELD_MISSING,
    FLAG_LISTING_SINGLE_METADATA_RECORD,
    FLAG_USABLE_CONTENT_BUT_BLOCKED,
)
from app.services.db_utils import mapping_or_empty
from app.services.domain_utils import normalize_domain
from app.services.field_policy import repair_target_fields_for_surface
from app.services.observability.baseline import (
    build_observation,
    compare_to_baseline,
    load_baseline,
    update_baseline,
)
from app.services.pipeline.run_complete_callbacks import register_run_complete_callback

logger = logging.getLogger(__name__)

_CALLBACK_KEY = "observability_run_audit"


def ensure_run_audit_registered() -> None:
    """Register the auditor as a run-complete callback (idempotent)."""
    register_run_complete_callback(audit_run_complete, key=_CALLBACK_KEY)


async def audit_run_complete(run_id: int) -> None:
    """Run-complete entry point. Never raises into the pipeline."""
    try:
        async with SessionLocal() as session:
            run = await session.get(CrawlRun, run_id)
            if run is None:
                return
            records = (
                (
                    await session.execute(
                        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )
            flags = build_run_flags(run, list(records), update_baselines=True)
            diagnosis = await _maybe_diagnose(session, run, list(records), flags)
            _write_flags(run_id, flags, diagnosis_status=diagnosis)
    except Exception:
        logger.exception("Run audit failed for run=%s", run_id)


async def _maybe_diagnose(
    session,
    run: CrawlRun,
    records: list[CrawlRecord],
    flags: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Run the observe-only LLM diagnosis on flagged runs; write its artifact.

    Returns a small status dict to embed in flags.json, or None when not run.
    Never raises into the audit path.
    """
    if not flags:
        return None
    try:
        from app.services.observability.run_llm_diagnosis import (
            diagnose_run,
            write_diagnosis,
        )

        diagnosis = await diagnose_run(session, run, records, flags)
        if diagnosis.get("status") == "skipped":
            return {"status": "skipped", "reason": diagnosis.get("reason")}
        path = write_diagnosis(int(getattr(run, "id", 0) or 0), diagnosis)
        return {"status": diagnosis.get("status"), "artifact": path}
    except Exception:
        logger.exception("LLM diagnosis failed for run=%s", getattr(run, "id", None))
        return {"status": "error"}


def build_run_flags(
    run: CrawlRun,
    records: list[CrawlRecord],
    *,
    update_baselines: bool = False,
) -> list[dict[str, Any]]:
    """Pure-ish flag builder (DB objects in, flag dicts out). No record mutation.

    When ``update_baselines`` is True, the per-(domain, surface) execution
    baseline is compared and rolled forward (the self-healing learning loop).
    """
    surface = str(getattr(run, "surface", "") or "").strip().lower()
    summary = mapping_or_empty(getattr(run, "result_summary", {}))
    verdict = str(summary.get("extraction_verdict") or "").strip().lower()
    requested_fields = list(getattr(run, "requested_fields", []) or [])
    high_value = _high_value_fields(surface, requested_fields)

    flags: list[dict[str, Any]] = []

    # Listing produced exactly one metadata-only row -> Rule 7.
    if "listing" in surface and len(records) == 1:
        record_data = mapping_or_empty(getattr(records[0], "data", {}))
        if _looks_like_metadata_only(record_data):
            flags.append(
                _flag(
                    FLAG_LISTING_SINGLE_METADATA_RECORD,
                    evidence={"record_keys": sorted(record_data.keys())},
                    url=getattr(records[0], "source_url", ""),
                )
            )

    for record in records:
        flags.extend(_audit_record(record, surface=surface, high_value=high_value))

    # Run-level acquisition flags from the per-URL trace artifacts.
    flags.extend(_audit_traces(run_id=int(getattr(run, "id", 0) or 0), verdict=verdict))

    # Baseline drift (the self-healing loop), scoped by (domain, surface).
    flags.extend(
        _audit_baseline_drift(
            run,
            records,
            surface=surface,
            verdict=verdict,
            high_value=high_value,
            update_baselines=update_baselines,
        )
    )

    return flags


def _audit_baseline_drift(
    run: CrawlRun,
    records: list[CrawlRecord],
    *,
    surface: str,
    verdict: str,
    high_value: list[str],
    update_baselines: bool,
) -> list[dict[str, Any]]:
    domain = _run_domain(run, records)
    if not domain or not surface:
        return []
    observation = build_observation(
        completed_tiers=_observed_tiers(records),
        fields_present=_observed_high_value_fields(records, high_value),
        engine=_observed_engine(records),
        total_acquire_ms=_observed_total_acquire_ms(int(getattr(run, "id", 0) or 0)),
        verdict=verdict,
    )
    baseline = load_baseline(domain, surface)
    flags = compare_to_baseline(baseline, observation)
    if update_baselines:
        try:
            update_baseline(domain, surface, observation)
        except Exception:
            # Baseline persistence is a sidecar; a write/serialize failure must
            # not abort the audit and suppress flags.json for the run.
            logger.exception(
                "Baseline update failed for domain=%s surface=%s", domain, surface
            )
    return flags


def _run_domain(run: CrawlRun, records: list[CrawlRecord]) -> str:
    for record in records:
        domain = normalize_domain(str(getattr(record, "source_url", "") or ""))
        if domain:
            return domain
    return normalize_domain(str(getattr(run, "url", "") or ""))


def _observed_tiers(records: list[CrawlRecord]) -> list[str]:
    for record in records:
        source_trace = mapping_or_empty(getattr(record, "source_trace", {}))
        extraction = mapping_or_empty(source_trace.get("extraction"))
        tiers = extraction.get("completed_tiers")
        if isinstance(tiers, list) and tiers:
            return [str(t) for t in tiers]
    return []


def _observed_high_value_fields(
    records: list[CrawlRecord],
    high_value: list[str],
) -> list[str]:
    present: set[str] = set()
    high_value_set = set(high_value)
    for record in records:
        data = mapping_or_empty(getattr(record, "data", {}))
        for field_name in high_value_set:
            if data.get(field_name) not in (None, "", [], {}):
                present.add(field_name)
    return sorted(present)


def _observed_engine(records: list[CrawlRecord]) -> str:
    for record in records:
        source_trace = mapping_or_empty(getattr(record, "source_trace", {}))
        acquisition = mapping_or_empty(source_trace.get("acquisition"))
        diagnostics = mapping_or_empty(acquisition.get("browser_diagnostics"))
        engine = str(diagnostics.get("browser_engine") or "").strip().lower()
        if engine:
            return engine
        method = str(acquisition.get("method") or "").strip().lower()
        if method and method != "browser":
            return method
    return ""


def _observed_total_acquire_ms(run_id: int) -> int | None:
    pages_dir = _run_pages_dir(run_id)
    if not pages_dir.is_dir():
        return None
    total_ms = 0
    found = False
    for browser_path in sorted(pages_dir.glob("*.browser.json")):
        diagnostics = _read_json(browser_path)
        if not isinstance(diagnostics, dict):
            continue
        timings = mapping_or_empty(diagnostics.get("phase_timings_ms"))
        total = timings.get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            total_ms += int(total)
            found = True
    return total_ms if found else None


def _audit_record(
    record: CrawlRecord,
    *,
    surface: str,
    high_value: list[str],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    data = mapping_or_empty(getattr(record, "data", {}))
    source_trace = mapping_or_empty(getattr(record, "source_trace", {}))
    extraction = mapping_or_empty(source_trace.get("extraction"))
    url = str(getattr(record, "source_url", "") or "")

    # Missing high-value field with no recorded diagnostic.
    missing = [
        field_name
        for field_name in high_value
        if data.get(field_name) in (None, "", [], {})
    ]
    field_discovery_missing = source_trace.get("field_discovery_missing")
    diagnosed = set(field_discovery_missing) if isinstance(field_discovery_missing, list) else set()
    undiagnosed_missing = [field_name for field_name in missing if field_name not in diagnosed]
    if undiagnosed_missing:
        flags.append(
            _flag(
                FLAG_HIGH_VALUE_FIELD_MISSING,
                evidence={"missing_fields": undiagnosed_missing},
                url=url,
            )
        )

    # DOM skipped while variants missing and variant cues present -> Rule 3.
    if "detail" in surface and data.get("variants") in (None, "", [], {}):
        skip = mapping_or_empty(extraction.get("dom_skip"))
        if bool(skip.get(obs_config.DOM_SKIP_KEY_SKIPPED)) and _has_variant_cues(data):
            flags.append(
                _flag(
                    FLAG_DOM_SKIPPED_WITH_VARIANT_CUES,
                    evidence={
                        "confidence": skip.get(obs_config.DOM_SKIP_KEY_CONFIDENCE),
                        "threshold": skip.get(obs_config.DOM_SKIP_KEY_THRESHOLD),
                        "reason": skip.get(obs_config.DOM_SKIP_KEY_REASON),
                    },
                    url=url,
                )
            )
    return flags


def _audit_traces(*, run_id: int, verdict: str) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    pages_dir = _run_pages_dir(run_id)
    if not pages_dir.is_dir():
        return flags
    for browser_path in sorted(pages_dir.glob("*.browser.json")):
        diagnostics = _read_json(browser_path)
        if not isinstance(diagnostics, dict):
            continue
        outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
        host_outcome = mapping_or_empty(diagnostics.get("host_outcome"))
        blocked = bool(host_outcome.get("blocked")) or verdict in obs_config.AUDIT_BLOCKED_VERDICTS
        # usable_content but the run/host says blocked -> Rule 6 contradiction.
        if outcome == "usable_content" and blocked:
            flags.append(
                _flag(
                    FLAG_USABLE_CONTENT_BUT_BLOCKED,
                    evidence={
                        "browser_outcome": outcome,
                        "host_result": host_outcome.get("result"),
                        "verdict": verdict,
                    },
                    url=str(diagnostics.get("final_url") or ""),
                )
            )
    return flags


def _flag(code: str, *, evidence: dict[str, Any], url: str = "") -> dict[str, Any]:
    rule = AUDIT_RULES.get(code, {})
    flag: dict[str, Any] = {
        "code": code,
        "severity": rule.get("severity", obs_config.FLAG_SEVERITY_MEDIUM),
        "symptom": rule.get("symptom", code),
        "invariant": rule.get("invariant", ""),
        "owner": rule.get("owner", ""),
    }
    if url:
        flag["url"] = url
    if evidence:
        flag["evidence"] = evidence
    return flag


def _high_value_fields(surface: str, requested_fields: list[str]) -> list[str]:
    resolved = repair_target_fields_for_surface(surface, requested_fields)
    if resolved:
        return resolved
    return list(obs_config.HIGH_VALUE_FIELD_FLOOR)


def _looks_like_metadata_only(data: dict[str, Any]) -> bool:
    populated = {
        key
        for key, value in data.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not populated:
        return False
    return populated <= obs_config.AUDIT_METADATA_ONLY_KEYS


def _has_variant_cues(data: dict[str, Any]) -> bool:
    for key in obs_config.AUDIT_VARIANT_CUE_FIELDS:
        if data.get(key) not in (None, "", [], {}):
            return True
    return False


def _run_audit_dir(run_id: int) -> Path:
    return Path(settings.artifacts_dir) / "runs" / str(max(int(run_id or 0), 0)) / obs_config.AUDIT_ARTIFACT_SUBDIR


def _run_pages_dir(run_id: int) -> Path:
    return Path(settings.artifacts_dir) / "runs" / str(max(int(run_id or 0), 0)) / "pages"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Could not read audit input %s", path, exc_info=True)
        return None


def _write_flags(
    run_id: int,
    flags: list[dict[str, Any]],
    *,
    diagnosis_status: dict[str, Any] | None = None,
) -> str:
    audit_dir = _run_audit_dir(run_id)
    audit_dir.mkdir(parents=True, exist_ok=True)
    severity_counts: dict[str, int] = {}
    for flag in flags:
        severity = str(flag.get("severity", "")) or "unknown"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    payload = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "run_id": int(run_id or 0),
        "flag_count": len(flags),
        "severity_counts": dict(sorted(severity_counts.items())),
        "flags": flags,
    }
    if diagnosis_status is not None:
        payload["llm_diagnosis"] = diagnosis_status
    path = audit_dir / obs_config.FLAGS_FILENAME
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(path)


__all__ = [
    "audit_run_complete",
    "build_run_flags",
    "ensure_run_audit_registered",
]
