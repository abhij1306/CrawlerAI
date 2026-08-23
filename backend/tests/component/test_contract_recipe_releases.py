"""test_contract_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.contract_runtime_test_support import (
    AsyncSession,
    CompiledExtractionRecipe,
    CrawlRun,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    RecipeCompileError,
    _recipe,
    activate_release_snapshot_for_run,
    active_release_snapshot_for_run,
    build_release_payload,
    compile_recipe_layers,
    create_candidate_release_snapshot,
    ensure_template,
    pytest,
    rollback_release_snapshot_for_run,
    selector_rules_from_release,
    upsert_recipe,
    uuid,
)


@pytest.mark.component
def test_release_selector_rules_normalize_canonical_field() -> None:
    payload = {
        "templates": [
            {
                "surface": "ecommerce_detail",
                "status": "active",
                "selector_rules": [
                    {"canonical_field": "title", "css_selector": ".title"}
                ],
            }
        ]
    }

    assert selector_rules_from_release(payload, surface="ecommerce_detail") == [
        {
            "canonical_field": "title",
            "field_name": "title",
            "css_selector": ".title",
        }
    ]


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
