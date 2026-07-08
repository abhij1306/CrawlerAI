# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *
from app.extraction import adapters
from app.extraction.contracts import field_contracts_for_surface
from app.extraction.contracts import EntityHint
from app.extraction.contracts import ModelEvidenceCandidate
from app.extraction.contracts import RequestContext
from app.extraction.contracts import SentinelObservation
from app.extraction.contracts import UniversalModelArtifact
from app.extraction.contracts import UniversalModelResult
from app.extraction.engine import _has_suspended_runtime_template
from app.extraction.engine import _needs_contract_fallback
from app.extraction.model_runtime import RuntimeFlatMapPage
from app.extraction.sentinel import _disagreement_classes, _normalized
from pydantic import ValidationError
from types import SimpleNamespace


def test_extraction_request_has_no_artifact_payloads_field() -> None:
    assert "artifact_payloads" not in ExtractionRequest.model_fields


def test_currency_hint_is_not_used_as_locale_hint() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    context = RequestContext(context_id="ctx-locale", currency_hint="EUR")
    request = request.model_copy(
        update={
            "capture": request.capture.model_copy(update={"request_context": context})
        }
    )

    assert adapters._request_locale_hint(request) is None


def test_review_detail_with_missing_repair_target_can_use_model_fallback() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    attempt = SimpleNamespace(
        verdict="review",
        records=(
            {"url": "https://shop.test/products/trail-shoe", "title": "Trail Shoe"},
        ),
    )

    assert _needs_contract_fallback(request, attempt)


def test_review_detail_with_coverage_does_not_use_model_fallback() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    attempt = SimpleNamespace(
        verdict="review",
        records=(
            {
                "url": "https://shop.test/products/trail-shoe",
                "title": "Trail Shoe",
                "brand": "Acme",
                "description": "Trail Shoe",
                "image_url": "https://shop.test/trail.jpg",
                "price": "19.00",
                "currency": "USD",
                "availability": "in_stock",
            },
        ),
    )

    assert not _needs_contract_fallback(request, attempt)


def test_sentinel_matches_reordered_records_by_identity() -> None:
    recipe = (
        {"sku": "A", "title": "Alpha", "price": "19.90"},
        {"sku": "B", "title": "Beta", "price": 3},
    )
    challenger = (
        {"sku": "B", "title": "Beta", "price": 3.0},
        {"sku": "A", "title": "Alpha", "price": "19.9"},
    )

    assert _disagreement_classes(recipe, challenger) == ()


def test_sentinel_matches_partially_populated_identity() -> None:
    recipe = ({"sku": "A", "title": "Old title"},)
    challenger = ({"sku": "A"},)

    assert _disagreement_classes(recipe, challenger) == ("critical_field:title",)


def test_sentinel_ignores_identified_pagination_count_difference() -> None:
    recipe = ({"sku": "A", "title": "Alpha"},)
    challenger = (
        {"sku": "A", "title": "Alpha"},
        {"sku": "B", "title": "Beta"},
    )

    assert _disagreement_classes(recipe, challenger) == ()


def test_sentinel_marks_one_sided_empty_results_as_record_count_drift() -> None:
    assert _disagreement_classes(({"sku": "A"},), ()) == ("record_count",)


def test_sentinel_normalizes_equivalent_numeric_shapes() -> None:
    assert _normalized("19.90") == _normalized(19.9)
    assert _normalized(3) == _normalized(3.0)


def test_sentinel_rejects_invalid_verdicts() -> None:
    with pytest.raises(ValidationError):
        SentinelObservation(
            challenger="deterministic",
            state="concordant",
            recipe_verdict="typo",
            challenger_verdict="success",
            recipe_record_count=1,
            challenger_record_count=1,
            diagnostic="invalid verdict probe",
            next_action="continue_recipe",
        )


