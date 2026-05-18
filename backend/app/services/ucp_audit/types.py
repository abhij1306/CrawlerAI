from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class UCPManifestResult:
    manifest_found: bool = False
    capabilities_declared: list[str] = field(default_factory=list)
    missing_required_capabilities: list[str] = field(default_factory=list)
    manifest_valid: bool = False
    raw_manifest: dict | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UCPSchemaScore:
    url: str = ""
    product_jsonld_found: bool = False
    required_fields_present: list[str] = field(default_factory=list)
    recommended_fields_present: list[str] = field(default_factory=list)
    ucp_fields_present: list[str] = field(default_factory=list)
    completeness_score: int = 0
    missing_required: list[str] = field(default_factory=list)
    missing_recommended: list[str] = field(default_factory=list)
    raw_additional_properties: list[dict] = field(default_factory=list)
    raw_product_type: str | None = None
    raw_offers: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class MetafieldCoverageReport:
    total_sampled: int = 0
    coverage_by_attribute: dict[str, float] = field(default_factory=dict)
    critical_gaps: list[str] = field(default_factory=list)
    worst_product_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaxonomyConsistencyReport:
    unique_raw_values: list[str] = field(default_factory=list)
    duplicate_clusters: list[list[str]] = field(default_factory=list)
    shallow_categories: list[str] = field(default_factory=list)
    consistency_score: int = 0


@dataclass(slots=True)
class UCPFinding:
    code: str
    dimension_id: str
    severity: str
    message: str = ""
    affected_count: int = 0
    count_kind: str = "items"
    affected_urls: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class VariantFidelityReport:
    products_with_variants_sampled: int = 0
    collapsed_offers_count: int = 0
    missing_sku_count: int = 0
    missing_availability_count: int = 0
    fidelity_score: int = 0
    findings: list[UCPFinding] = field(default_factory=list)


@dataclass(slots=True)
class PolicyReadabilityReport:
    structured_shipping_found: bool = False
    return_period_machine_readable: bool = False
    currency_is_iso4217: bool = False
    policy_page_http_accessible: bool = False
    readability_score: int = 0
    findings: list[UCPFinding] = field(default_factory=list)


@dataclass(slots=True)
class AgentViewDelta:
    url: str
    agent_extracted: dict[str, Any] = field(default_factory=dict)
    human_visible: dict[str, Any] = field(default_factory=dict)
    missing_in_agent_view: list[str] = field(default_factory=list)
    agent_only_signals: list[str] = field(default_factory=list)
    fidelity_score: float = 0.0


@dataclass(slots=True)
class UCPDimensionScore:
    dimension_id: str
    score: int
    status: str
    findings: list[UCPFinding] = field(default_factory=list)
    weight: float = 0.0


@dataclass(slots=True)
class UCPComplianceReport:
    domain: str
    audit_id: str
    overall_score: int
    dimension_scores: list[UCPDimensionScore]
    all_findings: list[UCPFinding]
    d_ucp1_gate_applied: bool
    agent_view_samples: list[AgentViewDelta] = field(default_factory=list)
