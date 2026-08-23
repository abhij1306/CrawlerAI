# ruff: noqa: F403, F405
"""test_extraction_runtime_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *

from tests.unit.extraction_runtime_test_support import (
    RequestContext,
    SentinelObservation,
    ValidationError,
    _disagreement_classes,
    _has_suspended_runtime_template,
    _normalized,
    adapters,
)


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


def test_known_template_recipe_fast_path_skips_generic_collectors() -> None:
    url = "https://shop.test/products/recipe-shoe"
    selector_rules = [
        {"field_name": "title", "css_selector": ".recipe-title", "is_active": True},
        {"field_name": "price", "css_selector": ".recipe-price", "is_active": True},
        {
            "field_name": "currency",
            "css_selector": ".recipe-currency",
            "is_active": True,
        },
        {"field_name": "image", "css_selector": ".recipe-image", "is_active": True},
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
          <h1 class="recipe-title">Recipe Shoe</h1>
          <span class="recipe-price">$10.00</span>
          <span class="recipe-currency">USD</span>
          <img class="recipe-image" src="/shoe.jpg">
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
        selector_rules=selector_rules,
        runtime_snapshot={
            "surface": "ecommerce_detail",
            "templates": [
                {
                    "template_id": "00000000-0000-0000-0000-000000000001",
                    "fingerprint": "known-template",
                    "route_pattern": "/products/{id}",
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

    assert result.records[0]["title"] == "Recipe Shoe"
    assert {row.collector_id for row in result.evidence} == {"css_recipe", "url"}
    assert result.diagnostics.extractor_tier == "recipe"
    assert result.manifest_context.template_id == "00000000-0000-0000-0000-000000000001"


def test_sampled_recipe_success_records_sentinel_without_override() -> None:
    url = "https://shop.test/products/recipe-shoe"
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
          "sku": "GENERIC-1",
          "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <span class="recipe-title">Recipe Shoe</span>
          <span class="recipe-price">$10.00</span>
          <span class="recipe-currency">USD</span>
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
        selector_rules=selector_rules,
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

    assert result.records[0]["title"] == "Recipe Shoe"
    assert result.sentinel_observations
    observation = result.sentinel_observations[0]
    assert observation.challenger == "deterministic"
    assert observation.state in {"suspected_drift", "critical_drift"}
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
    )
    assert result.diagnostics.model_outcome == "not_considered"
    assert result.diagnostics.trust_state == "rejected"
