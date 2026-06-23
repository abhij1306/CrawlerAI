from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from app.core.config.variant_policy import PUBLIC_VARIANT_AXIS_FIELDS
from app.extraction.surfaces import Surface

JsonValue = Any

PRODUCT_FACTS = frozenset(
    f"product.{field}"
    for field in (
        "url",
        "title",
        "brand",
        "description",
        "category",
        "product_type",
        "sku",
        "mpn",
        "gtin",
        "materials",
        "color",
        "size",
    )
)
VARIANT_FACTS = frozenset(
    {
        *(f"variant.{field}" for field in ("id", "sku", "gtin", "url", "selected")),
        *(f"variant.option.{axis}" for axis in PUBLIC_VARIANT_AXIS_FIELDS),
    }
)
OFFER_FACTS = frozenset(
    f"offer.{field}"
    for field in (
        "price",
        "currency",
        "original_price",
        "availability",
        "stock_quantity",
        "seller",
    )
)
ASSET_FACTS = frozenset({"asset.image_url", "asset.role", "asset.variant_association"})
OPTION_FACTS = frozenset(
    f"option.{axis}" for axis in PUBLIC_VARIANT_AXIS_FIELDS
)
FACT_TYPES = PRODUCT_FACTS | VARIANT_FACTS | OFFER_FACTS | ASSET_FACTS | OPTION_FACTS


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


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
        "css_recipe",
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
    http_status: int | None = None
    acquisition_method: str | None = None
    request_context: RequestContext
    artifacts: tuple[ArtifactRef, ...]
    acquisition_outcome: str
    browser_attempted: bool = False
    blocked: bool = False
    captured_at: str | None = None


class SourceLocator(FrozenModel):
    kind: Literal[
        "json_pointer",
        "css_selector",
        "script_path",
        "network_json_pointer",
        "url_component",
        "adapter_path",
    ]
    value: str
    preview: str | None = None


class EntityHint(FrozenModel):
    entity_type: Literal["product", "variant", "offer", "asset", "job"]
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
    surface: Surface = Surface.ECOMMERCE_DETAIL
    subject_id: str
    parent_subject_id: str | None = None

    @property
    def entity_kind(self) -> str:
        if self.entity_hint is not None:
            return self.entity_hint.entity_type
        return self.fact_type.split(".", 1)[0]


@runtime_checkable
class ArtifactReader(Protocol):
    document_store: Any

    def read_text(self, artifact: ArtifactRef) -> str: ...

    def read_json(self, artifact: ArtifactRef) -> JsonValue: ...

    def exists(self, artifact_id: str) -> bool: ...


class Collector(Protocol):
    collector_id: str
    collector_version: str

    def collect(
        self, bundle: CaptureBundle, artifacts: ArtifactReader
    ) -> tuple[Evidence, ...]: ...


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
    scope: Literal[
        "artifact",
        "entity",
        "candidate",
        "selected_entity",
        "selected_public_value",
        "page",
    ] = "entity"
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


class OfferDecision(FrozenModel):
    offer_entity_id: str
    status: Literal["resolved", "unresolved", "conflicted"]
    accepted_evidence_ids: tuple[str, ...]
    price: JsonValue | None = None
    currency: str | None = None
    original_price: JsonValue | None = None
    availability: str | None = None
    seller: str | None = None


class AssetDecision(FrozenModel):
    asset_entity_id: str | None
    url: str | None = None
    accepted_evidence_ids: tuple[str, ...]
    role: str = "primary"
    rank: int = 0
    rule_id: str = "PRODUCT_ASSET_SELECTION"
    rejection_reasons: tuple[str, ...] = ()


class OptionValue(FrozenModel):
    value: str
    evidence_ids: tuple[str, ...] = ()


class OptionAxis(FrozenModel):
    axis: str
    values: tuple[OptionValue, ...] = ()