def test_suspended_template_check_is_route_scoped() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    snapshot = {
        "templates": [
            {
                "surface": "ecommerce_detail",
                "route_pattern": "/collections/{id}",
                "sentinel_suspended": True,
            }
        ]
    }
    request = request.model_copy(update={"runtime_snapshot": snapshot})

    assert _has_suspended_runtime_template(request) is False
    snapshot["templates"][0]["route_pattern"] = "/products/{id}"
    assert _has_suspended_runtime_template(request) is True


def test_listing_visual_capture_builds_extractable_html_artifact() -> None:
    product_url = "https://shop.test/p/classic-pants/SKU123.html"
    rows: list[dict[str, object]] = [
        {"href": product_url, "ariaLabel": "View product"},
        {
            "href": product_url,
            "src": "https://shop.test/classic.jpg",
            "alt": "Classic Pants",
        },
        {"href": product_url, "text": "$42.95"},
    ]

    expected = listing_visual_elements_html(rows)
    artifacts = build_browser_artifacts(
        screenshot_path="",
        traversal_result=None,
        html="",
        rendered_html=None,
        rendered_listing_fragments=[],
        listing_visual_elements=rows,
    )

    assert artifacts["listing_visual_html"] == expected
    assert f'href="{product_url}"' in expected
    assert "Classic Pants" in expected
    assert "$42.95" in expected


def test_runtime_capture_bundle_uses_acquisition_metadata() -> None:
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url="https://shop.test/products/trail-shoe",
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url="https://shop.test/products/trail-shoe",
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url="https://shop.test/products/trail-shoe",
        max_records=1,
    )
    assert request.capture.run_id == 42
    assert request.capture.http_status == 200
    assert request.capture.acquisition_method == "browser"
    assert request.capture.browser_attempted is True
    assert request.capture.acquisition_outcome == "ok"
    assert all(
        not artifact.storage_uri.startswith("memory://")
        for artifact in request.capture.artifacts
    )


def test_runtime_request_carries_release_manifest_context() -> None:
    url = "https://shop.test/products/trail-shoe"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )

    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        runtime_snapshot={"_release_snapshot_id": "release-1"},
    )

    assert request.manifest_context.release_snapshot_id == "release-1"


def test_runtime_request_marks_active_selector_fields_as_user_controlled() -> None:
    url = "https://shop.test/products/trail-shoe"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        selector_rules=[
            {
                "field_name": "Product.Title",
                "css_selector": "h1",
                "is_active": True,
            },
            {
                "field_name": "price",
                "css_selector": ".price",
                "is_active": False,
            },
        ],
    )

    assert request.user_controlled_fields == ("product.title",)


