"""Per-(domain, surface) execution baseline — the self-healing learning loop.

Stores the expected execution signature for a ``(domain, surface)`` pair: which
extraction tiers normally run, which high-value fields normally extract, the
acquisition engine, a total-acquire timing band, and the normal verdict. After
each audited run the baseline is updated (rolling), so each run sharpens the
next ("learn once, reuse"). Drift from the baseline produces audit flags.

Storage: a JSON artifact per ``(domain, surface)`` under
``artifacts/observability/baselines/``. Deliberately NOT stored in
``DomainRunProfile.profile`` because that dict is re-normalized to a fixed schema
on every acquisition-contract save (unknown keys are dropped). Keeping the
baseline in its own observability-owned artifact avoids coupling, needs no
migration, and stays strictly ``(domain, surface)``-scoped per INVARIANT Rule 9.

Observe-only: this module never touches extraction output, verdicts, selector
memory, or the acquisition contract. It reads its own artifact and writes its
own artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.config import observability as obs_config
from app.services.config.audit_rules import (
    AUDIT_RULES,
    FLAG_BASELINE_ENGINE_CHANGED,
    FLAG_BASELINE_FIELD_REGRESSION,
    FLAG_BASELINE_TIER_REGRESSION,
    FLAG_BASELINE_TIMING_BREACH,
    FLAG_BASELINE_VERDICT_REGRESSION,
)
from app.services.domain_utils import normalize_domain

logger = logging.getLogger(__name__)

BASELINE_SUBDIR = "observability/baselines"
BASELINE_SCHEMA_VERSION = 1


def _baseline_dir() -> Path:
    return Path(settings.artifacts_dir) / BASELINE_SUBDIR


def _baseline_path(domain: str, surface: str) -> Path:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    key = f"{normalized_domain}__{normalized_surface}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe = "".join(ch if ch.isalnum() else "_" for ch in normalized_domain)[:48]
    return _baseline_dir() / f"{safe}__{normalized_surface}__{digest}.json"


def load_baseline(domain: str, surface: str) -> dict[str, Any] | None:
    path = _baseline_path(domain, surface)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Could not read baseline %s", path, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def build_observation(
    *,
    completed_tiers: list[str],
    fields_present: list[str],
    engine: str,
    total_acquire_ms: int | None,
    verdict: str,
) -> dict[str, Any]:
    """Normalize a single run into a comparable observation."""
    return {
        "tiers": sorted({str(t).strip().lower() for t in completed_tiers if str(t).strip()}),
        "fields": sorted({str(f).strip().lower() for f in fields_present if str(f).strip()}),
        "engine": str(engine or "").strip().lower(),
        "total_acquire_ms": int(total_acquire_ms) if total_acquire_ms is not None else None,
        "verdict": str(verdict or "").strip().lower(),
    }


def compare_to_baseline(
    baseline: dict[str, Any] | None,
    observation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return drift flags for this observation vs the learned baseline.

    Returns no flags until the baseline has enough samples to be trusted.
    """
    if not baseline:
        return []
    samples = int(baseline.get("samples", 0) or 0)
    if samples < obs_config.BASELINE_MIN_SAMPLES:
        return []

    flags: list[dict[str, Any]] = []

    baseline_fields = set(baseline.get("fields", []) or [])
    observed_fields = set(observation.get("fields", []) or [])
    lost_fields = sorted(baseline_fields - observed_fields)
    if lost_fields:
        flags.append(
            _drift_flag(
                FLAG_BASELINE_FIELD_REGRESSION,
                evidence={"lost_fields": lost_fields},
            )
        )

    baseline_tiers = set(baseline.get("tiers", []) or [])
    observed_tiers = set(observation.get("tiers", []) or [])
    lost_tiers = sorted(baseline_tiers - observed_tiers)
    if lost_tiers:
        flags.append(
            _drift_flag(
                FLAG_BASELINE_TIER_REGRESSION,
                evidence={"missing_tiers": lost_tiers},
            )
        )

    baseline_engine = str(baseline.get("engine", "") or "")
    observed_engine = observation.get("engine", "")
    if baseline_engine and observed_engine and baseline_engine != observed_engine:
        flags.append(
            _drift_flag(
                FLAG_BASELINE_ENGINE_CHANGED,
                evidence={"baseline_engine": baseline_engine, "engine": observed_engine},
            )
        )

    baseline_verdict = str(baseline.get("verdict", "") or "")
    observed_verdict = observation.get("verdict", "")
    if (
        baseline_verdict in obs_config.TRACE_SUCCESS_VERDICTS
        and observed_verdict
        and observed_verdict not in obs_config.TRACE_SUCCESS_VERDICTS
    ):
        flags.append(
            _drift_flag(
                FLAG_BASELINE_VERDICT_REGRESSION,
                evidence={"baseline_verdict": baseline_verdict, "verdict": observed_verdict},
            )
        )

    baseline_timing = baseline.get("avg_acquire_ms")
    observed_timing = observation.get("total_acquire_ms")
    if (
        isinstance(baseline_timing, (int, float))
        and baseline_timing > 0
        and isinstance(observed_timing, (int, float))
    ):
        ceiling = baseline_timing * (1 + obs_config.BASELINE_TIMING_TOLERANCE_RATIO)
        if (
            observed_timing > ceiling
            and observed_timing - baseline_timing
            > obs_config.BASELINE_TIMING_ABSOLUTE_SLACK_MS
        ):
            flags.append(
                _drift_flag(
                    FLAG_BASELINE_TIMING_BREACH,
                    evidence={
                        "baseline_avg_ms": int(baseline_timing),
                        "observed_ms": int(observed_timing),
                    },
                )
            )

    return flags


