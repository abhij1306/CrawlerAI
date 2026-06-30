"""Frozen contract preference and runtime snapshot loading."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.knowledge_graph.contract_runtime import (
    contract_preferences,
    match_template,
    resolved_contract_outcomes,
)
from app.core.knowledge_graph.templates import (
    fingerprint_from_parts,
    fingerprint_template,
)
from app.extraction.contracts import (
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionResult,
    RejectedEvidence,
    ResolutionResult,
    SourceLocator,
)
from app.extraction.surfaces import Surface
from app.persistence.knowledge_graph import (
    ContractInput,
    EntityInput,
    load_runtime_snapshot,
    lock_site_version,
    upsert_contracts,
    upsert_entities,
)


def _evidence(
    evidence_id: str,
    collector_id: str,
    locator_value: str,
    fact_type: str,
    value: object = "test-value",
    *,
    subject_id: str = "entity-1",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle-1",
        artifact_id="art-1",
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=locator_value),
        directness="direct",
        confidence=0.9,
        subject_id=subject_id,
    )


def _decision(
    fact_type: str,
    accepted_ids: tuple[str, ...],
    *,
    rule_id: str = "FIRST_BY_PRIORITY",
    rejected: tuple[RejectedEvidence, ...] = (),
    status: str = "resolved",
    entity_id: str = "entity-1",
) -> Decision:
    return Decision(
        decision_id=f"dec-{fact_type}",
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=accepted_ids,
        rejected=rejected,
        finding_ids=(),
        rule_id=rule_id,
        status=status,  # type: ignore[arg-type]
    )


def _resolution(*decisions: Decision) -> ResolutionResult:
    return ResolutionResult(
        primary_product_entity_id="entity-1",
        primary_offer_entity_id=None,
        decisions=decisions,
        derived_facts=(),
        unresolved_fact_types=(),
        blocking_finding_ids=(),
    )


def _snapshot(
    fingerprint: str,
    surface: str,
    contracts: list[dict],
    route_pattern: str = "",
) -> dict:
    return {
        "surface": surface,
        "graph_version": 1,
        "templates": [
            {
                "fingerprint": fingerprint,
                "route_pattern": route_pattern,
                "template_key": f"example.com:{surface}:{fingerprint}",
                "contracts": contracts,
            }
        ],
    }


@pytest.mark.unit
def test_match_template_returns_template_on_fingerprint_hit() -> None:
    snapshot = _snapshot("fp-abc", "ecommerce_detail", [])
    result = match_template(snapshot, "fp-abc", "ecommerce_detail")
    assert result is not None
    assert result["fingerprint"] == "fp-abc"


@pytest.mark.unit
def test_match_template_returns_none_on_wrong_fingerprint() -> None:
    snapshot = _snapshot("fp-abc", "ecommerce_detail", [])
    assert match_template(snapshot, "fp-xyz", "ecommerce_detail") is None


@pytest.mark.unit
def test_match_template_returns_none_on_wrong_surface() -> None:
    snapshot = _snapshot("fp-abc", "ecommerce_detail", [])
    assert match_template(snapshot, "fp-abc", "ecommerce_listing") is None


@pytest.mark.unit
def test_match_template_falls_back_to_route_pattern() -> None:
    snapshot = _snapshot(
        "fp-empty",
        "ecommerce_detail",
        [],
        route_pattern="/products/{id}",
    )
    result = match_template(
        snapshot,
        "fp-runtime",
        "ecommerce_detail",
        url="https://example.com/products/widget-1",
    )
    assert result is not None
    assert result["fingerprint"] == "fp-empty"


@pytest.mark.unit
def test_match_template_merges_operator_route_contract_into_exact_template() -> None:
    snapshot = {
        "surface": "ecommerce_detail",
        "templates": [
            {
                "fingerprint": "fp-runtime",
                "route_pattern": "/products/{id}",
                "contracts": [
                    {
                        "canonical_field": "product.brand",
                        "selected_source": "jsonld:/brand",
                        "selection_origin": "generic",
                    }
                ],
            },
            {
                "fingerprint": "fp-generated",
                "route_pattern": "/products/{id}",
                "contracts": [
                    {
                        "canonical_field": "product.brand",
                        "selected_source": "css_recipe:.brand",
                        "selection_origin": "operator",
                    }
                ],
            },
        ],
    }

    result = match_template(
        snapshot,
        "fp-runtime",
        "ecommerce_detail",
        url="https://example.com/products/widget-1",
    )

    assert result is not None
    assert result["contracts"][0]["selected_source"] == "css_recipe:.brand"


@pytest.mark.unit
def test_match_template_returns_none_on_empty_snapshot() -> None:
    assert match_template({}, "fp-abc", "ecommerce_detail") is None


@pytest.mark.unit
def test_contract_preferences_return_source_matching_ids_only() -> None:
    evidence = (
        _evidence("generic", "opengraph", 'meta[property="og:title"]', "product.title"),
        _evidence(
            "preferred",
            "js_state",
            "/embedded/__NEXT_DATA__/1/props/pageProps/__APOLLO_STATE__/Product:new-id/name",
            "product.title",
        ),
    )
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": (
                    "js_state:/embedded/__NEXT_DATA__/0/props/pageProps/"
                    "__APOLLO_STATE__/Product:old-id/name"
                ),
                "selection_origin": "operator",
            }
        ],
    )

    preferences = contract_preferences(
        snapshot,
        "fp-1",
        "ecommerce_detail",
        evidence,
        frozenset({"product.title"}),
        frozenset(),
    )

    assert preferences == {"product.title": ("preferred",)}


@pytest.mark.unit
def test_contract_preferences_skip_user_controlled_fields() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title")
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
            }
        ],
    )

    assert (
        contract_preferences(
            snapshot,
            "fp-1",
            "ecommerce_detail",
            (ev,),
            frozenset({"product.title"}),
            frozenset({"product.title"}),
        )
        == {}
    )


@pytest.mark.unit
def test_contract_outcome_hit_requires_resolver_selected_preferred_candidate() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title", "Widget")
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
            }
        ],
    )

    outcomes = resolved_contract_outcomes(
        snapshot,
        "fp-1",
        "ecommerce_detail",
        (ev,),
        _resolution(
            _decision(
                "product.title",
                ("ev-1",),
                rule_id="CONTRACT_PREFERRED_SOURCE",
            )
        ),
        frozenset({"product.title"}),
        frozenset(),
    )

    assert len(outcomes) == 1
    assert outcomes[0].outcome == "hit"
    assert outcomes[0].applied is True


@pytest.mark.unit
def test_contract_outcome_fallback_when_preferred_unavailable_or_inadmissible() -> None:
    selected = _evidence("selected", "microdata", "/name", "product.title", "Widget")
    recommendation = _evidence(
        "recommendation",
        "jsonld",
        "/recommendations/0/name",
        "product.title",
        "Other Widget",
        subject_id="other-product",
    )
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/recommendations/0/name",
                "selection_origin": "operator",
            }
        ],
    )

    outcomes = resolved_contract_outcomes(
        snapshot,
        "fp-1",
        "ecommerce_detail",
        (selected, recommendation),
        _resolution(_decision("product.title", ("selected",))),
        frozenset({"product.title"}),
        frozenset(),
    )

    assert len(outcomes) == 1
    assert outcomes[0].outcome == "fallback"
    assert outcomes[0].applied is False


@pytest.mark.unit
def test_contract_outcome_miss_when_field_unresolved() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title")
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
            }
        ],
    )

    outcomes = resolved_contract_outcomes(
        snapshot,
        "fp-1",
        "ecommerce_detail",
        (ev,),
        _resolution(),
        frozenset({"product.title"}),
        frozenset(),
    )

    assert outcomes[0].outcome == "miss"
    assert outcomes[0].applied is False


@pytest.mark.unit
def test_fingerprint_from_parts_matches_fingerprint_template() -> None:
    collector_outcomes = (
        CollectorOutcome(
            collector_id="jsonld", outcome="produced_evidence", evidence_count=2
        ),
        CollectorOutcome(
            collector_id="opengraph", outcome="produced_evidence", evidence_count=1
        ),
    )
    evidence = (
        _evidence("ev-1", "jsonld", "/name", "product.title"),
        _evidence("ev-2", "opengraph", "/og:title", "product.title"),
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="b1",
        records=(),
        evidence=evidence,
        collector_outcomes=collector_outcomes,
        verdict="success",
    )
    url = "https://example.com/products/widget-123"
    surface = "ecommerce_detail"

    fp_parts = fingerprint_from_parts(url, surface, evidence, collector_outcomes)
    fp_result = fingerprint_template(url, surface, result)

    assert fp_parts == fp_result


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_runtime_snapshot_returns_empty_for_unknown_domain(
    db_session: AsyncSession,
) -> None:
    snapshot = await load_runtime_snapshot(
        db_session, domain="no-such-domain.com", surface="ecommerce_detail"
    )
    assert snapshot == {}


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_runtime_snapshot_returns_templates_and_contracts(
    db_session: AsyncSession,
) -> None:
    domain = "snapshot-test.com"
    surface = "ecommerce_detail"
    fingerprint = "fp-snap-1"
    template_key = f"{domain}:{surface}:{fingerprint}"

    await lock_site_version(db_session, domain)
    entity_map = await upsert_entities(
        db_session,
        [
            EntityInput(
                entity_type="page_template",
                canonical_key=template_key,
                canonical_name=f"{domain} {surface}",
                properties={
                    "domain": domain,
                    "surface": surface,
                    "fingerprint": fingerprint,
                },
            )
        ],
    )
    template_id = entity_map[("page_template", template_key)]

    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=template_id,
                surface=surface,
                canonical_field="product.title",
                selected_source="jsonld:/name",
                selection_origin="generic",
                resolver_rule="FIRST_BY_PRIORITY",
            ),
            ContractInput(
                template_id=template_id,
                surface=surface,
                canonical_field="product.price",
                selected_source="microdata:/price",
                selection_origin="operator",
                resolver_rule="PRICE_RULE",
            ),
        ],
    )
    await db_session.flush()

    snapshot = await load_runtime_snapshot(db_session, domain=domain, surface=surface)

    assert snapshot["surface"] == surface
    assert isinstance(snapshot["graph_version"], int)
    templates = snapshot["templates"]
    assert len(templates) == 1
    assert templates[0]["fingerprint"] == fingerprint
    contracts = {c["canonical_field"]: c for c in templates[0]["contracts"]}
    assert contracts["product.title"]["selected_source"] == "jsonld:/name"
    assert contracts["product.price"]["selection_origin"] == "operator"


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_runtime_snapshot_ignores_wrong_surface(
    db_session: AsyncSession,
) -> None:
    domain = "surface-filter.com"
    detail_key = f"{domain}:ecommerce_detail:fp-d1"
    listing_key = f"{domain}:ecommerce_listing:fp-l1"

    await lock_site_version(db_session, domain)
    entity_map = await upsert_entities(
        db_session,
        [
            EntityInput(
                entity_type="page_template",
                canonical_key=detail_key,
                canonical_name="detail template",
                properties={
                    "domain": domain,
                    "surface": "ecommerce_detail",
                    "fingerprint": "fp-d1",
                },
            ),
            EntityInput(
                entity_type="page_template",
                canonical_key=listing_key,
                canonical_name="listing template",
                properties={
                    "domain": domain,
                    "surface": "ecommerce_listing",
                    "fingerprint": "fp-l1",
                },
            ),
        ],
    )
    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=entity_map[("page_template", detail_key)],
                surface="ecommerce_detail",
                canonical_field="product.title",
                selected_source="jsonld:/name",
                selection_origin="generic",
                resolver_rule="FIRST",
            ),
            ContractInput(
                template_id=entity_map[("page_template", listing_key)],
                surface="ecommerce_listing",
                canonical_field="product.title",
                selected_source="css:h2",
                selection_origin="generic",
                resolver_rule="FIRST",
            ),
        ],
    )
    await db_session.flush()

    snapshot = await load_runtime_snapshot(
        db_session, domain=domain, surface="ecommerce_detail"
    )

    templates = snapshot["templates"]
    assert len(templates) == 1
    assert templates[0]["fingerprint"] == "fp-d1"
    assert all(c["selected_source"] != "css:h2" for c in templates[0]["contracts"])


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_runtime_snapshot_idempotent(
    db_session: AsyncSession,
) -> None:
    domain = "idempotent-snap.com"
    surface = "ecommerce_detail"
    fingerprint = "fp-idem"
    template_key = f"{domain}:{surface}:{fingerprint}"

    await lock_site_version(db_session, domain)
    entity_map = await upsert_entities(
        db_session,
        [
            EntityInput(
                entity_type="page_template",
                canonical_key=template_key,
                canonical_name="template",
                properties={
                    "domain": domain,
                    "surface": surface,
                    "fingerprint": fingerprint,
                },
            )
        ],
    )
    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=entity_map[("page_template", template_key)],
                surface=surface,
                canonical_field="product.title",
                selected_source="jsonld:/name",
                selection_origin="generic",
                resolver_rule="FIRST",
            )
        ],
    )
    await db_session.flush()

    snap1 = await load_runtime_snapshot(db_session, domain=domain, surface=surface)
    snap2 = await load_runtime_snapshot(db_session, domain=domain, surface=surface)
    assert snap1 == snap2