def test_known_template_source_pin_marks_recipe_without_css_collectors() -> None:
    url = "https://shop.test/products/recipe-shoe"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Generic Shoe",
          "url": "https://shop.test/products/recipe-shoe",
          "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <h1 class="recipe-title">Recipe Shoe</h1>
        </main>
        """,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        runtime_snapshot={
            "surface": "ecommerce_detail",
            "templates": [
                {
                    "template_id": "00000000-0000-0000-0000-000000000001",
                    "fingerprint": "known-template",
                    "route_pattern": "/products/{id}",
                    "contracts": [
                        {
                            "canonical_field": "offer.currency",
                            "selected_source": "jsonld:/offers/0/priceCurrency",
                            "selection_origin": "operator",
                        }
                    ],
                    "compiled_recipe": {
                        "selector_rules": [],
                        "source_pins": [
                            {
                                "canonical_field": "offer.currency",
                                "selected_source": ("jsonld:/offers/0/priceCurrency"),
                                "selection_origin": "operator",
                            }
                        ],
                        "contracts": [
                            {
                                "canonical_field": "offer.currency",
                                "selected_source": ("jsonld:/offers/0/priceCurrency"),
                                "selection_origin": "operator",
                            }
                        ],
                        "provenance": [],
                    },
                }
            ],
        },
    )

    result = extract(request)

    assert result.records[0]["currency"] == "USD"
    assert "css_recipe" not in {row.collector_id for row in result.evidence}
    assert result.diagnostics.extractor_tier == "recipe"
    assert result.manifest_context.template_id == "00000000-0000-0000-0000-000000000001"


def test_sampled_recipe_success_records_sentinel_without_override() -> None:
    url = "https://shop.test/products/recipe-shoe"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Generic Shoe",
          "sku": "GENERIC-1",
          "url": "https://shop.test/products/recipe-shoe",
          "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Recipe Shoe</h1></main>
        """,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        runtime_snapshot={
            "surface": "ecommerce_detail",
            "sentinel": {"sample_rate": 1.0},
            "_release_snapshot_id": "release-1",
            "templates": [
                {
                    "template_id": "00000000-0000-0000-0000-000000000001",
                    "fingerprint": "known-template",
                    "route_pattern": "/products/{id}",
                    "status": "active",
                    "contracts": [
                        {
                            "canonical_field": "offer.currency",
                            "selected_source": "jsonld:/offers/0/priceCurrency",
                            "selection_origin": "operator",
                        }
                    ],
                    "compiled_recipe": {
                        "selector_rules": [],
                        "source_pins": [
                            {
                                "canonical_field": "offer.currency",
                                "selected_source": ("jsonld:/offers/0/priceCurrency"),
                                "selection_origin": "operator",
                            }
                        ],
                        "contracts": [
                            {
                                "canonical_field": "offer.currency",
                                "selected_source": ("jsonld:/offers/0/priceCurrency"),
                                "selection_origin": "operator",
                            }
                        ],
                        "provenance": [],
                    },
                }
            ],
        },
    )

    result = extract(request)

    assert result.records[0]["currency"] == "USD"
    assert result.sentinel_observations
    observation = result.sentinel_observations[0]
    assert observation.challenger == "deterministic"
    assert observation.state == "concordant"
    assert "sentinel_deterministic_challenger" in result.diagnostics.decision_path
    assert result.diagnostics.sentinel_state == observation.state


