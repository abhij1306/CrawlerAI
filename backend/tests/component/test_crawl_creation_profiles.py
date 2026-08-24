"""test_crawl_service cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_service_test_support import (
    AsyncSession,
    ReviewPromotion,
    apply_acquisition_contract_to_profile,
    build_success_acquisition_contract,
    create_crawl_run,
    dependencies_module,
    normalize_acquisition_contract,
    pytest,
    save_domain_run_profile,
    settings,
)


@pytest.fixture(autouse=True)
def _allow_test_profile_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        "app.crawl.profile.repository._source_run_is_admin_owned",
        _allowed,
    )


@pytest.mark.component
def test_get_run_dispatcher_reuses_dispatch_mode_singletons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies_module._run_dispatchers.clear()
    try:
        monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
        local_dispatcher = dependencies_module.get_run_dispatcher()

        assert dependencies_module.get_run_dispatcher() is local_dispatcher

        monkeypatch.setattr(settings, "celery_dispatch_enabled", True)
        celery_dispatcher = dependencies_module.get_run_dispatcher()

        assert dependencies_module.get_run_dispatcher() is celery_dispatcher
        assert celery_dispatcher is not local_dispatcher
    finally:
        dependencies_module._run_dispatchers.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_sets_pending_and_preserves_surface(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
        },
    )

    assert run.id is not None
    assert run.status == "pending"
    assert run.surface == "ecommerce_detail"
    assert run.result_summary["url_count"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_batch_uses_settings_urls_for_primary_url_and_count(
    db_session: AsyncSession,
    test_user,
) -> None:
    urls = [
        "https://example.com/products/one",
        "https://example.com/products/two",
    ]

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {"urls": urls},
        },
    )

    assert run.url == urls[0]
    assert run.result_summary["url_count"] == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_preserves_raw_additional_fields_and_keeps_domain_fields(
    db_session: AsyncSession,
    test_user,
) -> None:
    seed_run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/seed",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        ReviewPromotion(
            label_kind="review_promotion",
            source_run_id=seed_run.id,
            domain="example.com",
            surface="ecommerce_detail",
            approved_schema={"fields": ["title", "materials"]},
            field_mapping={"material_notes": "materials"},
        )
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["care instructions"],
        },
    )

    assert "materials" in run.requested_fields
    assert "care instructions" in run.requested_fields
    assert "care" not in run.requested_fields
    assert run.settings["requested_fields"] == run.requested_fields


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_preserves_exact_custom_additional_field_labels(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["Features & Benefits", "Product Story"],
        },
    )

    assert run.requested_fields == ["Features & Benefits", "Product Story"]
    assert run.settings["requested_fields"] == ["Features & Benefits", "Product Story"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_merges_saved_domain_run_profile_for_single_url(
    db_session: AsyncSession,
    test_user,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "fetch_profile": {
                "fetch_mode": "http_then_browser",
                "extraction_source": "rendered_dom",
                "js_mode": "enabled",
                "include_iframes": False,
                "traversal_mode": "paginate",
                "request_delay_ms": 1200,
                "max_pages": 8,
                "max_scrolls": 12,
            },
            "locality_profile": {
                "geo_country": "IN",
                "language_hint": "en-IN",
                "currency_hint": "INR",
            },
            "diagnostics_profile": {
                "capture_html": True,
                "capture_screenshot": False,
                "capture_network": "matched_only",
                "capture_response_headers": True,
                "capture_browser_diagnostics": True,
            },
            "acquisition_contract": {
                "preferred_browser_engine": "real_chrome",
                "prefer_browser": True,
                "handoff_eligible": True,
                "handoff_cookie_engine": "real_chrome",
            },
            "proxy_profile": {
                "enabled": True,
                "proxy_list": ["http://proxy-a", "http://proxy-b"],
            },
        },
        source_run_id=91,
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "settings": {
                "fetch_profile": {
                    "request_delay_ms": 900,
                }
            },
        },
    )

    assert run.settings["fetch_profile"]["fetch_mode"] == "http_then_browser"
    assert run.settings["fetch_profile"]["traversal_mode"] == "paginate"
    assert run.settings["fetch_profile"]["request_delay_ms"] == 900
    assert run.settings["locality_profile"]["geo_country"] == "IN"
    assert run.settings["diagnostics_profile"]["capture_network"] == "matched_only"
    assert run.settings["acquisition_contract"]["preferred_browser_engine"] == "auto"
    assert run.settings["acquisition_contract"]["handoff_eligible"] is False
    assert run.settings["proxy_enabled"] is False
    assert run.settings["proxy_list"] == []
    assert run.settings["proxy_profile"] == {
        "enabled": False,
        "proxy_list": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_explicit_forced_engine_overrides_saved_contract(
    db_session: AsyncSession,
    test_user,
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
            },
        },
        source_run_id=91,
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "settings": {
                "acquisition_contract": {
                    "preferred_browser_engine": "patchright",
                    "prefer_browser": True,
                    "handoff_eligible": False,
                    "handoff_cookie_engine": "patchright",
                },
            },
        },
    )

    contract = run.settings["acquisition_contract"]
    assert contract["preferred_browser_engine"] == "patchright"
    assert contract["handoff_eligible"] is False
    assert contract["handoff_cookie_engine"] == "patchright"


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_only_run_disables_saved_handoff_contract(
    db_session: AsyncSession,
    test_user,
) -> None:
    await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "fetch_profile": {"fetch_mode": "http_then_browser"},
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

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "settings": {
                "advanced_enabled": True,
                "fetch_profile": {"fetch_mode": "browser_only"},
            },
        },
    )

    contract = run.settings["acquisition_contract"]
    assert run.settings["fetch_profile"]["fetch_mode"] == "browser_only"
    assert contract["prefer_browser"] is True
    assert contract["handoff_eligible"] is False
    assert contract["handoff_cookie_engine"] == "auto"


@pytest.mark.component
def test_browser_only_profile_application_drops_handoff() -> None:
    profile = apply_acquisition_contract_to_profile(
        {"fetch_mode": "browser_only"},
        {
            "preferred_browser_engine": "real_chrome",
            "prefer_browser": True,
            "handoff_eligible": True,
            "handoff_cookie_engine": "real_chrome",
        },
    )

    assert profile["prefer_browser"] is True
    assert profile["forced_browser_engine"] == "real_chrome"
    assert "prefer_curl_handoff" not in profile
    assert "handoff_cookie_engine" not in profile


@pytest.mark.component
def test_normalize_acquisition_contract_accepts_legacy_handoff_flag() -> None:
    contract = normalize_acquisition_contract({"prefer_curl_handoff": True})

    assert contract["handoff_eligible"] is True


@pytest.mark.component
def test_build_success_acquisition_contract_tolerates_bad_payload_count() -> None:
    contract = build_success_acquisition_contract(
        method="browser",
        browser_engine="patchright",
        browser_diagnostics={"network_payload_count": "not-a-number"},
        record_count=1,
        requested_fields=["title"],
        found_fields=["title"],
        source_run_id=10,
    )

    assert contract["required_network_payloads"] is False
    assert contract["handoff_eligible"] is True
