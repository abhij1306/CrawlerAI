"""test_crawl_service cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_service_test_support import (
    AsyncSession,
    CrawlerConfigurationError,
    create_crawl_run,
    load_domain_run_profile,
    normalize_crawl_settings,
    normalize_domain_run_profile,
    note_acquisition_contract_failure,
    pytest,
    record_acquisition_contract_outcome,
    resolve_url_acquisition_recipe,
    save_domain_run_profile,
)


@pytest.fixture(autouse=True)
def _allow_test_profile_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        "app.crawl.profile.repository._source_run_is_admin_owned",
        _allowed,
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_rejects_invalid_traversal_mode(
    db_session: AsyncSession,
    test_user,
) -> None:
    with pytest.raises(
        CrawlerConfigurationError,
        match="Unsupported traversal_mode",
    ):
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/collections/widgets",
                "surface": "ecommerce_listing",
                "settings": {
                    "advanced_enabled": True,
                    "fetch_profile": {
                        "traversal_mode": "unsupported_mode",
                    },
                },
            },
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_contract_marks_stale_after_repeated_quality_failures(
    db_session: AsyncSession,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "acquisition_contract": {
                "preferred_browser_engine": "real_chrome",
                "prefer_browser": True,
                "handoff_eligible": True,
                "handoff_cookie_engine": "real_chrome",
                "last_quality_success": {
                    "method": "browser",
                    "browser_engine": "real_chrome",
                    "record_count": 1,
                    "field_coverage": {
                        "requested": ["title"],
                        "found": ["title"],
                        "missing": [],
                    },
                    "source_run_id": 12,
                    "timestamp": "2026-04-30T00:00:00+00:00",
                },
            },
        },
        source_run_id=12,
    )
    await db_session.commit()

    first = await note_acquisition_contract_failure(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        threshold=2,
    )
    second = await note_acquisition_contract_failure(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        threshold=2,
    )

    assert first["acquisition_contract"]["stale_after_failures"] == {
        "failure_count": 1,
        "stale": False,
    }
    assert second["acquisition_contract"]["stale_after_failures"] == {
        "failure_count": 2,
        "stale": True,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_contract_failure_tolerates_bad_source_run_id(
    db_session: AsyncSession,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "source_run_id": "bad-value",
            "acquisition_contract": {
                "last_quality_success": {"method": "browser"},
                "stale_after_failures": {"failure_count": 0, "stale": False},
            },
        },
        source_run_id=1,
    )

    updated = await note_acquisition_contract_failure(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        threshold=1,
    )

    assert updated is not None
    assert updated["acquisition_contract"]["stale_after_failures"] == {
        "failure_count": 1,
        "stale": True,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_contract_outcome_can_skip_non_acquisition_failures(
    db_session: AsyncSession,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "acquisition_contract": {
                "preferred_browser_engine": "real_chrome",
                "prefer_browser": True,
                "handoff_eligible": True,
                "handoff_cookie_engine": "real_chrome",
                "last_quality_success": {
                    "method": "browser",
                    "browser_engine": "real_chrome",
                    "record_count": 1,
                    "field_coverage": {
                        "requested": ["title"],
                        "found": ["title"],
                        "missing": [],
                    },
                    "source_run_id": 12,
                    "timestamp": "2026-04-30T00:00:00+00:00",
                },
            },
        },
        source_run_id=12,
    )
    await db_session.commit()

    await record_acquisition_contract_outcome(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        source_run_id=13,
        method="browser",
        browser_engine="real_chrome",
        browser_diagnostics={},
        requested_fields=["title"],
        records=[],
        persisted_count=0,
        verdict="blocked",
        blocked=True,
    )

    row = await load_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )
    assert row is not None
    assert row.profile["acquisition_contract"]["stale_after_failures"] == {
        "failure_count": 0,
        "stale": False,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_url_acquisition_recipe_reuses_saved_profile_for_batch_defaults(
    db_session: AsyncSession,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "fetch_profile": {
                "fetch_mode": "browser_only",
                "request_delay_ms": 1200,
            },
            "locality_profile": {
                "geo_country": "IN",
            },
            "diagnostics_profile": {
                "capture_network": "matched_only",
            },
            "acquisition_contract": {
                "preferred_browser_engine": "real_chrome",
                "prefer_browser": True,
                "handoff_eligible": True,
                "handoff_cookie_engine": "real_chrome",
            },
        },
        source_run_id=91,
    )
    await db_session.commit()

    resolved = await resolve_url_acquisition_recipe(
        db_session,
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        explicit_settings=normalize_crawl_settings({}),
    )

    assert resolved["fetch_profile"]["fetch_mode"] == "browser_only"
    assert resolved["fetch_profile"]["request_delay_ms"] == 1200
    assert resolved["locality_profile"]["geo_country"] == "IN"
    assert resolved["diagnostics_profile"]["capture_network"] == "matched_only"
    assert resolved["acquisition_contract"]["preferred_browser_engine"] == "real_chrome"
    assert resolved["acquisition_contract"]["handoff_eligible"] is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_record_acquisition_contract_outcome_saves_internal_api_endpoint(
    db_session: AsyncSession,
) -> None:
    await record_acquisition_contract_outcome(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        source_run_id=92,
        method="browser",
        browser_engine="patchright",
        browser_diagnostics={"network_payload_count": 1},
        requested_fields=["title", "price"],
        records=[
            {
                "title": "Replay Widget",
                "price": 19.99,
                "_field_sources": {
                    "title": ["network_payload"],
                    "price": ["network_payload"],
                },
            }
        ],
        persisted_count=1,
        verdict="success",
        blocked=False,
        page_url="https://example.com/products/replay-widget",
        network_payloads=[
            {
                "url": "https://example.com/api/products/replay-widget.json",
                "method": "GET",
                "status": 200,
                "content_type": "application/json",
                "endpoint_type": "product_api",
                "endpoint_family": "generic",
                "body": {
                    "product": {
                        "title": "Replay Widget",
                        "price": {"amount": "19.99"},
                        "sku": "RW-100",
                        "url": "https://example.com/products/replay-widget",
                    }
                },
            }
        ],
    )

    row = await load_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert row is not None
    assert row.profile["internal_api_endpoints"] == [
        {
            "url": "https://example.com/api/products/replay-widget.json",
            "method": "GET",
            "endpoint_type": "product_api",
            "endpoint_family": "generic",
            "source_run_id": 92,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_record_acquisition_contract_outcome_tracks_requested_custom_fields(
    db_session: AsyncSession,
) -> None:
    await record_acquisition_contract_outcome(
        db_session,
        domain="sigmaaldrich.com",
        surface="ecommerce_detail",
        source_run_id=93,
        method="browser",
        browser_engine="patchright",
        browser_diagnostics={"extraction_source": "rendered_dom"},
        requested_fields=[
            "cas_number",
            "molecular_formula",
            "molecular_weight",
            "price",
            "title",
            "image_url",
        ],
        records=[
            {
                "title": "Sodium Chloride",
                "cas_number": "7647-14-5",
                "molecular_formula": "NaCl",
                "molecular_weight": "58.44",
                "price": "12.00",
                "image_url": "https://example.com/nacl.jpg",
            }
        ],
        persisted_count=1,
        verdict="success",
        blocked=False,
        page_url="https://www.sigmaaldrich.com/US/en/product/sial/s9888",
    )

    row = await load_domain_run_profile(
        db_session,
        domain="sigmaaldrich.com",
        surface="ecommerce_detail",
    )

    assert row is not None
    contract = row.profile["acquisition_contract"]
    assert contract["prefer_browser"] is True
    assert contract["required_rendering"] is True
    coverage = contract["last_quality_success"]["field_coverage"]
    assert coverage["missing"] == []
    assert "cas_number" in coverage["found"]
    assert "molecular_formula" in coverage["found"]
    assert "molecular_weight" in coverage["found"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_record_acquisition_contract_outcome_counts_empty_detail_failure(
    db_session: AsyncSession,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "acquisition_contract": {
                "preferred_browser_engine": "real_chrome",
                "prefer_browser": True,
                "handoff_eligible": True,
                "handoff_cookie_engine": "real_chrome",
                "last_quality_success": {
                    "method": "browser",
                    "browser_engine": "real_chrome",
                    "record_count": 1,
                    "field_coverage": {
                        "requested": ["title"],
                        "found": ["title"],
                        "missing": [],
                    },
                    "source_run_id": 12,
                    "timestamp": "2026-04-30T00:00:00+00:00",
                },
            },
        },
        source_run_id=12,
    )
    await db_session.commit()

    await record_acquisition_contract_outcome(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        source_run_id=13,
        method="browser",
        browser_engine="real_chrome",
        browser_diagnostics={},
        requested_fields=["title"],
        records=[],
        persisted_count=0,
        verdict="empty",
        blocked=False,
    )

    row = await load_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )
    assert row is not None
    assert row.profile["acquisition_contract"]["stale_after_failures"] == {
        "failure_count": 1,
        "stale": False,
    }


@pytest.mark.component
def test_normalize_domain_run_profile_rejects_invalid_source_run_id() -> None:
    with pytest.raises(ValueError, match="source_run_id must be a positive integer"):
        normalize_domain_run_profile({}, source_run_id="invalid")  # type: ignore[arg-type]
