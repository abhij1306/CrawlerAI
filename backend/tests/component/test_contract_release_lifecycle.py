"""test_contract_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.contract_runtime_test_support import (
    AsyncSession,
    CommerceDetailRecord,
    CrawlRun,
    CrawlUrlResult,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    ExtractionRecipe,
    ExtractionResult,
    FieldEvidenceState,
    SentinelObservation,
    Surface,
    _evidence,
    _merge_observed_sources,
    _sentinel_template_in_scope,
    build_release_payload,
    create_candidate_release_snapshot,
    ensure_template,
    load_release_payload,
    pytest,
    record_extraction_result,
    select,
    selector_rules_from_release,
    upsert_recipe,
)


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
        observation = SentinelObservation(
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
        )
        result = ExtractionResult(
            surface=Surface.ECOMMERCE_DETAIL,
            records=(
                CommerceDetailRecord(
                    title="Recipe Widget",
                    url="https://example.com/products/widget",
                ),
            ),
            verdict="success",
            sentinel_observations=(observation, observation),
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
        if index == 0:
            assert template.status != EXTRACTION_MEMORY_STATUS_SUSPENDED

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
    future_fingerprints = {row["fingerprint"] for row in future["templates"]}
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


@pytest.mark.unit
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
