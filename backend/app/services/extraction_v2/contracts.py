from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

JsonValue = Any

PRODUCT_FACTS = frozenset(
    {
        "product.url",
        "product.title",
        "product.brand",
        "product.description",
        "product.category",
        "product.product_type",
        "product.sku",
        "product.mpn",
        "product.gtin",
        "product.materials",
        "product.color",
        "product.size",
    }
)
VARIANT_FACTS = frozenset(
    {
        "variant.id",
        "variant.sku",
        "variant.gtin",
        "variant.url",
        "variant.selected",
        "variant.option.size",
        "variant.option.color",
        "variant.option.width",
        "variant.option.length",
        "variant.option.material",
        "variant.option.style",
        "variant.option.capacity",
        "variant.option.quantity",
    }
)
OFFER_FACTS = frozenset(
    {
        "offer.price",
        "offer.currency",
        "offer.original_price",
        "offer.availability",
        "offer.stock_quantity",
        "offer.seller",
    }
)
ASSET_FACTS = frozenset({"asset.image_url", "asset.role", "asset.variant_association"})
FACT_TYPES = PRODUCT_FACTS | VARIANT_FACTS | OFFER_FACTS | ASSET_FACTS


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class RequestContext(FrozenModel):
    context_id: str
    locale: str | None = None
    language: str | None = None
    country: str | None = None
    currency_hint: str | None = None
    timezone: str | None = None
    browser_profile_id: str | None = None
    session_fingerprint: str | None = None


class ArtifactRef(FrozenModel):
    artifact_id: str
    artifact_type: Literal[
        "http_html",
        "rendered_html",
        "jsonld",
        "microdata",
        "opengraph",
        "js_state",
        "network_json",
        "screenshot",
    ]
    content_sha256: str
    storage_uri: str
    media_type: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CaptureBundle(FrozenModel):
    schema_version: Literal["capture.v1"]
    bundle_id: str
    run_id: int
    requested_url: str
    final_url: str
    request_context: RequestContext
    artifacts: tuple[ArtifactRef, ...]
    acquisition_outcome: str


class SourceLocator(FrozenModel):
    kind: Literal[
        "json_pointer",
        "css_selector",
        "xpath",
        "script_path",
        "network_json_pointer",
        "url_component",
        "adapter_path",
    ]
    value: str
    preview: str | None = None


class EntityHint(FrozenModel):
    entity_type: Literal["product", "variant", "offer", "asset"]
    product_id: str | None = None
    variant_id: str | None = None
    sku: str | None = None
    url: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    selected: bool | None = None


class Evidence(FrozenModel):
    evidence_id: str
    bundle_id: str
    artifact_id: str
    collector_id: str
    collector_version: str
    fact_type: str
    raw_value: JsonValue
    value: JsonValue
    locator: SourceLocator
    entity_hint: EntityHint | None = None
    group_id: str | None = None
    directness: Literal["direct", "embedded", "inferred"]
    confidence: float
    flags: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ArtifactReader(Protocol):
    def read_text(self, artifact: ArtifactRef) -> str: ...


class Collector(Protocol):
    collector_id: str
    collector_version: str

    def collect(self, bundle: CaptureBundle, artifacts: ArtifactReader) -> tuple[Evidence, ...]: ...


class RejectedEvidence(FrozenModel):
    evidence_id: str
    reason: str


class DerivedFact(FrozenModel):
    derived_fact_id: str
    entity_id: str
    fact_type: str
    value: JsonValue
    input_evidence_ids: tuple[str, ...]
    rule_id: str


class Finding(FrozenModel):
    finding_id: str
    rule_id: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    entity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    message: str
    blocking: bool
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Decision(FrozenModel):
    decision_id: str
    entity_id: str
    fact_type: str
    accepted_evidence_ids: tuple[str, ...]
    rejected: tuple[RejectedEvidence, ...]
    finding_ids: tuple[str, ...]
    rule_id: str
    status: Literal["resolved", "unresolved", "conflicted"]


class ResolutionResult(FrozenModel):
    primary_product_entity_id: str | None
    decisions: tuple[Decision, ...]
    derived_facts: tuple[DerivedFact, ...]
    unresolved_fact_types: tuple[str, ...]
    blocking_finding_ids: tuple[str, ...]


class ReplayArtifact(FrozenModel):
    bundle: CaptureBundle
    evidence: tuple[Evidence, ...]
    normalized_evidence: tuple[Evidence, ...]
    findings: tuple[Finding, ...]
    resolution: ResolutionResult
    record: dict[str, Any]
    verdict: str
