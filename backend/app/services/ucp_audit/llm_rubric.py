from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config import aid_score as config
from app.services.llm.runtime import run_prompt_task
from app.services.ucp_audit.evidence import EvidencePacket

logger = logging.getLogger(__name__)


class RubricVerdict(StrEnum):
    PASS = "PASS"  # nosec B105
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(slots=True)
class SimulatedQueryResult:
    query: str
    answerable: bool
    gap: str = ""


@dataclass(slots=True)
class RubricFinding:
    dimension: str
    verdict: RubricVerdict
    evidence_quote: str
    finding_code: str
    recommendation: str


@dataclass(slots=True)
class RubricResult:
    url: str
    findings: list[RubricFinding] = field(default_factory=list)
    simulated_queries: list[SimulatedQueryResult] = field(default_factory=list)
    llm_provider: str = ""
    llm_model: str = ""
    error: str = ""

    def to_contract(self) -> dict[str, Any]:
        return asdict(self)


async def audit_evidence_packets(
    session: AsyncSession,
    *,
    domain: str,
    audit_id: str,
    packets: list[EvidencePacket],
) -> list[RubricResult]:
    results: list[RubricResult] = []
    for packet in packets[: config.AID_LLM_MAX_PAGES]:
        task_result = await run_prompt_task(
            session,
            task_type=config.AID_LLM_TASK,
            run_id=None,
            domain=domain,
            variables={"evidence_packet": packet.to_prompt_dict()},
            budget_scope=f"{config.AID_LLM_TASK}:{audit_id}",
            timeout_seconds=config.AID_LLM_TIMEOUT_SECONDS,
        )
        if task_result.error_message:
            results.append(_error_result(packet.url, task_result.error_message))
            continue
        result = parse_rubric_payload(
            task_result.payload,
            fallback_url=packet.url,
            provider=task_result.provider,
            model=task_result.model,
        )
        results.append(result)
    return results


def parse_rubric_payload(
    payload: object,
    *,
    fallback_url: str,
    provider: str = "",
    model: str = "",
) -> RubricResult:
    if not isinstance(payload, dict):
        return _error_result(fallback_url, "invalid LLM JSON payload")
    result = RubricResult(
        url=str(payload.get("url") or fallback_url),
        llm_provider=provider,
        llm_model=model,
        error=str(payload.get("error") or ""),
    )
    for raw in payload.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        finding = _parse_finding(raw)
        if finding:
            result.findings.append(finding)
    for raw in payload.get("simulated_queries") or []:
        if isinstance(raw, dict):
            result.simulated_queries.append(
                SimulatedQueryResult(
                    query=str(raw.get("query") or ""),
                    answerable=bool(raw.get("answerable")),
                    gap=str(raw.get("gap") or ""),
                )
            )
    return result


def _parse_finding(raw: dict[str, Any]) -> RubricFinding | None:
    verdict = _verdict(raw.get("verdict"))
    evidence_quote = str(raw.get("evidence_quote") or "").strip()
    if verdict in {RubricVerdict.PARTIAL, RubricVerdict.FAIL} and not evidence_quote:
        logger.warning("AID LLM finding downgraded because evidence_quote was empty")
        verdict = RubricVerdict.INSUFFICIENT_EVIDENCE
    return RubricFinding(
        dimension=str(raw.get("dimension") or ""),
        verdict=verdict,
        evidence_quote=evidence_quote,
        finding_code=str(raw.get("finding_code") or config.FINDING_AID_LLM_INSUFFICIENT_EVIDENCE),
        recommendation=str(raw.get("recommendation") or ""),
    )


def _verdict(value: object) -> RubricVerdict:
    try:
        return RubricVerdict(str(value or ""))
    except ValueError:
        return RubricVerdict.INSUFFICIENT_EVIDENCE


def _error_result(url: str, error: str) -> RubricResult:
    return RubricResult(
        url=url,
        findings=[
            RubricFinding(
                dimension=dimension,
                verdict=RubricVerdict.INSUFFICIENT_EVIDENCE,
                evidence_quote="",
                finding_code=config.FINDING_AID_LLM_INSUFFICIENT_EVIDENCE,
                recommendation="",
            )
            for dimension in config.AID_LLM_RUBRIC_DIMENSIONS
        ],
        error=error,
    )
