"""RunTrace collector + typed trace contract.

A ``RunTrace`` accumulates the causal chain for a single processed URL: the
ordered acquire timeline (closing the launch -> rendered blackhole), the
extraction tier execution and skip-DOM decision (closing the extraction
blackhole), high-value field provenance (winner + losers + reject reasons),
normalization edits, and the final verdict.

Design contracts:
- Observe-only. Collecting a trace must never change pipeline behavior.
- No-op when disabled. When ``RUN_TRACE_ENABLED`` is False (or no collector is
  attached), every record_* call is a cheap no-op so hot paths are unaffected.
- Tiered. The lightweight trace is always recorded; full candidate-competition
  detail is only retained when the run is non-success or a flag fires (the
  consumer decides via ``should_capture_full`` at serialization time).
- Bounded. High-value-field-only candidate capture, capped loser lists.

This slice defines the contract and collector. Instrumentation call sites are
wired in later slices.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.config import observability as obs_config
from app.services.field_policy import repair_target_fields_for_surface

logger = logging.getLogger(__name__)


def high_value_fields(surface: str, requested_fields: list[str] | None) -> list[str]:
    """Resolve the high-value field set for a surface.

    Union of run ``requested_fields`` and the surface's default canonical repair
    targets, via the canonical field-policy owner. Falls back to a defensive
    floor only when nothing resolves (keeps candidate capture bounded without a
    parallel hardcoded list).
    """
    resolved = repair_target_fields_for_surface(surface, requested_fields)
    if resolved:
        return resolved
    return list(obs_config.HIGH_VALUE_FIELD_FLOOR)


@dataclass(slots=True)
class AcquireEvent:
    """One ordered step in the acquire timeline."""

    kind: str
    detail: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "sequence": self.sequence}
        if self.duration_ms is not None:
            payload["duration_ms"] = int(self.duration_ms)
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass(slots=True)
class CandidateObservation:
    """One candidate value competing for a field slot."""

    source: str
    won: bool
    value_preview: str = ""
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": self.source, "won": self.won}
        if self.value_preview:
            payload["value_preview"] = self.value_preview
        if self.reject_reason:
            payload["reject_reason"] = self.reject_reason
        return payload


@dataclass(slots=True)
class FieldProvenanceObservation:
    """Provenance for a single high-value field: winner + losing candidates."""

    field_name: str
    winning_source: str | None = None
    present: bool | None = None
    value_shape: str = ""
    value_count: int | None = None
    note: str = ""
    candidates: list[CandidateObservation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"field": self.field_name}
        if self.winning_source is not None:
            payload["winning_source"] = self.winning_source
        if self.present is not None:
            payload["present"] = bool(self.present)
        if self.value_shape:
            payload["value_shape"] = self.value_shape
        if self.value_count is not None:
            payload["value_count"] = int(self.value_count)
        if self.note:
            payload["note"] = self.note
        if self.candidates:
            payload["candidates"] = [c.to_dict() for c in self.candidates]
        return payload


@dataclass(slots=True)
class ExtractionTrace:
    """Tier execution + the skip-DOM decision + field provenance."""

    completed_tiers: list[str] = field(default_factory=list)
    dom_skipped: bool | None = None
    skip_decision: dict[str, Any] = field(default_factory=dict)
    rejection_reason: str = ""
    field_provenance: dict[str, FieldProvenanceObservation] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"completed_tiers": list(self.completed_tiers)}
        if self.dom_skipped is not None:
            payload["dom_skipped"] = bool(self.dom_skipped)
        if self.skip_decision:
            payload["skip_decision"] = dict(self.skip_decision)
        if self.rejection_reason:
            payload["rejection_reason"] = self.rejection_reason
        if self.field_provenance:
            payload["field_provenance"] = [
                obs.to_dict() for obs in self.field_provenance.values()
            ]
        return payload


@dataclass(slots=True)
class RunTrace:
    """Per-URL trace. Attach one to the processing context per URL.

    All ``record_*`` methods are tolerant of partial data and never raise into
    the pipeline; the collector is a diagnostics sink, not a control path.
    """

    run_id: int
    url: str
    surface: str = ""
    requested_fields: list[str] = field(default_factory=list)
    acquire_events: list[AcquireEvent] = field(default_factory=list)
    extraction: ExtractionTrace = field(default_factory=ExtractionTrace)
    normalize_edits: list[dict[str, Any]] = field(default_factory=list)
    host_outcome: dict[str, Any] = field(default_factory=dict)
    verdict: str = ""
    _seq: int = 0
    _high_value: frozenset[str] = field(default_factory=frozenset)
    _diagnostic_fields: frozenset[str] = field(default_factory=frozenset)
    _trace_fields: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self._high_value = frozenset(
            high_value_fields(self.surface, self.requested_fields)
        )
        if "detail" in str(self.surface or "").strip().lower():
            self._diagnostic_fields = frozenset(obs_config.DETAIL_DIAGNOSTIC_FIELDS)
        self._trace_fields = self._high_value | self._diagnostic_fields

    # -- acquire timeline -----------------------------------------------------
    def record_acquire_event(
        self,
        kind: str,
        *,
        detail: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._seq += 1
        self.acquire_events.append(
            AcquireEvent(
                kind=str(kind),
                detail=dict(detail or {}),
                duration_ms=duration_ms,
                sequence=self._seq,
            )
        )

    def record_host_outcome(self, outcome: dict[str, Any]) -> None:
        self.host_outcome = dict(outcome or {})

    # -- extraction -----------------------------------------------------------
    def record_completed_tiers(self, tiers: list[str]) -> None:
        self.extraction.completed_tiers = [str(t) for t in tiers if str(t).strip()]

    def record_skip_dom_decision(
        self,
        *,
        dom_skipped: bool,
        confidence: float | None = None,
        threshold: float | None = None,
        dom_completion_reason: str | None = None,
    ) -> None:
        self.extraction.dom_skipped = bool(dom_skipped)
        decision: dict[str, Any] = {}
        if confidence is not None:
            decision["confidence"] = float(confidence)
        if threshold is not None:
            decision["threshold"] = float(threshold)
        if dom_completion_reason:
            decision["dom_completion_reason"] = str(dom_completion_reason)
        self.extraction.skip_decision = decision

    def record_extraction_rejection(self, reason: str | None) -> None:
        cleaned = str(reason or "").strip()
        if cleaned:
            self.extraction.rejection_reason = cleaned

    def record_field_candidate(
        self,
        field_name: str,
        *,
        source: str,
        won: bool,
        value_preview: str = "",
        reject_reason: str | None = None,
    ) -> None:
        """Record a competing candidate for a high-value field only.

        Non-trace fields are ignored to bound trace size. Loser lists are capped
        per field.
        """
        normalized = str(field_name or "").strip().lower()
        if normalized not in self._trace_fields:
            return
        obs = self._field_observation(normalized)
        if won:
            if obs.winning_source is not None:
                logger.warning("Ignoring repeated winning candidate for %s", normalized)
                return
            obs.winning_source = str(source)
            obs.candidates.append(
                CandidateObservation(
                    source=str(source),
                    won=True,
                    value_preview=_preview(value_preview),
                    reject_reason=str(reject_reason) if reject_reason else None,
                )
            )
            return
        loser_count = sum(1 for candidate in obs.candidates if not candidate.won)
        if loser_count >= obs_config.MAX_CANDIDATE_LOSERS_PER_FIELD:
            return
        obs.candidates.append(
            CandidateObservation(
                source=str(source),
                won=False,
                value_preview=_preview(value_preview),
                reject_reason=str(reject_reason) if reject_reason else None,
            )
        )

    def record_field_state(
        self,
        field_name: str,
        *,
        value: object,
        candidate_sources: list[str] | None = None,
    ) -> None:
        normalized = str(field_name or "").strip().lower()
        if normalized not in self._trace_fields:
            return
        obs = self._field_observation(normalized)
        present = value not in (None, "", [], {})
        obs.present = present
        obs.value_shape, obs.value_count = _value_shape(value)
        if (
            not present
            and candidate_sources
            and obs.note in ("", "missing_without_candidate")
        ):
            obs.note = "candidate_source_without_public_value"
        elif not present and not candidate_sources and not obs.note:
            obs.note = "missing_without_candidate"

    def trace_field_names(self) -> list[str]:
        return sorted(self._trace_fields)

    def _field_observation(self, normalized: str) -> FieldProvenanceObservation:
        obs = self.extraction.field_provenance.get(normalized)
        if obs is None:
            obs = FieldProvenanceObservation(field_name=normalized)
            self.extraction.field_provenance[normalized] = obs
        return obs

    # -- normalize / verdict --------------------------------------------------
    def record_normalize_edit(self, field_name: str, reason: str) -> None:
        self.normalize_edits.append({"field": str(field_name), "reason": str(reason)})

    def record_verdict(self, verdict: str) -> None:
        self.verdict = str(verdict or "")

    # -- serialization --------------------------------------------------------
    def should_capture_full(self, *, flagged: bool = False) -> bool:
        """Full candidate-competition detail is retained on non-success or flags."""
        if flagged:
            return True
        return self.verdict not in obs_config.TRACE_SUCCESS_VERDICTS

    def to_dict(self, *, flagged: bool = False) -> dict[str, Any]:
        tier = (
            obs_config.TRACE_TIER_FULL
            if self.should_capture_full(flagged=flagged)
            else obs_config.TRACE_TIER_LIGHT
        )
        extraction_payload = self.extraction.to_dict()
        if tier == obs_config.TRACE_TIER_LIGHT:
            # Light tier keeps tier execution + skip decision + winning sources,
            # but drops the verbose losing-candidate lists.
            extraction_payload = _light_extraction(extraction_payload)
        payload: dict[str, Any] = {
            "schema_version": obs_config.RUN_TRACE_SCHEMA_VERSION,
            "tier": tier,
            "run_id": self.run_id,
            "url": self.url,
            "surface": self.surface,
            "requested_fields": list(self.requested_fields),
            "high_value_fields": sorted(self._high_value),
            "diagnostic_fields": sorted(self._diagnostic_fields),
            "verdict": self.verdict,
            "acquire_timeline": [event.to_dict() for event in self.acquire_events],
            "extraction": extraction_payload,
        }
        if self.host_outcome:
            payload["host_outcome"] = dict(self.host_outcome)
        if self.normalize_edits:
            payload["normalize_edits"] = list(self.normalize_edits)
        return payload


class NullRunTrace(RunTrace):
    """No-op trace used when tracing is disabled.

    Every ``record_*`` call is a no-op and ``to_dict`` yields an empty envelope
    (no acquire events, no completed tiers). Subclassing keeps call sites
    type-stable (they always hold a ``RunTrace``) without paying collection
    cost. ``persist_run_trace`` additionally short-circuits when tracing is
    disabled, so a NullRunTrace is never actually serialized in production.

    Override signatures mirror ``RunTrace`` exactly so static analysis sees a
    consistent method contract across the hierarchy.
    """

    def __init__(self) -> None:
        super().__init__(run_id=0, url="")

    def record_acquire_event(
        self,
        kind: str,
        *,
        detail: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        return None

    def record_host_outcome(self, outcome: dict[str, Any]) -> None:
        return None

    def record_completed_tiers(self, tiers: list[str]) -> None:
        return None

    def record_skip_dom_decision(
        self,
        *,
        dom_skipped: bool,
        confidence: float | None = None,
        threshold: float | None = None,
        dom_completion_reason: str | None = None,
    ) -> None:
        return None

    def record_extraction_rejection(self, reason: str | None) -> None:
        return None

    def record_field_candidate(
        self,
        field_name: str,
        *,
        source: str,
        won: bool,
        value_preview: str = "",
        reject_reason: str | None = None,
    ) -> None:
        return None

    def record_normalize_edit(self, field_name: str, reason: str) -> None:
        return None

    def record_verdict(self, verdict: str) -> None:
        return None


def new_run_trace(
    *,
    run_id: int,
    url: str,
    surface: str = "",
    requested_fields: list[str] | None = None,
) -> RunTrace:
    """Factory: a real collector when enabled, a no-op otherwise."""
    if not obs_config.RUN_TRACE_ENABLED:
        return NullRunTrace()
    return RunTrace(
        run_id=int(run_id or 0),
        url=str(url or ""),
        surface=str(surface or ""),
        requested_fields=list(requested_fields or []),
    )


def _preview(value: Any, *, limit: int = 120) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}\u2026"


def _light_extraction(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    light = dict(extraction_payload)
    provenance = light.get("field_provenance")
    if isinstance(provenance, list):
        light["field_provenance"] = [
            {
                key: value
                for key, value in dict(entry).items()
                if key
                in {
                    "field",
                    "winning_source",
                    "present",
                    "value_shape",
                    "value_count",
                    "note",
                }
            }
            for entry in provenance
        ]
    return light


def _value_shape(value: object) -> tuple[str, int | None]:
    if value in (None, "", [], {}):
        return ("missing", None)
    if isinstance(value, list):
        return ("list", len(value))
    if isinstance(value, dict):
        return ("dict", len(value))
    return (type(value).__name__, None)


# Reserved for future timing helpers in instrumentation slices.
def now_ms() -> int:
    return int(time.monotonic() * 1000)


__all__ = [
    "AcquireEvent",
    "CandidateObservation",
    "ExtractionTrace",
    "FieldProvenanceObservation",
    "NullRunTrace",
    "RunTrace",
    "high_value_fields",
    "new_run_trace",
    "now_ms",
]
