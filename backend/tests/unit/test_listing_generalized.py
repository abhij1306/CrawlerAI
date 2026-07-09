"""Slice 4.4: generalized exemplar-record listing tier + per-domain recipe cache.

Proves the acquire-once / replay-cheap contract for listing pages the Tier 0
structured floor cannot hold:

- one exemplar LLM call binds the record shape and applies across all N records;
- the grounding gate emits DOM text at the bound path, never the model's value;
- a compiled recipe replays deterministically with zero LLM on later runs;
- markup drift that breaks the bound path forces a fresh exemplar acquisition;
- a structurally-clean listing still grounds deterministically (no LLM at all).
"""

from __future__ import annotations

from typing import NoReturn

import pytest

from app.extraction.contracts import (
    EntityHint,
    ModelEvidenceCandidate,
    UniversalModelArtifact,
    UniversalModelResult,
)
from app.extraction.engine import extract
from app.extraction.listing_generalized import (
    InMemoryListingRecipeStore,
    run_listing_generalized,
)
from app.extraction.model_runtime import RuntimeFlatMapPage
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit

_PAGE_URL = "https://shop.test/category/shoes"

# A record grid whose title/price live in bare <span>s with no JSON-LD or
# microdata joining them — discovery finds the records, but the Tier 0
# structured floor cannot ground them, so the generalized tier owns the page.
_GRID_HTML = """
<html><body><ul class="grid">
  <li class="card">
    <a href="/p/trail-shoe"><span class="name">Trail Shoe</span></a>
    <span class="price">$79.00</span>
  </li>
  <li class="card">
    <a href="/p/road-shoe"><span class="name">Road Shoe</span></a>
    <span class="price">$89.00</span>
  </li>
  <li class="card">
    <a href="/p/track-spike"><span class="name">Track Spike</span></a>
    <span class="price">$99.00</span>
  </li>
</ul></body></html>
"""


def _approved_snapshot() -> dict[str, object]:
    return {
        "llm_enabled": True,
        "universal_model": {
            "schema_version": "universal_model_artifact.v1",
            "artifact_id": "universal-extractor",
            "artifact_version": "2026-07-02",
            "adapter_id": "fixture-runtime-adapter",
            "model_family": "fixture-grounded-model",
            "deployment_mode": "local",
            "benchmark_schema_version": "universal_model_benchmark.v2",
            "benchmark_report_id": "benchmark-approved-1",
            "benchmark_passed": True,
            "approved": True,
            "enabled": True,
            "confidence_threshold": 0.8,
            "timeout_ms": 1000,
            "max_memory_mb": 128.0,
            "max_cost_per_page_usd": 0.01,
            "supported_surfaces": ["ecommerce_listing"],
        },
    }


_DEFAULT = object()


def _request(html: str, *, snapshot: object = _DEFAULT):
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        html,
        _PAGE_URL,
        max_records=10,
    )
    resolved = _approved_snapshot() if snapshot is _DEFAULT else snapshot
    return request.model_copy(update={"runtime_snapshot": resolved})


class ExemplarBindingAdapter:
    """Binds title/price by the *path* of the exemplar record only.

    Critically, the returned ``value`` is deliberately fabricated ("MODEL SAYS")
    to prove the grounding gate never trusts it — every emitted value must be the
    DOM text read at the bound path, not this string. The adapter sees only the
    single exemplar record's flat map (§163), not all N records.
    """

    adapter_id = "fixture-runtime-adapter"

    def __init__(self) -> None:
        self.calls = 0
        self.entry_counts: list[int] = []

    def predict(
        self,
        page: RuntimeFlatMapPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult:
        self.calls += 1
        self.entry_counts.append(len(page.entries))
        title = next(
            row for row in page.entries if "Shoe" in row.text or "Spike" in row.text
        )
        price = next(row for row in page.entries if "$" in row.text)
        hint = EntityHint(entity_type="product", url="https://shop.test/p/exemplar")
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=(
                ModelEvidenceCandidate(
                    prediction_id="title",
                    artifact_id=page.source.artifact_id,
                    source_path=title.path,
                    fact_type="product.title",
                    raw_value="MODEL SAYS",
                    value="MODEL SAYS",
                    subject_id="model-product-1",
                    subject_scope="product",
                    confidence=0.96,
                    entity_hint=hint,
                ),
                ModelEvidenceCandidate(
                    prediction_id="price",
                    artifact_id=page.source.artifact_id,
                    source_path=price.path,
                    fact_type="offer.price",
                    raw_value="0.00",
                    value="0.00",
                    subject_id="model-product-1",
                    subject_scope="offer",
                    confidence=0.95,
                    entity_hint=hint,
                ),
            ),
            latency_ms=2.0,
            memory_mb=16.0,
            cost_usd=0.001,
        )


class TitleOnlyAdapter(ExemplarBindingAdapter):
    """Binds only the title path — price has no binding, so it must be omitted."""

    def predict(self, page, artifact, *, timeout_ms):
        result = super().predict(page, artifact, timeout_ms=timeout_ms)
        title = next(p for p in result.predictions if p.fact_type == "product.title")
        return result.model_copy(update={"predictions": (title,)})


class MustNotRunAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise AssertionError("generalized tier must remain lazy")


class TimeoutAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise TimeoutError("fixture timeout")


def _by_fact(evidence, fact_type: str) -> list[str]:
    return [row.value for row in evidence if row.fact_type == fact_type]


