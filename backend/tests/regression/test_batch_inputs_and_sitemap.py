"""test_batch_runtime cases split by public behavior."""

from __future__ import annotations

from app.core.config.run_events import RunEventKind
from tests.regression.batch_runtime_test_support import (
    AsyncSession,
    PageAcquisitionResult,
    SITEMAP_DEFAULT_MAX_URLS,
    URLProcessingResult,
    _detail_html,
    assemble_run_summary_payload,
    batch_runtime_module,
    create_crawl_run,
    process_run,
    pytest,
)


@pytest.fixture(autouse=True)
def _disable_run_event_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _record(**_kwargs) -> object:
        return object()

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_requested_fields_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "requested_fields": ["materials"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [["materials"], ["materials"]]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_proxy_list_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "settings": {
                "proxy_enabled": True,
                "proxy_list": ["http://proxy-a", "http://proxy-b"],
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": ["http://proxy-a", "http://proxy-b"],
                },
            },
        },
    )
    captured_proxy_lists: list[list[str]] = []

    async def _fake_acquire(request):
        captured_proxy_lists.append(list(request.proxy_list))
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_proxy_lists == [
        ["http://proxy-a", "http://proxy-b"],
        ["http://proxy-a", "http://proxy-b"],
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_exact_requested_section_labels_for_every_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "additional_fields": ["Features & Benefits"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [
        ["Features & Benefits"],
        ["Features & Benefits"],
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_resolves_urls_from_sitemap_settings(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_filter_keyword": "collections",
                "sitemap_max_urls": 2,
            },
        },
    )
    resolved_inputs: list[tuple[str, str, int, bool]] = []
    processed_urls: list[str] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        resolved_inputs.append(
            (domain, filter_keyword, max_urls, allow_homepage_fallback)
        )
        return [
            "https://example.com/collections/a",
            "https://example.com/collections/b",
        ]

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        processed_urls.append(url)
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert resolved_inputs == [("example.com", "collections", 2, False)]
    assert processed_urls == [
        "https://example.com/collections/a",
        "https://example.com/collections/b",
    ]
    assert run.result_summary["url_count"] == 2
    # 2.1: resolved_url_list / mid-run url_verdicts are no longer stored on the
    # run row (every per-URL commit used to rewrite the N-sized JSONB). Read
    # paths reconstruct them from crawl_url_results via
    # assemble_run_summary_payload; the final patch still persists url_verdicts.
    assert "resolved_url_list" not in run.result_summary
    assert run.result_summary["url_verdicts"] == ["success", "success"]
    payload = await assemble_run_summary_payload(db_session, run)
    assert payload["url_verdicts"] == ["success", "success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_defaults_bad_sitemap_max_urls(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_max_urls": "not-a-number",
            },
        },
    )
    resolved_inputs: list[int] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, allow_homepage_fallback
        resolved_inputs.append(max_urls)
        return ["https://example.com/collections/a"]

    async def _fake_process_single_url(*args, **kwargs):
        del args, kwargs
        return URLProcessingResult(records=[], verdict="success")

    monkeypatch.setattr(
        "app.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)

    assert resolved_inputs == [SITEMAP_DEFAULT_MAX_URLS]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_marks_failed_when_sitemap_resolution_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_filter_keyword": "collections",
            },
        },
    )

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, max_urls, allow_homepage_fallback
        raise ValueError(
            "Sitemap fetch failed: https://example.com/sitemap.xml returned HTTP 503"
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    recorded: list[tuple[int, object]] = []

    async def _record(*, run_id: int, fact, **_kwargs) -> object:
        recorded.append((run_id, fact))
        return object()

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.completed_at is not None
    assert (
        run.result_summary["error"]
        == "ValueError: Sitemap fetch failed: https://example.com/sitemap.xml returned HTTP 503"
    )
    assert [(run_id, event.kind, event.facts) for run_id, event in recorded] == [
        (run.id, RunEventKind.RUN_FAILED, {"exception_type": "ValueError"})
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_keeps_homepage_fallback_disabled_for_explicit_surface(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
            },
        },
    )
    resolved_flags: list[bool] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, max_urls
        resolved_flags.append(allow_homepage_fallback)
        return ["https://example.com/women"]

    async def _fake_process_single_url(*args, **kwargs):
        del args, kwargs
        return URLProcessingResult(records=[], verdict="success")

    monkeypatch.setattr(
        "app.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)

    assert resolved_flags == [False]
