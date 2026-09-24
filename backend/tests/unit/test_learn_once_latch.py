from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.crawl.pipeline import record_extraction_stage as stage
from app.crawl.pipeline.url_processing_context import URLProcessingContext
from app.extraction.contracts import ExtractionResult
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_maybe_learn_once_latches_after_first_attempt(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_learn(*_args, **_kwargs):
        calls.append(1)
        return False

    async def fake_snapshot(_context):
        return {}

    monkeypatch.setattr(stage, "_load_runtime_snapshot", fake_snapshot)
    monkeypatch.setattr(stage, "request_from_acquisition_result", lambda *a, **k: None)
    monkeypatch.setattr(stage, "select_active_recipe", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.crawl.pipeline.learn_once.learn_recipe_after_extraction", fake_learn
    )

    context = URLProcessingContext(
        session=SimpleNamespace(),  # type: ignore[arg-type]
        run=SimpleNamespace(
            id=1,
            settings_view=SimpleNamespace(llm_enabled=lambda: True),
            extraction_release_snapshot_id=None,
        ),  # type: ignore[arg-type]
        url="https://shop.test/p/1",
        config=SimpleNamespace(max_records=10),  # type: ignore[arg-type]
        url_timeout_seconds=120.0,
        started_at_monotonic=0.0,
        requested_fields=["title"],
        surface="ecommerce_detail",
    )
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=1,
            url=context.url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=context.url,
        html="<html></html>",
        method="curl_cffi",
        status_code=200,
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL, records=(), verdict="empty"
    )

    await stage._maybe_learn_once(
        context, acquisition_result=acquisition, selector_rules=[], result=result
    )
    await stage._maybe_learn_once(
        context, acquisition_result=acquisition, selector_rules=[], result=result
    )

    assert calls == [1]
    assert context.learn_once_attempted is True
