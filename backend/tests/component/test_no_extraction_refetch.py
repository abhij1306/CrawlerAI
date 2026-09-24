"""Extraction must consume the acquired page without opening another browser."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.crawl.pipeline import extraction_loop
from app.extraction.contracts import ExtractionResult
from app.extraction.surfaces import Surface

pytestmark = [pytest.mark.asyncio, pytest.mark.component]


@pytest.mark.parametrize("surface", (Surface.ECOMMERCE_DETAIL, Surface.JOB_DETAIL))
async def test_missing_record_never_refetches_after_extraction(
    monkeypatch, surface: Surface
) -> None:
    acquisition = SimpleNamespace(method="curl_cffi")
    fetched = SimpleNamespace(acquisition_result=acquisition)
    context = SimpleNamespace(
        run=SimpleNamespace(id=1),
        url="https://shop.test/item",
        surface=surface.value,
        requested_fields=["variants"],
    )
    extract_calls = 0

    async def fake_extract(_context, _fetched):
        nonlocal extract_calls
        extract_calls += 1
        return ExtractionResult(surface=surface, records=(), verdict="empty"), []

    async def unexpected_acquire(_request):
        raise AssertionError("extraction attempted a second acquisition")

    monkeypatch.setattr(
        extraction_loop, "extract_records_for_acquisition", fake_extract
    )
    monkeypatch.setattr(extraction_loop, "acquire", unexpected_acquire)
    monkeypatch.setattr(
        extraction_loop,
        "_record_detail_expansion_extraction_outcome",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        extraction_loop, "set_logfire_attributes", lambda *args, **kwargs: None
    )

    result = await extraction_loop._run_extraction_stage_observed(
        context, fetched, None
    )

    assert extract_calls == 1
    assert result.result.verdict == "empty"
    assert fetched.acquisition_result is acquisition