def test_one_exemplar_call_grounds_every_record_from_dom_text() -> None:
    adapter = ExemplarBindingAdapter()
    result = run_listing_generalized(_request(_GRID_HTML), adapter)

    assert result.outcome == "produced_evidence"
    assert result.invoked is True
    # ONE LLM call for the whole page, and it saw one record's worth of entries
    # (§163: "the LLM sees 1 record, not 900"), not the full grid.
    assert adapter.calls == 1
    assert adapter.entry_counts == [2]
    # Values are the DOM text at the bound path — never the model's fabrication.
    assert _by_fact(result.evidence, "product.title") == [
        "Trail Shoe",
        "Road Shoe",
        "Track Spike",
    ]
    assert _by_fact(result.evidence, "offer.price") == ["$79.00", "$89.00", "$99.00"]
    assert _by_fact(result.evidence, "product.url") == [
        "https://shop.test/p/trail-shoe",
        "https://shop.test/p/road-shoe",
        "https://shop.test/p/track-spike",
    ]
    assert "MODEL SAYS" not in {row.value for row in result.evidence}


def test_recipe_replay_grounds_second_run_with_zero_llm() -> None:
    store = InMemoryListingRecipeStore()
    adapter = ExemplarBindingAdapter()

    first = run_listing_generalized(_request(_GRID_HTML), adapter, recipe_store=store)
    second = run_listing_generalized(_request(_GRID_HTML), adapter, recipe_store=store)

    assert adapter.calls == 1  # second run replayed the compiled recipe
    assert first.invoked is True
    assert second.invoked is False
    assert second.outcome == "produced_evidence"
    assert _by_fact(second.evidence, "product.title") == _by_fact(
        first.evidence, "product.title"
    )


def test_markup_drift_under_recipe_forces_reacquisition() -> None:
    store = InMemoryListingRecipeStore()
    adapter = ExemplarBindingAdapter()

    run_listing_generalized(_request(_GRID_HTML), adapter, recipe_store=store)
    assert adapter.calls == 1

    # The title moves from <span> to <h3>: the recipe's bound path no longer
    # resolves, so replay grounds nothing and the page is re-acquired.
    drifted = _GRID_HTML.replace('span class="name"', 'h3 class="name"').replace(
        "</span></a>", "</h3></a>"
    )
    result = run_listing_generalized(_request(drifted), adapter, recipe_store=store)

    assert adapter.calls == 2  # fresh exemplar pass
    assert result.invoked is True
    assert result.outcome == "produced_evidence"
    assert _by_fact(result.evidence, "product.title") == [
        "Trail Shoe",
        "Road Shoe",
        "Track Spike",
    ]


def test_unbound_optional_field_is_dropped_not_hallucinated() -> None:
    result = run_listing_generalized(_request(_GRID_HTML), TitleOnlyAdapter())

    assert result.outcome == "produced_evidence"
    assert _by_fact(result.evidence, "product.title") == [
        "Trail Shoe",
        "Road Shoe",
        "Track Spike",
    ]
    # No price binding was produced, so no offer.price evidence is emitted — the
    # tier never invents a value the model did not ground.
    assert _by_fact(result.evidence, "offer.price") == []


def test_missing_adapter_disables_tier_without_failure_escalation() -> None:
    result = run_listing_generalized(_request(_GRID_HTML), None)

    assert result.outcome == "failed"
    assert result.failure_code == "model_service_failure"
    assert result.invoked is False
    assert result.evidence == ()


def test_unapproved_snapshot_disables_tier_and_never_invokes() -> None:
    result = run_listing_generalized(
        _request(_GRID_HTML, snapshot={}), MustNotRunAdapter()
    )

    assert result.outcome == "disabled"
    assert result.invoked is False
    assert result.evidence == ()


def test_no_discoverable_records_is_a_clean_no_match() -> None:
    html = "<html><body><main><p>No products here.</p></main></body></html>"
    result = run_listing_generalized(_request(html), MustNotRunAdapter())

    assert result.outcome == "no_match"
    assert result.invoked is False
    assert result.evidence == ()


def test_exemplar_timeout_degrades_without_breaking_extraction() -> None:
    result = run_listing_generalized(_request(_GRID_HTML), TimeoutAdapter())

    assert result.outcome == "timed_out"
    assert result.invoked is True
    assert result.failure_code == "model_service_failure"
    assert result.evidence == ()


def test_structured_listing_stays_deterministic_and_model_free() -> None:
    # A listing carrying a JSON-LD ItemList grounds on the Tier 0 structured
    # floor: the engine must resolve every record with zero LLM and never route
    # to the generalized tier.
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"ItemList","itemListElement":[
        {"@type":"ListItem","url":"https://shop.test/p/trail-shoe",
         "item":{"@type":"Product","name":"Trail Shoe","offers":{"@type":"Offer","price":"79.00"}}},
        {"@type":"ListItem","url":"https://shop.test/p/road-shoe",
         "item":{"@type":"Product","name":"Road Shoe","offers":{"@type":"Offer","price":"89.00"}}}
      ]}
      </script>
    </head><body><ul class="grid">
      <li class="card"><a href="/p/trail-shoe">Trail Shoe</a><span>$79.00</span></li>
      <li class="card"><a href="/p/road-shoe">Road Shoe</a><span>$89.00</span></li>
    </ul></body></html>
    """
    result = extract(_request(html), model_adapter=MustNotRunAdapter())

    assert {row["title"] for row in result.records} == {"Trail Shoe", "Road Shoe"}
    assert result.metrics.universal_model_invocation_count == 0
    assert result.metrics.universal_representation_build_count == 0
    assert result.diagnostics.model_outcome == "not_considered"
