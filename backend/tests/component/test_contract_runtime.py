"""Frozen contract preference and runtime snapshot loading."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.extraction_memory.contract_runtime import (
    contract_preferences,
    match_template,
    resolved_contract_outcomes,
)
from app.core.extraction_memory.templates import (
    fingerprint_from_parts,
    fingerprint_template,
)
from app.extraction.contracts import (
    CommerceDetailRecord,
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionResult,
    FieldEvidenceState,
    RejectedEvidence,
    ResolutionResult,
    SentinelObservation,
    SourceLocator,
)
from app.extraction.surfaces import Surface
from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.models.crawl_run import CrawlRun, CrawlUrlResult
from app.models.extraction_memory import CompiledExtractionRecipe, ExtractionRecipe
from app.persistence.extraction_memory import (
    RecipeCompileError,
    _merge_observed_sources,
    _sentinel_template_in_scope,
    activate_release_snapshot_for_run,
    active_release_snapshot_for_run,
    build_release_payload,
    compile_recipe_layers,
    create_candidate_release_snapshot,
    ensure_template,
    load_release_payload,
    record_extraction_result,
    rollback_release_snapshot_for_run,
    selector_rules_from_release,
    upsert_recipe,
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
def test_match_template_merges_all_route_only_operator_contracts() -> None:
    snapshot = {
        "surface": "ecommerce_detail",
        "templates": [
            {
                "fingerprint": "generic",
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
                "fingerprint": "operator",
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
        "no-exact-match",
        "ecommerce_detail",
        url="https://example.com/products/widget-1",
    )

    assert result is not None
    assert result["contracts"][0]["selected_source"] == "css_recipe:.brand"


def test_match_template_applies_operator_preference_across_routes() -> None:
    snapshot = {
        "surface": "ecommerce_detail",
        "templates": [
            {
                "fingerprint": "products-template",
                "route_pattern": "/products/{id}",
                "contracts": [
                    {
                        "canonical_field": "product.brand",
                        "selected_source": "css_recipe:.brand",
                        "selection_origin": "operator",
                    }
                ],
            },
            {
                "fingerprint": "shop-template",
                "route_pattern": "/shop/{id}",
                "contracts": [
                    {
                        "canonical_field": "product.brand",
                        "selected_source": "jsonld:/brand",
                        "selection_origin": "generic",
                    }
                ],
            },
        ],
    }

    result = match_template(
        snapshot,
        "shop-template",
        "ecommerce_detail",
        url="https://example.com/shop/widget-1",
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
def test_contract_outcome_checks_every_accepted_evidence_id() -> None:
    generic = _evidence("generic", "microdata", "/name", "product.title", "Widget")
    preferred = _evidence("preferred", "jsonld", "/name", "product.title", "Widget")
    snapshot = _snapshot(
        "fp-1",
        "ecommerce_detail",
        [
            {
                "canonical_field": "product.title",
                "selected_source": "jsonld:/name",
                "selection_origin": "operator",
            }
        ],
    )

    outcomes = resolved_contract_outcomes(
        snapshot,
        "fp-1",
        "ecommerce_detail",
        (generic, preferred),
        _resolution(
            _decision(
                "product.title",
                ("generic", "preferred"),
                rule_id="CONTRACT_PREFERRED_SOURCE",
            )
        ),
        frozenset({"product.title"}),
        frozenset(),
    )

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


@pytest.mark.unit
def test_fingerprint_ignores_values_but_changes_with_source_shape() -> None:
    outcomes = (
        CollectorOutcome(
            collector_id="jsonld", outcome="produced_evidence", evidence_count=1
        ),
    )

    original = fingerprint_from_parts(
        "https://example.com/products/widget-123",
        "ecommerce_detail",
        (_evidence("ev-1", "jsonld", "/name", "product.title", "Widget"),),
        outcomes,
    )
    changed_value = fingerprint_from_parts(
        "https://example.com/products/widget-123",
        "ecommerce_detail",
        (_evidence("ev-2", "jsonld", "/name", "product.title", "Different"),),
        outcomes,
    )
    changed_source = fingerprint_from_parts(
        "https://example.com/products/widget-123",
        "ecommerce_detail",
        (_evidence("ev-3", "jsonld", "/product/name", "product.title", "Widget"),),
        outcomes,
    )

    assert changed_value == original
    assert changed_source != original


def _recipe(layer: str, kind: str, payload: dict) -> ExtractionRecipe:
    return ExtractionRecipe(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        layer=layer,
        kind=kind,
        payload=payload,
        version=1,
    )


@pytest.mark.unit
def test_compile_recipe_layers_allows_higher_layer_override_without_mutating_parent() -> (
    None
):
    parent_rule = {"field_name": "title", "css_selector": "h1"}
    compiled = compile_recipe_layers(
        [
            _recipe(
                EXTRACTION_RECIPE_LAYER_DOMAIN,
                EXTRACTION_RECIPE_KIND_SELECTORS,
                {"rules": [parent_rule]},
            ),
            _recipe(
                EXTRACTION_RECIPE_LAYER_TEMPLATE,
                EXTRACTION_RECIPE_KIND_SELECTORS,
                {"rules": [{"field_name": "title", "css_selector": ".pdp-title"}]},
            ),
        ]
    )

    assert compiled["selector_rules"] == [
        {"field_name": "title", "css_selector": ".pdp-title"}
    ]
    assert parent_rule == {"field_name": "title", "css_selector": "h1"}


@pytest.mark.unit
def test_compile_recipe_layers_fails_ambiguous_same_layer_override() -> None:
    with pytest.raises(RecipeCompileError):
        compile_recipe_layers(
            [
                _recipe(
                    EXTRACTION_RECIPE_LAYER_TEMPLATE,
                    EXTRACTION_RECIPE_KIND_SELECTORS,
                    {"rules": [{"field_name": "title", "css_selector": "h1"}]},
                ),
                _recipe(
                    EXTRACTION_RECIPE_LAYER_TEMPLATE,
                    EXTRACTION_RECIPE_KIND_SELECTORS,
                    {"rules": [{"field_name": "title", "css_selector": "h2"}]},
                ),
            ]
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_release_payload_returns_empty_templates_for_unknown_domain(
    db_session: AsyncSession,
) -> None:
    snapshot = await build_release_payload(
        db_session, domain="unknown.example", surface="ecommerce_detail"
    )
    assert snapshot == {
        "schema_version": "release.v2",
        "domain": "unknown.example",
        "surface": "ecommerce_detail",
        "templates": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_release_payload_contains_compiled_contract_recipe(
    db_session: AsyncSession,
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="fp-runtime",
        route_pattern="/products/{id}",
    )
    _, compiled = await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={
            "contracts": [
                {
                    "canonical_field": "product.brand",
                    "selected_source": "jsonld:/brand",
                    "selection_origin": "operator",
                }
            ]
        },
    )
    await db_session.commit()

    snapshot = await build_release_payload(
        db_session, domain="example.com", surface="ecommerce_detail"
    )

    assert snapshot["templates"][0]["fingerprint"] == "fp-runtime"
    assert (
        snapshot["templates"][0]["contracts"][0]["selected_source"] == "jsonld:/brand"
    )
    assert await db_session.get(CompiledExtractionRecipe, compiled.id) is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_release_payload_freezes_selector_recipes(
    db_session: AsyncSession,
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="domain-default",
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer="domain",
        kind="selectors",
        payload={"rules": [{"field_name": "title", "css_selector": "h1"}]},
    )
    frozen = await build_release_payload(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer="domain",
        kind="selectors",
        payload={"rules": [{"field_name": "title", "css_selector": "h2"}]},
    )

    assert (
        selector_rules_from_release(frozen, surface="ecommerce_detail")[0][
            "css_selector"
        ]
        == "h1"
    )
    assert frozen["templates"][0]["compiled_recipe"]["selector_rules"] == [
        {"field_name": "title", "css_selector": "h1"}
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_release_snapshot_activation_and_rollback_are_atomic(
    db_session: AsyncSession, test_user
) -> None:
    db_session.add(
        CrawlRun(
            id=901,
            user_id=test_user.id,
            run_type="crawl",
            url="https://example.com/products/widget",
            status="running",
            surface="ecommerce_detail",
        )
    )
    await db_session.flush()

    baseline_template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="baseline",
    )
    await upsert_recipe(
        db_session,
        template=baseline_template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload={"rules": [{"field_name": "title", "css_selector": "h1"}]},
    )
    baseline = await create_candidate_release_snapshot(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    await activate_release_snapshot_for_run(
        db_session, run_id=901, release_snapshot_id=baseline.id
    )

    candidate_template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="candidate",
    )
    await upsert_recipe(
        db_session,
        template=candidate_template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload={"rules": [{"field_name": "title", "css_selector": ".pdp-title"}]},
    )
    candidate = await create_candidate_release_snapshot(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    await activate_release_snapshot_for_run(
        db_session, run_id=901, release_snapshot_id=candidate.id
    )

    active = await active_release_snapshot_for_run(db_session, run_id=901)
    assert active is not None
    assert active.id == candidate.id
    assert baseline.run_id is None
    assert baseline.payload["templates"][0]["fingerprint"] == "baseline"

    with pytest.raises(ValueError):
        await activate_release_snapshot_for_run(
            db_session,
            run_id=901,
            release_snapshot_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        )
    active_after_failed_activation = await active_release_snapshot_for_run(
        db_session, run_id=901
    )
    assert active_after_failed_activation is not None
    assert active_after_failed_activation.id == candidate.id

    incompatible = await create_candidate_release_snapshot(
        db_session, domain="other.example", surface="ecommerce_detail"
    )
    with pytest.raises(ValueError, match="incompatible"):
        await activate_release_snapshot_for_run(
            db_session, run_id=901, release_snapshot_id=incompatible.id
        )
    active_after_incompatible = await active_release_snapshot_for_run(
        db_session, run_id=901
    )
    assert active_after_incompatible is not None
    assert active_after_incompatible.id == candidate.id

    await rollback_release_snapshot_for_run(
        db_session, run_id=901, target_release_snapshot_id=baseline.id
    )

    rolled_back = await active_release_snapshot_for_run(db_session, run_id=901)
    assert rolled_back is not None
    assert rolled_back.id == baseline.id
    assert candidate.run_id is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_confirmed_critical_sentinel_drift_suspends_template_and_fallback(
    db_session: AsyncSession, test_user
) -> None:
    run = CrawlRun(
        id=902,
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/products/widget",
        status="running",
        surface="ecommerce_detail",
    )
    db_session.add(run)
    await db_session.flush()

    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="known-template",
        route_pattern="/products/{id}",
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload={"rules": [{"field_name": "title", "css_selector": ".recipe-title"}]},
    )
    release = await create_candidate_release_snapshot(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    await db_session.flush()

    for index in range(2):
        url_result = CrawlUrlResult(
            run_id=run.id,
            requested_url=f"https://example.com/products/widget-{index}",
            normalized_url=f"https://example.com/products/widget-{index}",
            final_url=f"https://example.com/products/widget-{index}",
            surface="ecommerce_detail",
            generation=1,
        )
        db_session.add(url_result)
        await db_session.flush()
        result = ExtractionResult(
            surface=Surface.ECOMMERCE_DETAIL,
            records=(
                CommerceDetailRecord(
                    title="Recipe Widget",
                    url="https://example.com/products/widget",
                ),
            ),
            verdict="success",
            sentinel_observations=(
                SentinelObservation(
                    challenger="deterministic",
                    state="critical_drift",
                    template_id=str(template.id),
                    release_snapshot_id=str(release.id),
                    sample_rate=1.0,
                    recipe_verdict="success",
                    challenger_verdict="success",
                    recipe_record_count=1,
                    challenger_record_count=0,
                    disagreement_classes=("record_count",),
                    evidence_ids=("e1", "e2"),
                    diagnostic="Sentinel deterministic challenger is critical_drift.",
                    next_action="confirm_drift_before_suspending_template",
                ),
            ),
        )
        await record_extraction_result(
            db_session,
            run_id=run.id,
            url_result_id=url_result.id,
            release_snapshot_id=release.id,
            url=url_result.final_url,
            surface="ecommerce_detail",
            result=result,
        )

    await db_session.flush()
    await db_session.refresh(template)

    # CRITICAL 2: the stored release snapshot is frozen. Reloading the in-flight
    # run's snapshot returns the payload EXACTLY as created — suspending the
    # template later must not mutate a run already in progress.
    frozen = await load_release_payload(db_session, release.id)
    assert template.status == EXTRACTION_MEMORY_STATUS_SUSPENDED
    assert frozen["templates"][0]["status"] != EXTRACTION_MEMORY_STATUS_SUSPENDED
    assert frozen == release.payload

    # A FUTURE snapshot built after suspension excludes the suspended template,
    # so the next run falls through to the floors (and can re-learn).
    future = await build_release_payload(
        db_session, domain=template.domain, surface="ecommerce_detail"
    )
    future_fingerprints = {
        row["fingerprint"] for row in future["templates"]
    }
    assert template.fingerprint not in future_fingerprints
    # The suspended template held the only selector rules, so future crawls fall
    # through to the floors.
    assert selector_rules_from_release(future, surface="ecommerce_detail") == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_successful_extraction_records_observed_field_preference(
    db_session: AsyncSession, test_user
) -> None:
    run = CrawlRun(
        id=903,
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/products/widget",
        status="running",
        surface="ecommerce_detail",
    )
    db_session.add(run)
    await db_session.flush()
    url_result = CrawlUrlResult(
        run_id=run.id,
        requested_url=run.url,
        normalized_url=run.url,
        final_url=run.url,
        surface="ecommerce_detail",
        generation=1,
    )
    db_session.add(url_result)
    await db_session.flush()
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        records=(CommerceDetailRecord(title="Widget", url=run.url),),
        evidence=(
            _evidence(
                "ev-title",
                "jsonld",
                "/products/123/name",
                "product.title",
                "Widget",
            ),
        ),
        field_states=(
            FieldEvidenceState(
                field="title",
                state="captured_published",
                evidence_ids=("ev-title",),
            ),
        ),
        verdict="success",
    )

    await record_extraction_result(
        db_session,
        run_id=run.id,
        url_result_id=url_result.id,
        release_snapshot_id=None,
        url=url_result.final_url,
        surface="ecommerce_detail",
        result=result,
    )

    recipe = (
        await db_session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS
            )
        )
    ).scalar_one()
    assert recipe.payload["contracts"] == [
        {
            "id": recipe.payload["contracts"][0]["id"],
            "template_id": str(recipe.template_id),
            "surface": "ecommerce_detail",
            "canonical_field": "product.title",
            "candidates": [
                {
                    "source": "jsonld:/products/{index}/name",
                    "success_count": 1,
                }
            ],
            "latest_values": [],
            "success_count": 1,
            "rejection_count": 0,
            "resolver_rule": "observed_published_evidence",
            "selected_source": "jsonld:/products/{index}/name",
            "selection_origin": "generic",
            "selection_history": [
                {
                    "selected_source": "jsonld:/products/{index}/name",
                    "source": "successful_crawl",
                }
            ],
            "status": "active",
        }
    ]


def test_observed_source_merge_uses_canonical_source_keys() -> None:
    contract = {
        "candidates": [
            {"source": "jsonld:/products/0/name", "success_count": 1},
        ],
        "selected_source": "jsonld:/products/0/name",
        "selection_origin": "generic",
        "success_count": 1,
        "rejection_count": 0,
    }

    _merge_observed_sources(contract, ["jsonld:/products/{index}/name"])

    assert contract["candidates"] == [
        {"source": "jsonld:/products/{index}/name", "success_count": 2}
    ]
    assert contract["selected_source"] == "jsonld:/products/{index}/name"
    assert contract["rejection_count"] == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_recipe_merge_payload_preserves_existing_contracts(
    db_session: AsyncSession,
) -> None:
    template = await ensure_template(
        db_session,
        domain="shop.test",
        surface="ecommerce_detail",
        fingerprint="merge-payload",
        route_pattern="/products/{id}",
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": [{"canonical_field": "product.title"}]},
    )
    recipe, _compiled = await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": []},
        merge_payload=lambda existing: {
            "contracts": [
                *list(existing.get("contracts", [])),
                {"canonical_field": "product.price"},
            ]
        },
    )

    assert recipe.payload["contracts"] == [
        {"canonical_field": "product.title"},
        {"canonical_field": "product.price"},
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_sentinel_template_scope_rejects_unrelated_route(
    db_session: AsyncSession,
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="unrelated-template",
        route_pattern="/categories/{id}",
    )

    assert (
        await _sentinel_template_in_scope(
            db_session,
            template_id=template.id,
            domain="example.com",
            surface="ecommerce_detail",
            route_pattern="/products/{id}",
        )
        is None
    )