class ProductOptionCatalog(FrozenModel):
    product_entity_id: str
    axes: tuple[OptionAxis, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class ResolutionResult(FrozenModel):
    primary_product_entity_id: str | None
    primary_offer_entity_id: str | None = None
    decisions: tuple[Decision, ...]
    asset_decisions: tuple[AssetDecision, ...] = ()
    derived_facts: tuple[DerivedFact, ...]
    unresolved_fact_types: tuple[str, ...]
    blocking_finding_ids: tuple[str, ...]


class EntityGraph(FrozenModel):
    schema_version: Literal["entity_graph.v1"] = "entity_graph.v1"
    root_entity_ids: tuple[str, ...] = ()
    entity_counts: dict[str, int] = Field(default_factory=dict)


class RejectedEntity(FrozenModel):
    entity_id: str
    reason: str


class TargetSelection(FrozenModel):
    status: Literal["resolved", "ambiguous", "missing", "wrong_surface"] = "missing"
    root_entity_ids: tuple[str, ...] = ()
    selected_root_entity_id: str | None = None
    rejected_roots: tuple[RejectedEntity, ...] = ()


class CapabilityRequest(FrozenModel):
    schema_version: Literal["capability-request.v1"] = "capability-request.v1"
    required: bool = False
    reason: Literal[
        "dynamic_content_missing", "explicit_variants_missing", "http_shell"
    ]
    required_artifacts: tuple[str, ...] = ()
    max_attempts: int = Field(default=1, ge=1, le=1)


RetryRequest = CapabilityRequest


class ExtractionMetrics(FrozenModel):
    collector_count: int = 0
    evidence_count: int = 0
    entity_counts: dict[str, int] = Field(default_factory=dict)
    finding_counts_by_severity: dict[str, int] = Field(default_factory=dict)
    decision_counts_by_status: dict[str, int] = Field(default_factory=dict)
    selected_root_ids: tuple[str, ...] = ()
    variant_count: int = 0
    public_lineage_coverage: float = 0.0
    completeness_score: float = 0.0
    verdict: str | None = None


class PublicRecord(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    def __getitem__(self, key: str) -> Any:
        payload = self.model_dump(mode="json", exclude_none=True)
        if key not in payload:
            raise KeyError(key)
        return payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        extra = self.__pydantic_extra__ or {}
        return getattr(self, key, extra.get(key, default))

    def items(self):
        return self.model_dump(mode="python").items()

    def keys(self):
        return self.model_dump(mode="python").keys()

    def values(self):
        return self.model_dump(mode="python").values()

    def __iter__(self):
        return iter(self.model_dump(mode="python"))

    def __len__(self) -> int:
        return len(self.model_dump(mode="python"))


class CommerceVariantRecord(PublicRecord):
    variant_id: str | None = None
    sku: str | None = None
    price: JsonValue | None = None
    currency: str | None = None
    url: str | None = None
    image_url: str | None = None
    availability: str | None = None
    stock_quantity: JsonValue | None = None


class CommerceDetailRecord(PublicRecord):
    url: str
    title: str | None = None
    brand: str | None = None
    description: str | None = None
    category: str | None = None
    sku: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    price: JsonValue | None = None
    price_min: JsonValue | None = None
    price_max: JsonValue | None = None
    currency: str | None = None
    original_price: JsonValue | None = None
    availability: str | None = None
    image_url: str | None = None
    additional_images: tuple[str, ...] = ()
    variants: tuple[CommerceVariantRecord, ...] = ()


class CommerceListingRecord(PublicRecord):
    url: str
    title: str
    price: JsonValue | None = None
    image_url: str | None = None


class JobDetailRecord(PublicRecord):
    title: str
    company: str | None = None
    location: str | None = None
    apply_url: str | None = None
    description: str | None = None


class JobListingRecord(PublicRecord):
    title: str
    url: str
    company: str | None = None
    location: str | None = None


class ExtractionRequest(FrozenModel):
    surface: Surface
    capture: CaptureBundle
    artifact_reader: ArtifactReader = Field(exclude=True)
    requested_fields: tuple[str, ...] = ()
    max_records: int = 1


class ExtractionResult(FrozenModel):
    schema_version: Literal["extraction.v1"] = "extraction.v1"
    surface: Surface
    bundle_id: str = ""
    records: tuple[SerializeAsAny[PublicRecord], ...]
    evidence: tuple[Evidence, ...] = ()
    graph: EntityGraph = Field(default_factory=EntityGraph)
    target: TargetSelection = Field(default_factory=TargetSelection)
    findings: tuple[Finding, ...] = ()
    decisions: tuple[Decision, ...] = ()
    verdict: Literal[
        "success",
        "partial",
        "review",
        "invalid",
        "empty",
        "blocked",
        "error",
        "wrong_surface",
    ]
    retry_request: RetryRequest | None = None
    metrics: ExtractionMetrics = Field(default_factory=ExtractionMetrics)
