from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.crawl.crud import create_crawl_run
from app.services.llm.payloads import validate_task_payload
from app.services.pipeline.direct_record_fallback import apply_llm_fallback


def _as_async(fn):
    async def _wrapped(*args, **kwargs):
        await asyncio.sleep(0)
        return fn(*args, **kwargs)

    return _wrapped


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ecommerce_detail_llm_missing_field_fallback_is_disabled(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {"llm_enabled": True},
            "additional_fields": ["price"],
        },
    )

    @_as_async
    def _unexpected_extract_missing_fields(*args, **kwargs):
        del args, kwargs
        raise AssertionError("ecommerce detail must not run LLM field filling")

    monkeypatch.setattr(
        "app.services.pipeline.direct_record_fallback.extract_missing_fields",
        _unexpected_extract_missing_fields,
    )

    rows = await apply_llm_fallback(
        db_session,
        run=run,
        page_url="https://example.com/products/widget",
        html="<html><body><h1>Widget</h1></body></html>",
        records=[
            {
                "title": "Widget",
                "url": "https://example.com/products/widget",
                "_field_sources": {"title": ["json_ld"]},
            }
        ],
    )

    assert rows == [
        {
            "title": "Widget",
            "url": "https://example.com/products/widget",
            "_field_sources": {"title": ["json_ld"]},
        }
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_non_detail_llm_missing_field_fallback_still_runs(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category",
            "surface": "ecommerce_listing",
            "settings": {"llm_enabled": True},
            "additional_fields": ["brand"],
        },
    )

    calls: list[list[str]] = []

    @_as_async
    def _fake_extract_missing_fields(*args, **kwargs):
        del args
        calls.append(list(kwargs["missing_fields"]))
        return {"brand": "Acme"}, None

    monkeypatch.setattr(
        "app.services.pipeline.direct_record_fallback.extract_missing_fields",
        _fake_extract_missing_fields,
    )

    rows = await apply_llm_fallback(
        db_session,
        run=run,
        page_url="https://example.com/category",
        html="<html><body><h1>Category</h1></body></html>",
        records=[{"title": "Widget", "_field_sources": {"title": ["dom_selector"]}}],
    )

    assert calls == [["brand"]]
    assert rows[0]["brand"] == "Acme"
    assert rows[0]["_field_sources"]["brand"] == ["llm_missing_field_extraction"]


@pytest.mark.regression
def test_llm_evidence_adjudication_contract_rejects_generated_values() -> None:
    valid, valid_error = validate_task_payload(
        "field_cleanup_review",
        {
            "decisions": {
                "price": {
                    "action": "choose",
                    "winning_evidence_ids": ["ev_000001"],
                }
            },
            "recipe_suggestions": [
                {"field_name": "price", "json_path": "$.product.price"}
            ],
        },
    )
    invalid, invalid_error = validate_task_payload(
        "field_cleanup_review",
        {
            "decisions": {},
            "recipe_suggestions": [],
            "suggested_value": "19.99",
        },
    )

    assert valid_error is None
    assert valid is not None
    assert invalid == {
        "decisions": {},
        "recipe_suggestions": [],
        "suggested_value": "19.99",
    }
    assert invalid_error
