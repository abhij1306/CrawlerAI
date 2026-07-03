"""Deterministic run-level root-cause report (``runs/{id}/report.json``).

Run-complete callback. It scans every ``diagnose.json`` the per-URL writer
emitted, groups them by root cause, and writes a single ``report.json`` listing
each root cause with a count and direct links back to the contributing
``diagnose.json`` files. No DB, no LLM, no baselines — purely a deterministic
fold over the already-self-contained diagnose artifacts, so the same inputs
always produce the same report.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.config.extraction_rules import DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS
from app.crawl.pipeline.run_complete_callbacks import register_run_complete_callback

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "run-report.v1"
_CALLBACK_KEY = "observability_run_report"

# Published/resolved fields are not root causes; every other state is.
_CLEAN_FIELD_STATES = frozenset(
    {"captured_and_resolved", "captured_published", "not_requested"}
)
# Parent field states that count as "the public parent already carries this fact"
# for the parent/child divergence metric.
_PARENT_PUBLISHED_FIELD_STATES = frozenset(
    {"captured_and_resolved", "captured_published"}
)
# These findings are metrics emitted for every result, not failures. They remain
# available in diagnose.json but must never inflate the run-level root-cause list.
_INFORMATIONAL_FINDING_RULES = frozenset({"RECORD_COMPLETENESS"})
# Finding scopes that describe discarded candidate evidence rather than the
# public/selected record. Diagnostic-only: preserved per-page, never a run cause.
_DIAGNOSTIC_ONLY_FINDING_SCOPES = frozenset({"candidate"})
_EXAMPLE_LIMIT = 5


def ensure_run_report_registered() -> None:
    """Register the report generator as a run-complete callback (idempotent)."""
    register_run_complete_callback(write_run_report, key=_CALLBACK_KEY)


async def write_run_report(run_id: int) -> None:
    """Run-complete entry point. Never raises into the pipeline.

    The disk scan + serialization + write is fully synchronous; we hop to a
    worker thread so a large run cannot block the event loop.
    """
    try:
        await asyncio.to_thread(_build_and_write_report, run_id)
    except Exception:
        logger.exception("Run report failed for run=%s", run_id)


def _build_and_write_report(run_id: int) -> None:
    report = build_run_report(run_id)
    _write_report(run_id, report)


def build_run_report(run_id: int) -> dict[str, Any]:
    groups: dict[str, _RootCauseGroup] = {}
    results_dir = _run_results_dir(run_id)
    for diagnose_path in sorted(results_dir.glob("*/diagnose.json")):
        diagnosis = _read_json(diagnose_path)
        if not isinstance(diagnosis, Mapping):
            continue
        link = _diagnose_link(run_id, diagnose_path)
        for root_cause, example in _root_causes(diagnosis):
            groups.setdefault(root_cause, _RootCauseGroup(root_cause)).add(
                link, example
            )
    root_causes = [group.as_dict() for group in groups.values()]
    root_causes.sort(key=lambda item: (-int(item["count"]), str(item["root_cause"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": int(run_id or 0),
        "root_cause_count": len(root_causes),
        "root_causes": root_causes,
    }


class _RootCauseGroup:
    __slots__ = ("root_cause", "_links", "_examples")

    def __init__(self, root_cause: str) -> None:
        self.root_cause = root_cause
        self._links: list[str] = []
        self._examples: list[dict[str, object]] = []

    def add(self, link: str, example: Mapping[str, object] | None = None) -> None:
        if link not in self._links:
            self._links.append(link)
        if example and len(self._examples) < _EXAMPLE_LIMIT:
            self._examples.append(dict(example))

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "root_cause": self.root_cause,
            "count": len(self._links),
            "diagnose_links": sorted(self._links),
        }
        if self._examples:
            payload["examples"] = self._examples
        return payload


def _root_causes(
    diagnosis: Mapping[str, object],
) -> list[tuple[str, dict[str, object]]]:
    """Group keys for one diagnose.json. Empty when nothing went wrong."""
    causes: dict[str, dict[str, object]] = {}
    field_status: dict[str, str] = {}
    for field in _object_list(diagnosis.get("fields")):
        field_name = str(field.get("field") or "").strip() or "?"
        status = str(field.get("status") or "").strip()
        field_status[field_name] = status
        # ``variants.*`` are a separate variant-scope summary (see
        # projection_field_states). They stay in per-page diagnose.json but must
        # not inflate run-level root causes with variant-only noise; the
        # parent/child divergence they enable is folded in as its own metric
        # below.
        if field_name.startswith("variants."):
            continue
        publication_policy = field.get("publication_policy")
        if publication_policy not in (None, "", [], {}):
            cause = f"publication_policy:{field_name}:{_scalar(publication_policy)}"
            causes.setdefault(cause, {"field": field_name})
        if status and status not in _CLEAN_FIELD_STATES:
            causes.setdefault(
                f"field:{field_name}:{status}",
                {
                    "field": field_name,
                    "status": status,
                    "reason_codes": list(_string_list(field.get("reason_codes"))),
                },
            )
            for reason in _string_list(field.get("reason_codes")):
                causes.setdefault(
                    f"field_reason:{field_name}:{status}:{reason}",
                    {"field": field_name, "status": status, "reason": reason},
                )
    # Run-level metric (audit Slice 1.5): a public parent commercial field is
    # absent while the same field is published on a child variant. This is the
    # divergence that path-aware field states make visible; surface it as its own
    # deterministic root cause so operators can see structured child facts that
    # never became parent facts.
    for commercial_field in DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS:
        parent_status = field_status.get(commercial_field, "")
        child_status = field_status.get(f"variants.{commercial_field}", "")
        if (
            child_status == "captured_published"
            and parent_status not in _PARENT_PUBLISHED_FIELD_STATES
        ):
            causes.setdefault(
                f"parent_absent_child_published:{commercial_field}",
                {
                    "field": commercial_field,
                    "parent_status": parent_status or "not_present",
                    "child_status": child_status,
                },
            )
    for drop in _object_list(_mapping(diagnosis.get("variants")).get("dropped")):
        stage = str(drop.get("stage") or "?").strip()
        rule = str(drop.get("rule") or "?").strip()
        causes.setdefault(
            f"variant_dropped:{stage}:{rule}",
            {"stage": stage, "rule": rule, "reason": str(drop.get("reason") or "")},
        )
    for finding in _object_list(diagnosis.get("findings")):
        rule_id = str(finding.get("rule_id") or "").strip()
        if not rule_id or rule_id in _INFORMATIONAL_FINDING_RULES:
            continue
        # Candidate-scope findings are evidence diagnostics about discarded
        # candidates, not public-integrity failures. Keep them in per-page
        # diagnose.json but never fold them into run-level root causes (audit
        # Slice 1.4) — otherwise discarded-candidate offer-pair warnings dominate.
        if str(finding.get("scope") or "").strip() in _DIAGNOSTIC_ONLY_FINDING_SCOPES:
            continue
        severity = str(finding.get("severity") or "").strip() or "unknown"
        blocking = bool(finding.get("blocking"))
        prefix = "blocking_finding" if blocking else "finding"
        metadata = _mapping(finding.get("metadata"))
        field_name = str(metadata.get("field") or "").strip()
        cause = f"{prefix}:{rule_id}"
        if rule_id == "MISSING_CONTRACT_FIELD" and field_name:
            cause = f"{cause}:{field_name}"
        causes.setdefault(
            cause,
            {
                "rule_id": rule_id,
                "severity": severity,
                "blocking": blocking,
                "scope": str(finding.get("scope") or ""),
                **({"field": field_name} if field_name else {}),
            },
        )
    acquisition = _mapping(diagnosis.get("acquisition"))
    if bool(acquisition.get("blocked")):
        causes.setdefault(
            "capture_assessment:blocked",
            {"status_code": acquisition.get("status_code")},
        )
    if acquisition.get("failure_reason") not in (None, ""):
        causes.setdefault(
            f"capture_failure:{_scalar(acquisition.get('failure_reason'))}",
            {"failure_reason": _scalar(acquisition.get("failure_reason"))},
        )
    return sorted(causes.items())


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _diagnose_link(run_id: int, diagnose_path: Path) -> str:
    return (
        Path("runs")
        / str(max(int(run_id or 0), 0))
        / "results"
        / diagnose_path.parent.name
        / "diagnose.json"
    ).as_posix()


def _run_results_dir(run_id: int) -> Path:
    return (
        Path(settings.artifacts_dir)
        / "runs"
        / str(max(int(run_id or 0), 0))
        / "results"
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Could not read diagnose artifact %s", path, exc_info=True)
        return None


def _write_report(run_id: int, report: Mapping[str, object]) -> str:
    run_dir = Path(settings.artifacts_dir) / "runs" / str(max(int(run_id or 0), 0))
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(path)


def _object_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for item in value if (text := str(item)).strip())


def _scalar(value: object) -> str:
    if isinstance(value, Mapping):
        return str(value.get("reason") or value.get("code") or next(iter(value), ""))
    if isinstance(value, (list, tuple)):
        return ",".join(_scalar(item) for item in value)
    return str(value)


__all__ = [
    "build_run_report",
    "ensure_run_report_registered",
    "write_run_report",
]
