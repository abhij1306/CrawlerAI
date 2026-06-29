"""Slice 7 tests: frozen contract execution and runtime snapshot loading.

Covers match_template, apply_contracts (hit/miss/fallback/stale_source/
override_miss), load_runtime_snapshot DB query, and fingerprint_from_parts
consistency with fingerprint_template.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.knowledge_graph.contract_runtime import apply_contracts, match_template
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(
    evidence_id: str,
    collector_id: str,
    locator_value: str,
    fact_type: str,
    value: object = "test-value",
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
        subject_id="prod-1",
    )


def _decision(
    fact_type: str,
    accepted_ids: tuple[str, ...],
    rejected: tuple[RejectedEvidence, ...] = (),
    status: str = "resolved",
) -> Decision:
    return Decision(
        decision_id=f"dec-{fact_type}",
        entity_id="entity-1",
        fact_type=fact_type,
        accepted_evidence_ids=accepted_ids,
        rejected=rejected,
        finding_ids=(),
        rule_id="FIRST_BY_PRIORITY",
        status=status,  # type: ignore[arg-type]
    )


def _resolution(*decisions: Decision) -> ResolutionResult:
    return ResolutionResult(
        primary_product_entity_id="entity-1",
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


# ---------------------------------------------------------------------------
# match_template
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# apply_contracts — hit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_hit_repoints_decision_to_preferred_source() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title", "Widget")
    decision = _decision("product.title", ("ev-1",))
    resolution = _resolution(decision)
    source = "jsonld:/name"
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": source,
                "selection_origin": "generic",
                "resolver_rule": "FIRST_BY_PRIORITY",
            }
        ],
    )

    new_resolution, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert len(outcomes) == 1
    assert outcomes[0].outcome == "hit"
    assert outcomes[0].applied is True
    assert outcomes[0].field == "product.title"
    # Decision re-pointed to the same evidence (it was already preferred)
    updated = {d.fact_type: d for d in new_resolution.decisions}
    assert updated["product.title"].accepted_evidence_ids == ("ev-1",)


@pytest.mark.unit
def test_apply_contracts_treats_requested_field_alias_as_fact_type() -> None:
    selector = ".product-detail-primary-brand-value-that-is-longer-than-eighty-characters-1234567890"
    evidence = (
        _evidence("ev-1", "jsonld", "/brand", "product.brand", "Generic"),
        _evidence("ev-2", "css_recipe", selector, "product.brand", "ACME"),
    )
    resolution = _resolution(_decision("product.brand", ("ev-1",)))
    snapshot = _snapshot(
        "fp-abc",
        "ecommerce_detail",
        [
            {
                "canonical_field": "brand",
                "selected_source": f"css_recipe:{selector}",
                "selection_origin": "operator",
                "resolver_rule": "operator_selector",
            }
        ],
    )

    new_resolution, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-abc",
        surface="ecommerce_detail",
        evidence=evidence,
        resolution=resolution,
        requested_fields=frozenset({"brand"}),
        user_controlled_fields=frozenset(),
    )

    assert new_resolution.decisions[0].accepted_evidence_ids == ("ev-2",)
    assert outcomes[0].outcome == "hit"
    assert outcomes[0].field == "product.brand"


@pytest.mark.unit
def test_apply_contracts_hit_repoints_when_alternative_preferred() -> None:
    """Contract prefers jsonld but generic chose microdata; engine re-points."""
    ev_jsonld = _evidence("ev-jsonld", "jsonld", "/name", "product.title", "Widget")
    ev_micro = _evidence("ev-micro", "microdata", "/name", "product.title", "Widget")
    # Generic resolution accepted microdata
    decision = _decision("product.title", ("ev-micro",))
    resolution = _resolution(decision)
    source = "jsonld:/name"
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": source,
                "selection_origin": "operator",
                "resolver_rule": "PREFERRED",
            }
        ],
    )

    new_resolution, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev_jsonld, ev_micro),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes[0].outcome == "hit"
    assert outcomes[0].applied is True
    updated = {d.fact_type: d for d in new_resolution.decisions}
    assert updated["product.title"].accepted_evidence_ids == ("ev-jsonld",)


# ---------------------------------------------------------------------------
# apply_contracts — miss (field unresolved)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_miss_when_field_has_no_decision() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title")
    # Resolution has no decision for product.title
    resolution = _resolution()
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
                "resolver_rule": "FIRST",
            }
        ],
    )

    _, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes[0].outcome == "miss"
    assert outcomes[0].applied is False


# ---------------------------------------------------------------------------
# apply_contracts — fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_fallback_when_preferred_source_absent() -> None:
    """Preferred source not present in evidence; generic resolution is kept."""
    ev = _evidence("ev-micro", "microdata", "/name", "product.title", "Widget")
    decision = _decision("product.title", ("ev-micro",))
    resolution = _resolution(decision)
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
                "resolver_rule": "FIRST",
            }
        ],
    )

    _, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes[0].outcome == "fallback"
    assert outcomes[0].applied is False


# ---------------------------------------------------------------------------
# apply_contracts — override_miss (operator source absent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_override_miss_for_operator_source_absent() -> None:
    ev = _evidence("ev-micro", "microdata", "/name", "product.title", "Widget")
    decision = _decision("product.title", ("ev-micro",))
    resolution = _resolution(decision)
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "operator",
                "resolver_rule": "PREFERRED",
            }
        ],
    )

    _, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes[0].outcome == "override_miss"
    assert outcomes[0].applied is False


# ---------------------------------------------------------------------------
# apply_contracts — stale_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_stale_source_when_preferred_is_rejected() -> None:
    """Preferred source is in evidence but was rejected by the resolver."""
    ev_jsonld = _evidence("ev-jsonld", "jsonld", "/name", "product.title", "Widget")
    ev_micro = _evidence("ev-micro", "microdata", "/name", "product.title", "Widget")
    decision = Decision(
        decision_id="dec-title",
        entity_id="entity-1",
        fact_type="product.title",
        accepted_evidence_ids=("ev-micro",),
        rejected=(RejectedEvidence(evidence_id="ev-jsonld", reason="low_confidence"),),
        finding_ids=(),
        rule_id="FIRST_BY_PRIORITY",
        status="resolved",
    )
    resolution = _resolution(decision)
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "generic",
                "resolver_rule": "FIRST",
            }
        ],
    )

    _, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev_jsonld, ev_micro),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes[0].outcome == "stale_source"
    assert outcomes[0].applied is False


# ---------------------------------------------------------------------------
# apply_contracts — user_controlled_fields skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_skips_user_controlled_fields() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title", "Widget")
    decision = _decision("product.title", ("ev-1",))
    resolution = _resolution(decision)
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "microdata:/name",
                "selection_origin": "generic",
                "resolver_rule": "FIRST",
            }
        ],
    )

    new_resolution, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-1",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(["product.title"]),
    )

    # No outcomes emitted, resolution unchanged
    assert outcomes == ()
    assert new_resolution is resolution


# ---------------------------------------------------------------------------
# apply_contracts — no matching template
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_apply_contracts_noop_on_fingerprint_miss() -> None:
    ev = _evidence("ev-1", "jsonld", "/name", "product.title")
    decision = _decision("product.title", ("ev-1",))
    resolution = _resolution(decision)
    snapshot = _snapshot("fp-OTHER", "ecommerce_detail", [])

    new_resolution, outcomes = apply_contracts(
        snapshot=snapshot,
        fingerprint="fp-NOMATCH",
        surface="ecommerce_detail",
        evidence=(ev,),
        resolution=resolution,
        requested_fields=frozenset(["product.title"]),
        user_controlled_fields=frozenset(),
    )

    assert outcomes == ()
    assert new_resolution is resolution


# ---------------------------------------------------------------------------
# fingerprint_from_parts consistency
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fingerprint_from_parts_matches_fingerprint_template() -> None:
    """fingerprint_from_parts and fingerprint_template produce identical hashes."""
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


# ---------------------------------------------------------------------------
# load_runtime_snapshot — DB component tests
# ---------------------------------------------------------------------------


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
    assert "product.title" in contracts
    assert contracts["product.title"]["selected_source"] == "jsonld:/name"
    assert contracts["product.title"]["selection_origin"] == "generic"
    assert "product.price" in contracts
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
    template_id = entity_map[("page_template", detail_key)]
    listing_id = entity_map[("page_template", listing_key)]

    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.title",
                selected_source="jsonld:/name",
                selection_origin="generic",
                resolver_rule="FIRST",
            ),
            ContractInput(
                template_id=listing_id,
                surface="ecommerce_listing",
                canonical_field="product.title",
                selected_source="css:h2",
                selection_origin="generic",
                resolver_rule="FIRST",
            ),
        ],
    )
    await db_session.flush()

    # Request detail surface — listing template contracts must not appear
    snapshot = await load_runtime_snapshot(
        db_session, domain=domain, surface="ecommerce_detail"
    )
    templates = snapshot["templates"]
    assert len(templates) == 1
    assert templates[0]["fingerprint"] == "fp-d1"
    for contract in templates[0]["contracts"]:
        assert contract["selected_source"] != "css:h2"


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_runtime_snapshot_idempotent(
    db_session: AsyncSession,
) -> None:
    """Calling load_runtime_snapshot twice on same data returns identical result."""
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
