from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CandidateSet",
    "ExtractionResult",
    "ExtractionWarning",
    "RawCandidate",
    "RuntimeMetrics",
]


class RawCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1)
    value: Any
    source: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_type: str = ""
    extraction_tier: str = ""
    candidate_index: int = Field(default=0, ge=0)
    entity_ref: str | None = None
    entity_scope: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_locator: str = ""
    evidence: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: str = Field(min_length=1)
    page_url: str = ""
    candidates: list[RawCandidate] = Field(default_factory=list)
    field_decisions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def add(
        self,
        *,
        field_name: str,
        value: Any,
        source: str,
        extraction_tier: str,
        candidate_index: int,
        source_type: str = "",
        entity_ref: str | None = None,
        entity_scope: str | None = None,
        confidence: float = 0.0,
        source_locator: str = "",
        evidence: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        evidence_id = f"ev_{len(self.candidates) + 1:06d}"
        self.candidates.append(
            RawCandidate(
                field_name=field_name,
                value=value,
                source=source,
                evidence_id=evidence_id,
                source_type=source_type or _source_type(source),
                extraction_tier=extraction_tier,
                candidate_index=candidate_index,
                entity_ref=entity_ref,
                entity_scope=entity_scope,
                confidence=confidence,
                source_locator=source_locator,
                evidence=evidence,
                metadata=dict(metadata or {}),
            )
        )
        return evidence_id

    def record_resolution(
        self,
        *,
        field_name: str,
        winning_evidence_ids: list[str],
        resolver_rule: str,
    ) -> dict[str, Any]:
        entries = self.field_candidates(field_name)
        winner_ids = [
            evidence_id
            for evidence_id in winning_evidence_ids
            if any(entry.evidence_id == evidence_id for entry in entries)
        ]
        winner_values = {
            _semantic_value(entry.value)
            for entry in entries
            if entry.evidence_id in winner_ids
        }
        distinct_values = {_semantic_value(entry.value) for entry in entries}
        rejected_candidates = [
            {
                "evidence_id": entry.evidence_id,
                "reason": (
                    "duplicate_value"
                    if _semantic_value(entry.value) in winner_values
                    else "lower_source_priority"
                ),
            }
            for entry in entries
            if entry.evidence_id not in winner_ids
        ]
        decision = {
            "winning_evidence_ids": winner_ids,
            "candidate_count": len(entries),
            "rejected_candidate_count": len(rejected_candidates),
            "rejected_candidates": rejected_candidates,
            "conflict_count": max(0, len(distinct_values) - 1),
            "validation_finding_ids": [],
            "resolver_rule": resolver_rule,
            "llm_used": any(entry.source_type == "llm" for entry in entries),
        }
        self.field_decisions[field_name] = decision
        return dict(decision)

    def field_candidates(self, field_name: str) -> list[RawCandidate]:
        return [
            candidate
            for candidate in self.candidates
            if candidate.field_name == field_name
        ]

    def ordered(
        self,
        field_name: str,
        *,
        source_rank: Callable[[str], int],
    ) -> list[RawCandidate]:
        return sorted(
            self.field_candidates(field_name),
            key=lambda candidate: (
                source_rank(candidate.source),
                candidate.candidate_index,
            ),
        )

    def field_sources(self, field_name: str) -> list[str]:
        sources: list[str] = []
        for candidate in self.field_candidates(field_name):
            if candidate.source not in sources:
                sources.append(candidate.source)
        return sources

    def winning_field_sources(self, field_name: str) -> list[str]:
        winner_ids = set(
            self.field_decisions.get(field_name, {}).get("winning_evidence_ids") or []
        )
        sources: list[str] = []
        for candidate in self.field_candidates(field_name):
            if candidate.evidence_id not in winner_ids:
                continue
            if candidate.source not in sources:
                sources.append(candidate.source)
        return sources

    def as_graph(self) -> dict[str, Any]:
        return {
            "field_evidence": {
                candidate.evidence_id: candidate.model_dump(
                    mode="json",
                    exclude_none=True,
                )
                for candidate in self.candidates
            },
            "field_decisions": dict(self.field_decisions),
        }

    def stable_fingerprint(self) -> str:
        return json.dumps(
            self.as_graph(),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )


class ExtractionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field_name: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: str = Field(min_length=1)
    page_url: str = ""
    record: dict[str, Any] = Field(default_factory=dict)
    candidates: CandidateSet | None = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RuntimeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counters: dict[str, int] = Field(default_factory=dict)


def _source_type(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized == "adapter":
        return "adapter"
    if normalized in {"json_ld", "microdata", "opengraph", "json_ld_breadcrumb"}:
        return "structured_source"
    if normalized == "network_payload":
        return "network"
    if normalized == "js_state":
        return "js_state"
    if normalized.startswith("dom") or normalized in {"selector_rule", "html_image"}:
        return "dom"
    if normalized.startswith("llm"):
        return "llm"
    return "extraction"


def _semantic_value(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