def update_baseline(
    domain: str,
    surface: str,
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Roll the observation into the stored baseline (learn-once/reuse)."""
    existing = load_baseline(domain, surface) or {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "domain": normalize_domain(domain or ""),
        "surface": str(surface or "").strip().lower(),
        "samples": 0,
        "tiers": [],
        "fields": [],
        "engine": "",
        "avg_acquire_ms": None,
        "verdict": "",
    }
    samples = int(existing.get("samples", 0) or 0)

    # Tiers/fields baseline = intersection of "what normally appears" once we
    # have samples; seed with the first observation.
    if samples == 0:
        merged_tiers = list(observation.get("tiers", []))
        merged_fields = list(observation.get("fields", []))
    else:
        # With samples present, merged_tiers/merged_fields intentionally tighten
        # to the intersection of existing and observation so regressions show as
        # missing tiers/fields; the baseline shrinks as more samples are added.
        merged_tiers = sorted(
            set(existing.get("tiers", []) or []) & set(observation.get("tiers", []))
        )
        merged_fields = sorted(
            set(existing.get("fields", []) or []) & set(observation.get("fields", []))
        )

    observed_timing = observation.get("total_acquire_ms")
    prior_avg = existing.get("avg_acquire_ms")
    if isinstance(observed_timing, (int, float)):
        if isinstance(prior_avg, (int, float)) and samples > 0:
            new_avg: float | None = (prior_avg * samples + observed_timing) / (samples + 1)
        else:
            new_avg = float(observed_timing)
    else:
        new_avg = prior_avg

    updated = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "domain": normalize_domain(domain or ""),
        "surface": str(surface or "").strip().lower(),
        "samples": samples + 1,
        "tiers": merged_tiers,
        "fields": merged_fields,
        "engine": observation.get("engine", "") or existing.get("engine", ""),
        "avg_acquire_ms": int(new_avg) if isinstance(new_avg, (int, float)) else None,
        "verdict": observation.get("verdict", "") or existing.get("verdict", ""),
    }
    _write_baseline(domain, surface, updated)
    return updated


def _write_baseline(domain: str, surface: str, payload: dict[str, Any]) -> None:
    path = _baseline_path(domain, surface)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _drift_flag(code: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    rule = AUDIT_RULES.get(code, {})
    return {
        "code": code,
        "severity": rule.get("severity", obs_config.FLAG_SEVERITY_LOW),
        "symptom": rule.get("symptom", code),
        "invariant": rule.get("invariant", ""),
        "owner": rule.get("owner", ""),
        "evidence": evidence,
    }


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "build_observation",
    "compare_to_baseline",
    "load_baseline",
    "update_baseline",
]
