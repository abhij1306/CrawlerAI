from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *
from .product_intelligence_test_support import _build_candidate_intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_brand_present(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def fake_run_prompt_task(*args, **kwargs):
        calls.append(kwargs.get("task_type", ""))
        raise AssertionError("LLM must not be called when brand already resolved")

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,  # never used because LLM path is gated off
        raw={
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "url": "https://www.belk.com/p/1.html",
        },
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Levis"
    assert snapshot["normalized_brand"] == "levi's"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={
            "title": "Wundermost Bodysuit",
            "url": "https://shop.example.com/products/wundermost.html",
        },
        llm_enabled=False,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_uses_llm_brand_when_confident(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        captured["task_type"] = task_type
        captured["domain"] = domain
        captured["variables"] = variables
        return LLMTaskResult(
            payload={
                "brand": "Lululemon",
                "confidence": 0.92,
                "rationale": "DTC URL match",
            },
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={
            "title": "Wundermost Bodysuit",
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit.html",
        },
        llm_enabled=True,
    )

    assert snapshot["brand"] == "Lululemon"
    assert snapshot["normalized_brand"] == "lululemon"
    assert captured["task_type"] == "product_intelligence_brand_inference"
    assert captured["domain"] == "lululemon.com"
    assert captured["variables"]["product_title"] == "Wundermost Bodysuit"
    assert captured["variables"]["source_domain"] == "lululemon.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_drops_low_confidence_llm_brand(
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={
                "brand": "MaybeBrand",
                "confidence": 0.2,
                "rationale": "weak signal",
            },
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_swallows_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider unavailable",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={"title": "Random Title", "url": "https://retailer.example.com/p/123.html"},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""
    assert snapshot["normalized_brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_source_snapshot_skips_llm_when_no_inputs(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called without title or url")

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    snapshot = await resolve_source_snapshot(
        session=None,
        raw={},
        llm_enabled=True,
    )

    assert snapshot["brand"] == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_skips_when_disabled(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when llm_enabled is False")

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=False,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_skips_when_brand_present(monkeypatch) -> None:
    async def fake_run_prompt_task(*args, **kwargs):
        raise AssertionError("LLM must not be called when candidate brand is set")

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence(brand="Lululemon")
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Lululemon Wundermost Bodysuit", "brand": "Lululemon"},
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_applies_llm_brand_and_rescores(
    monkeypatch,
) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={
                "brand": "Lululemon",
                "confidence": 0.91,
                "rationale": "DTC URL match",
            },
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    source = {
        "title": "Lululemon Wundermost Bodysuit",
        "brand": "Lululemon",
        "normalized_brand": "lululemon",
    }
    result = await backfill_candidate_brand(
        session=None,
        source=source,
        intelligence=intelligence,
        source_type="brand_dtc",
        llm_enabled=True,
    )

    canonical = result["canonical_record"]
    assert canonical["brand"] == "Lululemon"
    assert canonical["normalized_brand"] == "lululemon"
    assert result["score_reasons"]["brand_match"] is True
    assert result["confidence_score"] > intelligence["confidence_score"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_drops_low_confidence(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload={"brand": "Maybe", "confidence": 0.1, "rationale": "weak"},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Wundermost Bodysuit", "brand": ""},
        intelligence=intelligence,
        source_type="unknown",
        llm_enabled=True,
    )

    assert result is intelligence


@pytest.mark.asyncio
@pytest.mark.component
async def test_backfill_candidate_brand_handles_llm_error(monkeypatch) -> None:
    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        return LLMTaskResult(
            payload=None,
            error_message="provider down",
            error_category=LLMErrorCategory.PROVIDER_ERROR,
        )

    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    intelligence = _build_candidate_intelligence()
    result = await backfill_candidate_brand(
        session=None,
        source={"title": "Anything", "brand": ""},
        intelligence=intelligence,
        source_type="retailer",
        llm_enabled=True,
    )

    assert result is intelligence
