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
from app.crawl.pipeline.run_complete_callbacks import register_run_complete_callback

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "run-report.v1"
_CALLBACK_KEY = "observability_run_report"

# Published/resolved fields are not root causes; every other state is.
_CLEAN_FIELD_STATES = frozenset({"captured_and_resolved", "captured_published"})


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
        for root_cause in _root_causes(diagnosis):
            groups.setdefault(root_cause, _RootCauseGroup(root_cause)).add(link)
    root_causes = [group.as_dict() for group in groups.values()]
    root_causes.sort(key=lambda item: (-int(item["count"]), str(item["root_cause"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": int(run_id or 0),
        "root_cause_count": len(root_causes),
        "root_causes": root_causes,
    }


class _RootCauseGroup:
    __slots__ = ("root_cause", "_links")

    def __init__(self, root_cause: str) -> None:
        self.root_cause = root_cause
        self._links: list[str] = []

    def add(self, link: str) -> None:
        if link not in self._links:
            self._links.append(link)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "count": len(self._links),
            "diagnose_links": sorted(self._links),
        }


def _root_causes(diagnosis: Mapping[str, object]) -> list[str]:
    """Group keys for one diagnose.json. Empty when nothing went wrong."""
    causes: set[str] = set()
    for field in _object_list(diagnosis.get("fields")):
        field_name = str(field.get("field") or "").strip() or "?"
        publication_policy = field.get("publication_policy")
        if publication_policy not in (None, "", [], {}):
            causes.add(
                f"publication_policy:{field_name}:{_scalar(publication_policy)}"
            )
        status = str(field.get("status") or "").strip()
        if status and status not in _CLEAN_FIELD_STATES:
            causes.add(f"field:{field_name}:{status}")
    for drop in _object_list(_mapping(diagnosis.get("variants")).get("dropped")):
        stage = str(drop.get("stage") or "?").strip()
        rule = str(drop.get("rule") or "?").strip()
        causes.add(f"variant_dropped:{stage}:{rule}")
    return sorted(causes)


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