def test_suspended_runtime_template_routes_to_generic_without_css_recipe() -> None:
    url = "https://shop.test/products/generic-shoe"
    selector_rules = [
        {"field_name": "title", "css_selector": ".recipe-title", "is_active": True},
        {"field_name": "price", "css_selector": ".recipe-price", "is_active": True},
        {
            "field_name": "currency",
            "css_selector": ".recipe-currency",
            "is_active": True,
        },
    ]
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Generic Shoe",
          "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Generic Shoe</h1></main>
        """,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        runtime_snapshot={
            "surface": "ecommerce_detail",
            "templates": [
                {
                    "template_id": "00000000-0000-0000-0000-000000000001",
                    "fingerprint": "known-template",
                    "route_pattern": "/products/{id}",
                    "status": "suspended",
                    "contracts": [],
                    "compiled_recipe": {
                        "selector_rules": selector_rules,
                        "contracts": [],
                        "provenance": [],
                    },
                }
            ],
        },
    )

    result = extract(request)

    assert result.records[0]["title"].casefold() == "generic shoe"
    assert result.diagnostics.extractor_tier == "deterministic"
    assert "css_recipe" not in {row.collector_id for row in result.evidence}


def test_recipe_identity_failure_falls_back_to_grounded_model_record() -> None:
    url = "https://shop.test/products/correct-shoe"
    selector_rules = [
        {"field_name": "url", "css_selector": ".recipe-url", "is_active": True},
        {"field_name": "title", "css_selector": ".recipe-title", "is_active": True},
        {"field_name": "price", "css_selector": ".recipe-price", "is_active": True},
        {
            "field_name": "currency",
            "css_selector": ".recipe-currency",
            "is_active": True,
        },
    ]
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="""
        <main>
          <a class="recipe-url" href="https://shop.test/products/wrong-shoe">
            Wrong Shoe
          </a>
          <span class="recipe-title">Wrong Shoe</span>
          <span class="recipe-price">$11.00</span>
          <span class="recipe-currency">USD</span>
          <p>
            Correct Shoe /products/correct-shoe Acme durable trail runner
            $19.00 USD /correct.jpg
          </p>
        </main>
        """,
        method="browser",
        status_code=200,
        artifacts={},
    )
    snapshot = {
        "surface": "ecommerce_detail",
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
            "supported_surfaces": ["ecommerce_detail"],
        },
        "templates": [
            {
                "template_id": "00000000-0000-0000-0000-000000000001",
                "fingerprint": "known-template",
                "route_pattern": "/products/{id}",
                "status": "active",
                "contracts": [],
                "compiled_recipe": {
                    "selector_rules": selector_rules,
                    "contracts": [],
                    "provenance": [],
                },
            }
        ],
    }
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        selector_rules=selector_rules,
        runtime_snapshot=snapshot,
    )

    result = extract(request, model_adapter=GroundedDetailAdapter())

    assert result.records
    assert result.records[0]["title"].casefold() == "correct shoe"
    assert result.records[0]["url"] == url
    assert result.records[0]["price"] == "19.00"
    assert result.diagnostics.extractor_tier == "ml"
    assert "model_fallback" in result.diagnostics.decision_path
    assert any(row.collector_id == "universal_model" for row in result.evidence)


class GroundedDetailAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(
        self,
        page: RuntimeFlatMapPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult:
        del timeout_ms
        entry = next(row for row in page.entries if "Correct Shoe" in row.text)
        product_hint = EntityHint(entity_type="product", url=page.source.artifact_id)
        offer_hint = EntityHint(entity_type="offer")
        asset_hint = EntityHint(entity_type="asset")
        predictions = (
            ModelEvidenceCandidate(
                prediction_id="title",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="product.title",
                raw_value="Correct Shoe",
                value="Correct Shoe",
                subject_id="model-product",
                subject_scope="product",
                confidence=0.95,
                entity_hint=product_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="url",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="product.url",
                raw_value="/products/correct-shoe",
                value="https://shop.test/products/correct-shoe",
                subject_id="model-product",
                subject_scope="product",
                confidence=0.95,
                entity_hint=product_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="brand",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="product.brand",
                raw_value="Acme",
                value="Acme",
                subject_id="model-product",
                subject_scope="product",
                confidence=0.9,
                entity_hint=product_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="description",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="product.description",
                raw_value="durable trail runner",
                value="durable trail runner",
                subject_id="model-product",
                subject_scope="product",
                confidence=0.9,
                entity_hint=product_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="price",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="offer.price",
                raw_value="19.00",
                value="19.00",
                subject_id="model-offer",
                subject_scope="offer",
                parent_subject_id="model-product",
                relation_type="product_offer",
                group_id="model-offer",
                confidence=0.95,
                entity_hint=offer_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="currency",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="offer.currency",
                raw_value="USD",
                value="USD",
                subject_id="model-offer",
                subject_scope="offer",
                parent_subject_id="model-product",
                relation_type="product_offer",
                group_id="model-offer",
                confidence=0.95,
                entity_hint=offer_hint,
            ),
            ModelEvidenceCandidate(
                prediction_id="image",
                artifact_id=page.source.artifact_id,
                source_path=entry.path,
                fact_type="asset.image_url",
                raw_value="/correct.jpg",
                value="https://shop.test/correct.jpg",
                subject_id="model-asset",
                subject_scope="asset",
                parent_subject_id="model-product",
                relation_type="product_asset",
                group_id="model-asset",
                confidence=0.9,
                entity_hint=asset_hint,
            ),
        )
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=predictions,
            latency_ms=2.0,
            memory_mb=32.0,
            cost_usd=0.001,
        )


def test_active_provider_shell_is_blocked_when_building_runtime_capture() -> None:
    url = "https://shop.test/products/challenge-shell"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=44,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<html><body><div id='px-captcha'>px-captcha</div></body></html>",
        method="browser",
        status_code=307,
        blocked=False,
        browser_diagnostics={
            "browser_attempted": True,
            "browser_outcome": "usable_content",
            "challenge_evidence": [
                "provider:perimeterx",
                "provider:px-captcha",
                "active_provider:px-captcha",
            ],
            "challenge_provider_hits": ["perimeterx", "px-captcha"],
            "readiness_probes": [{"is_ready": False}],
        },
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )
    result = extract(request)

    assert request.capture.blocked is True
    assert result.records == ()
    assert result.verdict == "blocked"
    assert result.failure_classifications[0].code == "insufficient_input_bundle"
    assert result.diagnostics.trust_state == "blocked"


def test_low_content_browser_shell_is_blocked_when_building_runtime_capture() -> None:
    url = "https://shop.test/products/low-content-shell"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=45,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<html><body><div>Loading...</div></body></html>",
        method="browser",
        status_code=200,
        blocked=False,
        browser_diagnostics={
            "browser_attempted": True,
            "browser_outcome": "low_content_shell",
        },
    )

    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )

    assert request.capture.blocked is True
    assert extract(request).records == ()


def test_not_found_detail_does_not_publish_url_only_fallback_record() -> None:
    url = "https://shop.test/p/poppi-prebiotic-soda/-/A-88886187"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=43,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<main><div>Product Grid</div></main>",
        method="browser",
        status_code=404,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )

    result = extract(request)

    assert result.records == ()


def test_zero_record_result_has_failure_taxonomy_and_diagnostics() -> None:
    result = _extract(
        "ecommerce_listing",
        "<main><h1>Privacy Policy</h1><p>Account and shipping help.</p></main>",
        "https://shop.test/privacy",
        max_records=10,
    )

    assert result.records == ()
    assert result.failure_classifications
    assert result.failure_classifications[0].code in {
        "discovery",
        "insufficient_input_bundle",
        "validation",
        "semantic_resolution",
    }
    assert result.diagnostics.failure_codes
    assert result.diagnostics.decision_path == (
        "harvest",
        "resolve",
        "publish",
        "validate",
        "model_fallback",
    )
    assert result.diagnostics.model_outcome == "disabled"
    assert result.diagnostics.trust_state == "rejected"


def test_field_contract_registry_marks_default_detail_fields_critical() -> None:
    contracts = {
        row.field: row for row in field_contracts_for_surface(Surface.ECOMMERCE_DETAIL)
    }

    assert contracts["title"].required is True
    assert contracts["title"].criticality == "critical"
    assert contracts["price"].entity_scope == "offer"
    assert contracts["image_url"].entity_scope == "asset"
    assert contracts["variants"].cardinality == "many"


def test_evidence_is_immutable() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    item = result.evidence[0]
    try:
        item.value = "changed"  # type: ignore[misc]
    except (ValidationError, TypeError):
        pass
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/trail-shoe")
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert "price" not in public
    assert "currency" not in public
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in result.findings}


def test_offer_price_inherits_currency_from_locale_path_segment() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.test/en-in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/en-in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"
    assert not any(
        row.metadata.get("derived_by") == "currency_from_page_url_hint"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "offer.currency"
        and row.value == "INR"
        and row.rule_id == "currency_from_page_url_hint"
        for row in result.derived_facts
    )


def test_offer_price_inherits_currency_from_cctld() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.co.in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.co.in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"


def test_uncorroborated_cent_magnitude_price_is_not_silently_repaired() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "name": "Runner Tee",
                    "url": "https://shop.test/products/runner-tee",
                    "price": "3499",
                    "currency": "USD",
                }
            },
        ),
    )
    assert result.records[0]["price"] == "3499.00"
    assert result.records[0]["currency"] == "USD"


def test_explicit_usd_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Road Hoodie",
                        "url": "https://shop.test/products/road-hoodie",
                        "priceInCents": 13875,
                        "currency": "USD",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and "explicit_minor_unit_price" not in item.flags
        for item in result.evidence
    )


def test_explicit_inr_minor_unit_variant_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Studio Jacket",
                    "url": "https://shop.test/products/studio-jacket",
                    "variants": [
                        {
                            "variantId": "black-m",
                            "sku": "STUDIO-BLK-M",
                            "size": "M",
                            "priceInPaise": 2820000,
                            "currency": "INR",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "28200.00"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "28200.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 2820000 and not item.flags
        for item in result.evidence
    )


def test_dom_direct_variant_controls_emit_full_variant_matrix_rows() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            """
            <main>
              <h1>Trail Shoe</h1>
              <button
                data-size="M"
                data-color="Black"
                data-sku="TRAIL-BLK-M"
                data-price="64.00"
                data-currency="USD"
                data-available="true">Black M</button>
              <button
                data-size="L"
                data-color="Black"
                data-sku="TRAIL-BLK-L"
                data-price="66.00"
                data-currency="USD"
                data-available="false">Black L</button>
            </main>
            """,
            "https://shop.test/products/trail-shoe",
        )
    )

    variants = sorted(result.records[0]["variants"], key=lambda row: row["size"])
    assert variants == [
        {
            "variant_id": "TRAIL-BLK-L",
            "color": "Black",
            "size": "L",
            "sku": "TRAIL-BLK-L",
            "price": "66.00",
            "currency": "USD",
            "availability": "out_of_stock",
        },
        {
            "variant_id": "TRAIL-BLK-M",
            "color": "Black",
            "size": "M",
            "sku": "TRAIL-BLK-M",
            "price": "64.00",
            "currency": "USD",
            "availability": "in_stock",
        },
    ]


def test_nested_variant_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "priceInfo": {
                                "priceInCents": 13875,
                                "currencyCode": "USD",
                            },
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and item.locator.value.endswith("/priceInCents")
        and not item.flags
        for item in result.evidence
    )


def test_zero_decimal_currency_explicit_minor_key_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Tokyo Jacket</h1></main>",
        "https://shop.test/products/tokyo-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Tokyo Jacket",
                        "url": "https://shop.test/products/tokyo-jacket",
                        "priceInCents": 13875,
                        "currency": "JPY",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "13875.00"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")


def test_decimal_major_unit_price_remains_unchanged() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Studio Jacket",
                        "url": "https://shop.test/products/studio-jacket",
                        "price": "28200.50",
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "28200.50"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")
    assert not _price_repair_facts(result, "corroborated_price_scale")


def test_independent_parent_price_corroborates_variant_minor_unit_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "138.75"
    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "138.75" for fact in facts)
    repaired_evidence_ids = {
        evidence_id for fact in facts for evidence_id in fact.input_evidence_ids
    }
    assert any(
        item.evidence_id in repaired_evidence_ids
        and item.fact_type == "offer.price"
        and item.raw_value == 13875
        for item in result.evidence
    )


def test_parent_price_band_corroborates_different_variant_minor_unit_prices() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Luna Bag",
          "url": "https://shop.test/products/luna-bag",
          "offers": {"price": "59400", "priceCurrency": "INR"}
        }
        </script>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-medium",
                            "sku": "LUNA-M",
                            "size": "M",
                            "price": 5250000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5940000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59400.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "M": "52500.00",
        "L": "59400.00",
    }
    repaired_evidence_ids = {
        evidence_id
        for fact in _price_repair_facts(result, "corroborated_price_scale")
        for evidence_id in fact.input_evidence_ids
    }
    assert {
        item.raw_value
        for item in result.evidence
        if item.evidence_id in repaired_evidence_ids
    } >= {4170000, 5250000, 5940000}


def test_parent_currency_outranks_stray_dom_currency_for_variant_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Luna Bag","url":"https://shop.test/products/luna-bag","offers":{"price":"59500","priceCurrency":"INR"}}
        </script>
        <main><h1>Luna Bag</h1><div class="price">USD 595.00</div></main>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5950000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59500.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "L": "59500.00",
    }


def test_ten_x_peer_does_not_scale_normal_major_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Arrival Shorts","url":"https://shop.test/products/arrival-shorts","offers":{"price":"20","priceCurrency":"USD"},"hasVariant":[{"@type":"Product","sku":"ARRIVAL-3XL","size":"3XL","offers":{"price":"20","priceCurrency":"USD"}}]}
        </script>
        """,
        "https://shop.test/products/arrival-shorts",
        artifacts={
            "js_state_objects": {
                "productData": {
                    "name": "Arrival Shorts",
                    "getTheLookProducts": [
                        {
                            "name": "Related Socks",
                            "variants": [
                                {
                                    "variantId": "related-socks",
                                    "sku": "SOCKS-S",
                                    "size": "S",
                                    "price": 2,
                                    "currency": "USD",
                                }
                            ],
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "20.00"
    assert result.records[0]["variants"][0]["price"] == "20.00"


def test_primary_structured_offer_outranks_conflicting_secondary_currency() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="product:price:amount" content="1400.00">
        <meta property="product:price:currency" content="USD">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Lip Balm","url":"https://shop.test/en-in/products/lip-balm","image":"https://shop.test/lip-balm.jpg","offers":{"price":"1400","priceCurrency":"INR"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":180000,"sku":"BALM-BDAY","public_title":"Birthday"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/en-in/products/lip-balm",
    )

    record = result.records[0]
    assert record["price"] == "1400.00"
    assert record["currency"] == "INR"
    assert record["variants"][0]["price"] == "1800.00"
    assert record["variants"][0]["currency"] == "INR"


def test_uniform_variant_offer_populates_missing_parent_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"ProductGroup",
          "name":"Kids Tank",
          "url":"https://shop.test/products/kids-tank",
          "image":"https://shop.test/kids-tank.jpg",
          "hasVariant":[
            {"@type":"Product","sku":"TANK-S","size":"S","offers":{"price":"70","priceCurrency":"USD"}},
            {"@type":"Product","sku":"TANK-M","size":"M","offers":{"price":"70","priceCurrency":"USD"}}
          ]
        }
        </script>
        """,
        "https://shop.test/products/kids-tank",
    )

    record = result.records[0]
    assert record["price"] == "70.00"
    assert record["currency"] == "USD"
    assert record["_lineage"]["price"]["rule_id"] == ("uniform_variant_offer_aggregate")


def test_same_offer_formatted_price_corroborates_raw_minor_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Air Jordan 5 Retro</h1></main>",
        "https://shop.test/products/air-jordan-5-retro",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Air Jordan 5 Retro",
                        "url": "https://shop.test/products/air-jordan-5-retro",
                        "price": 21500,
                        "formattedPrice": "USD 215.00",
                        "currency": "USD",
                        "variants": [
                            {
                                "variantId": "jordan-8",
                                "sku": "JORDAN-8",
                                "size": "8",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                            {
                                "variantId": "jordan-9",
                                "sku": "JORDAN-9",
                                "size": "9",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "215.00"
    assert {row["price"] for row in result.records[0]["variants"]} == {"215.00"}
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "215.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 21500 and not item.flags
        for item in result.evidence
    )


def test_uncorroborated_expensive_inr_price_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Collector Handbag</h1></main>",
        "https://shop.test/products/collector-handbag",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Collector Handbag",
                        "url": "https://shop.test/products/collector-handbag",
                        "price": 2820000,
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "2820000.00"


def test_parent_current_price_does_not_scale_variant_original_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": "150",
                            "originalPrice": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["price"] == "150.00"
    assert variant["original_price"] == "13875.00"
    assert not any(
        fact.rule_id == "corroborated_price_scale"
        for fact in result.derived_facts
        if fact.fact_type == "offer.original_price"
    )
