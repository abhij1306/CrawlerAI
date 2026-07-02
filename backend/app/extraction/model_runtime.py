"""Lazy, evaluation-gated universal-model fallback.

The runtime accepts only approved artifact metadata from the frozen run snapshot.
Predictions are converted to normal Evidence after source-grounding checks. This
module never resolves or publishes records.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from typing import Literal, Mapping, Protocol
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config.evaluation import (
    COMPACT_REPRESENTATION_ATTRIBUTES,
    COMPACT_REPRESENTATION_EXCLUDED_TAGS,
    COMPACT_REPRESENTATION_MAX_NODES,
    COMPACT_REPRESENTATION_MAX_TEXT_CHARS,
    COMPACT_REPRESENTATION_SCHEMA_VERSION,
    UNIVERSAL_MODEL_COLLECTOR_ID,
    UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY,
)
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    ModelEvidenceCandidate,
    SourceLocator,
    UniversalModelArtifact,
    UniversalModelResult,
)
from app.extraction.documents import HtmlDocument, HtmlNode

ModelRuntimeOutcome = Literal[
    "disabled",
    "produced_evidence",
    "no_match",
    "failed",
    "timed_out",
    "budget_limited",
]


class RuntimeRepresentationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, arbitrary_types_allowed=True, allow_inf_nan=False
    )


class RuntimeCompactSource(RuntimeRepresentationModel):
    artifact_id: str
    content_hash: str


class RuntimeCompactNode(RuntimeRepresentationModel):
    node_id: str
    tag: str
    path: str
    text: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    repeated_block_key: str | None = None


class RuntimeCompactPage(RuntimeRepresentationModel):
    schema_version: str = COMPACT_REPRESENTATION_SCHEMA_VERSION
    source: RuntimeCompactSource
    nodes: tuple[RuntimeCompactNode, ...]
    market_tags: tuple[str, ...] = ()
    truncated: bool = False


class RuntimeModelAdapter(Protocol):
    adapter_id: str

    def predict(
        self,
        page: RuntimeCompactPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult: ...


@dataclass(frozen=True)
class ModelFallbackResult:
    outcome: ModelRuntimeOutcome
    evidence: tuple[Evidence, ...] = ()
    artifact: UniversalModelArtifact | None = None
    representation_built: bool = False
    invoked: bool = False
    latency_ms: float = 0.0
    memory_mb: float = 0.0
    cost_usd: float = 0.0
    prediction_count: int = 0
    ungrounded_rejection_count: int = 0
    failure_code: (
        Literal["model_service_failure", "unsupported_representation"] | None
    ) = None
    detail: str | None = None


def run_model_fallback(
    request: ExtractionRequest,
    adapter: RuntimeModelAdapter | None,
) -> ModelFallbackResult:
    artifact, disabled_reason = _approved_artifact(request)
    if artifact is None:
        return ModelFallbackResult(outcome="disabled", detail=disabled_reason)
    if adapter is None:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="model_service_failure",
            detail="approved model artifact has no runtime adapter",
        )
    if adapter.adapter_id != artifact.adapter_id:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="model_service_failure",
            detail="runtime adapter identity does not match approved artifact",
        )
    source = _html_source(request)
    if source is None:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="unsupported_representation",
            detail="no HTML artifact is available for compact representation",
        )
    artifact_id, html = source
    page = build_runtime_compact_page(
        html=html,
        artifact_id=artifact_id,
        market_tags=_market_tags(request),
    )
    started = perf_counter()
    try:
        result = _predict_with_timeout(adapter, page, artifact)
    except TimeoutError:
        return ModelFallbackResult(
            outcome="timed_out",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=(perf_counter() - started) * 1_000,
            failure_code="model_service_failure",
            detail="universal model invocation timed out",
        )
    except Exception as exc:  # model service must degrade without breaking extraction
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=(perf_counter() - started) * 1_000,
            failure_code="model_service_failure",
            detail=f"universal model invocation failed: {type(exc).__name__}",
        )
    elapsed_ms = (perf_counter() - started) * 1_000
    identity_error = _result_identity_error(result, artifact)
    if identity_error:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=elapsed_ms,
            memory_mb=result.memory_mb,
            cost_usd=result.cost_usd,
            prediction_count=len(result.predictions),
            failure_code="model_service_failure",
            detail=identity_error,
        )
    if (
        elapsed_ms > artifact.timeout_ms
        or result.memory_mb > artifact.max_memory_mb
        or result.cost_usd > artifact.max_cost_per_page_usd
    ):
        return ModelFallbackResult(
            outcome="budget_limited",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=elapsed_ms,
            memory_mb=result.memory_mb,
            cost_usd=result.cost_usd,
            prediction_count=len(result.predictions),
            detail="universal model runtime budget exceeded",
        )
    evidence, rejected = _grounded_evidence(request, page, artifact, result)
    return ModelFallbackResult(
        outcome="produced_evidence" if evidence else "no_match",
        evidence=evidence,
        artifact=artifact,
        representation_built=True,
        invoked=True,
        latency_ms=elapsed_ms,
        memory_mb=result.memory_mb,
        cost_usd=result.cost_usd,
        prediction_count=len(result.predictions),
        ungrounded_rejection_count=rejected,
    )


def build_runtime_compact_page(
    *,
    html: str,
    artifact_id: str,
    market_tags: tuple[str, ...] = (),
    max_nodes: int = COMPACT_REPRESENTATION_MAX_NODES,
) -> RuntimeCompactPage:
    if max_nodes <= 0:
        raise ValueError("max_nodes must be greater than zero")
    node_limit = min(max_nodes, COMPACT_REPRESENTATION_MAX_NODES)
    candidates = tuple(_candidate_nodes(HtmlDocument(artifact_id, html)))
    retained = candidates[:node_limit]
    repeated_keys = _repeated_block_keys(candidates)
    nodes = tuple(
        RuntimeCompactNode(
            node_id=f"n{index}",
            tag=node.tag(),
            path=node.dom_path(),
            text=_bounded_text(node.direct_text()),
            attributes=_selected_attributes(node.attributes()),
            repeated_block_key=repeated_keys.get(node.identity()),
        )
        for index, node in enumerate(retained, start=1)
    )
    return RuntimeCompactPage(
        source=RuntimeCompactSource(
            artifact_id=artifact_id,
            content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        ),
        nodes=nodes,
        market_tags=market_tags,
        truncated=len(candidates) > node_limit,
    )


def _predict_with_timeout(
    adapter: RuntimeModelAdapter,
    page: RuntimeCompactPage,
    artifact: UniversalModelArtifact,
) -> UniversalModelResult:
    responses: Queue[UniversalModelResult | Exception] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            responses.put(
                adapter.predict(page, artifact, timeout_ms=artifact.timeout_ms)
            )
        except Exception as exc:
            responses.put(exc)

    Thread(target=invoke, daemon=True).start()
    try:
        response = responses.get(timeout=artifact.timeout_ms / 1_000)
    except Empty as exc:
        raise TimeoutError from exc
    if isinstance(response, Exception):
        raise response
    return response


def _approved_artifact(
    request: ExtractionRequest,
) -> tuple[UniversalModelArtifact | None, str]:
    if request.runtime_snapshot is None:
        return None, "no universal model artifact in frozen runtime snapshot"
    raw = request.runtime_snapshot.get(UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY)
    if not isinstance(raw, Mapping):
        return None, "no universal model artifact in frozen runtime snapshot"
    try:
        artifact = UniversalModelArtifact.model_validate(dict(raw))
    except ValidationError:
        return None, "universal model artifact metadata is invalid"
    if not artifact.enabled:
        return None, "universal model fallback is disabled"
    if not artifact.approved or not artifact.benchmark_passed:
        return None, "universal model artifact is not benchmark-approved"
    if request.surface not in artifact.supported_surfaces:
        return None, "universal model artifact does not support requested surface"
    return artifact, ""


def _html_source(request: ExtractionRequest) -> tuple[str, str] | None:
    html_artifacts = sorted(
        (
            artifact
            for artifact in request.capture.artifacts
            if artifact.artifact_type in {"rendered_html", "http_html"}
        ),
        key=lambda artifact: artifact.artifact_type != "rendered_html",
    )
    for artifact in html_artifacts:
        if request.artifact_reader.exists(artifact.artifact_id):
            return artifact.artifact_id, request.artifact_reader.read_text(artifact)
    return None


def _market_tags(request: ExtractionRequest) -> tuple[str, ...]:
    context = request.capture.request_context
    return tuple(
        value
        for value in (
            context.locale,
            context.language,
            context.country,
            context.currency_hint,
        )
        if value
    )


def _result_identity_error(
    result: UniversalModelResult, artifact: UniversalModelArtifact
) -> str | None:
    if result.adapter_id != artifact.adapter_id:
        return "model result adapter identity mismatch"
    if (
        result.artifact_id != artifact.artifact_id
        or result.artifact_version != artifact.artifact_version
    ):
        return "model result artifact identity mismatch"
    return None


def _grounded_evidence(
    request: ExtractionRequest,
    page: RuntimeCompactPage,
    artifact: UniversalModelArtifact,
    result: UniversalModelResult,
) -> tuple[tuple[Evidence, ...], int]:
    nodes_by_path = {node.path: node for node in page.nodes}
    rows: list[Evidence] = []
    rejected = 0
    for candidate in result.predictions:
        if candidate.confidence < artifact.confidence_threshold:
            continue
        node = nodes_by_path.get(candidate.source_path)
        if (
            candidate.artifact_id != page.source.artifact_id
            or node is None
            or not _value_is_grounded(candidate.raw_value, node)
            or not _canonical_value_is_grounded(request, candidate, node)
        ):
            rejected += 1
            continue
        rows.append(_candidate_evidence(request, artifact, candidate, node))
    return tuple(rows), rejected


def _candidate_evidence(
    request: ExtractionRequest,
    artifact: UniversalModelArtifact,
    candidate: ModelEvidenceCandidate,
    node: RuntimeCompactNode,
) -> Evidence:
    return Evidence(
        evidence_id=stable_id(
            "evidence",
            request.capture.bundle_id,
            UNIVERSAL_MODEL_COLLECTOR_ID,
            artifact.artifact_id,
            candidate.prediction_id,
        ),
        bundle_id=request.capture.bundle_id,
        artifact_id=candidate.artifact_id,
        collector_id=UNIVERSAL_MODEL_COLLECTOR_ID,
        collector_version=artifact.artifact_version,
        fact_type=candidate.fact_type,
        raw_value=candidate.raw_value,
        value=candidate.value,
        locator=SourceLocator(
            kind="dom_path",
            value=candidate.source_path,
            preview=_bounded_text(
                node.text or next(iter(node.attributes.values()), "")
            ),
        ),
        entity_hint=candidate.entity_hint,
        group_id=candidate.group_id,
        directness="inferred",
        confidence=candidate.confidence,
        flags=("model_prediction",),
        metadata={
            "model_artifact_id": artifact.artifact_id,
            "model_artifact_version": artifact.artifact_version,
            "model_family": artifact.model_family,
            "benchmark_report_id": artifact.benchmark_report_id,
        },
        surface=request.surface,
        subject_id=candidate.subject_id,
        parent_subject_id=candidate.parent_subject_id,
        subject_scope=candidate.subject_scope,
        relation_type=candidate.relation_type,
    )


def _value_is_grounded(value: object, node: RuntimeCompactNode) -> bool:
    needle = _normalize_source_value(value)
    if not needle:
        return False
    sources = (node.text, *node.attributes.values())
    return any(
        needle == normalized or needle in normalized
        for source in sources
        if (normalized := _normalize_source_value(source))
    )


def _canonical_value_is_grounded(
    request: ExtractionRequest,
    candidate: ModelEvidenceCandidate,
    node: RuntimeCompactNode,
) -> bool:
    if _value_is_grounded(candidate.value, node):
        return True
    raw = _normalize_source_value(candidate.raw_value)
    canonical = _normalize_source_value(candidate.value)
    if raw and canonical and canonical in raw:
        return True
    if candidate.fact_type in {"product.url", "asset.image_url"}:
        base_url = request.capture.final_url or request.capture.requested_url
        return canonical == _normalize_source_value(
            urljoin(base_url, str(candidate.raw_value))
        )
    return False


def _normalize_source_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return " ".join(str("" if value is None else value).casefold().split())


def _candidate_nodes(document: HtmlDocument):
    for node in document.nodes():
        if not node.tag() or node.tag() in COMPACT_REPRESENTATION_EXCLUDED_TAGS:
            continue
        if node.direct_text() or _selected_attributes(node.attributes()):
            yield node


def _selected_attributes(attributes) -> dict[str, str]:
    allowed = set(COMPACT_REPRESENTATION_ATTRIBUTES)
    return {
        str(key): _bounded_text(str(value or ""))
        for key, value in dict(attributes or {}).items()
        if str(key) in allowed
    }


def _bounded_text(value: str) -> str:
    return " ".join(value.split())[:COMPACT_REPRESENTATION_MAX_TEXT_CHARS]


def _repeated_block_keys(nodes: tuple[HtmlNode, ...]) -> dict[int, str]:
    node_classes: dict[int, str] = {}
    counts: dict[str, int] = {}
    for node in nodes:
        classes = " ".join((node.attribute("class") or "").split()[:2])
        if not classes:
            continue
        key = f"{node.tag()}:{classes}"
        node_classes[node.identity()] = key
        counts[key] = counts.get(key, 0) + 1
    return {
        node_id: key for node_id, key in node_classes.items() if counts.get(key, 0) > 1
    }
