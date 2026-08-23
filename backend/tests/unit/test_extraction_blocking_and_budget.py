# ruff: noqa: F403, F405
"""test_extraction_contract_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *

from tests.unit.extraction_contract_test_support import (
    _trust_state,
)


def test_active_provider_shell_without_product_identity_is_blocked() -> None:
    marker = "px-captcha"
    classification = classify_blocked_page(
        f"<html><body><div id='{marker}'>{marker}</div></body></html>",
        200,
    )

    assert classification.blocked is True
    assert classification.outcome == "challenge_page"
    assert marker in classification.active_provider_hits


def test_job_detail_blocking_finding_keeps_error_verdict() -> None:
    request = fixture_request_from_inputs(
        Surface.JOB_DETAIL,
        "<main><h1>Engineer</h1></main>",
        "https://jobs.test/engineer",
    )
    finding = Finding(
        finding_id="blocking-job-finding",
        rule_id="JOB_REQUIRED_FIELD_MISSING",
        severity="high",
        entity_ids=(),
        evidence_ids=(),
        message="Required job field is missing.",
        blocking=True,
    )

    verdict = _assess(
        request,
        TargetSelection(status="resolved"),
        (PublicRecord(title="Engineer"),),
        (finding,),
    )

    assert verdict == "error"


def test_blocked_result_finding_retains_supplied_evidence_ids() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<main><h1>Challenge</h1></main>",
        "https://shop.test/products/challenge",
    )
    row = evidence(
        request.capture,
        "html",
        "dom",
        "product.title",
        "Challenge",
        SourceLocator(kind="css_selector", value="h1"),
        hint=EntityHint(entity_type="product"),
    )

    result = _blocked_result(request, (row,), ())

    assert result.findings[0].evidence_ids == (row.evidence_id,)


def test_blocked_trust_state_wins_over_review_required() -> None:
    assert _trust_state("blocked", (), True) == "blocked"


def test_js_state_source_object_evidence_budget_is_reported() -> None:
    image_urls = [
        f"https://cdn.shop.test/images/trail-shoe-{index}.jpg"
        for index in range(MAX_EVIDENCE_PER_SOURCE_OBJECT + 25)
    ]
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<html><body><h1>Trail Shoe</h1></body></html>",
            "https://shop.test/products/trail-shoe",
            artifacts={
                "js_state_objects": {
                    "name": "Trail Shoe",
                    "sku": "TS-1",
                    "url": "https://shop.test/products/trail-shoe",
                    "images": image_urls,
                }
            },
        )
    )

    budget_outcomes = [
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    ]
    assert budget_outcomes
    assert "evidence_per_source_object_budget_exhausted" in str(
        budget_outcomes[0].detail
    )
    assert "assets" in budget_outcomes[0].dropped_fact_families
    assert budget_outcomes[0].dropped_source_paths
    assert (
        len(budget_outcomes[0].dropped_source_paths)
        <= MAX_DIAGNOSTIC_EXAMPLES_PER_REASON
    )
    assert (
        sum(1 for row in result.evidence if row.collector_id == "js_state")
        <= MAX_EVIDENCE_PER_SOURCE_OBJECT
    )


def test_js_state_source_object_budget_is_reported(monkeypatch) -> None:
    from app.extraction.collectors import js_state

    monkeypatch.setattr(js_state, "MAX_SOURCE_OBJECTS_PER_ARTIFACT", 2)
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<html><body><h1>Trail Shoe</h1></body></html>",
            "https://shop.test/products/trail-shoe",
            artifacts={
                "js_state_objects": {
                    "products": [
                        {"name": "Trail Shoe", "sku": "TS-1"},
                        {"name": "Trail Shoe Blue", "sku": "TS-2"},
                        {"name": "Trail Shoe Red", "sku": "TS-3"},
                    ]
                }
            },
        )
    )

    budget_outcomes = [
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    ]
    assert budget_outcomes
    assert "source_object_budget_exhausted" in str(budget_outcomes[0].detail)


def test_harvest_forwards_budget_limited_outcomes_from_any_harvest_collector(
    monkeypatch,
) -> None:
    from app.extraction import pipeline as extraction_pipeline
    from app.extraction.contracts import CollectorOutcome

    class BudgetedCollector:
        collector_id = "custom_harvest"

        def harvest(self, bundle, artifacts, *, requested_fields=()):
            return SimpleNamespace(
                evidence=(),
                outcomes=(
                    CollectorOutcome(
                        collector_id=self.collector_id,
                        outcome="budget_limited",
                        detail="custom budget",
                    ),
                ),
                admitted_source_objects=0,
            )

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><body></body></html>",
        "https://shop.test/products/widget",
    )
    monkeypatch.setattr(
        extraction_pipeline,
        "default_collectors",
        lambda: (BudgetedCollector(),),
    )

    result = extraction_pipeline.harvest_ecommerce_detail(
        request.capture,
        request.artifact_reader,
    )

    assert result.collector_outcomes[0].collector_id == "custom_harvest"
    assert result.collector_outcomes[0].outcome == "budget_limited"


def test_admitted_source_object_count_keys_by_collector_artifact_and_subject(
    monkeypatch,
) -> None:
    from app.extraction import pipeline as extraction_pipeline

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><body></body></html>",
        "https://shop.test/products/widget",
    )
    subject_id = "subject:product"

    class CollectorA:
        collector_id = "collector_a"

        def collect(self, bundle, artifacts):
            return (
                evidence(
                    bundle,
                    "html",
                    self.collector_id,
                    "product.title",
                    "Widget",
                    SourceLocator(kind="css_selector", value="h1"),
                    hint=EntityHint(entity_type="product"),
                    subject_id=subject_id,
                ),
            )

    class CollectorB(CollectorA):
        collector_id = "collector_b"

    monkeypatch.setattr(
        extraction_pipeline,
        "default_collectors",
        lambda: (CollectorA(), CollectorB()),
    )

    result = extraction_pipeline.harvest_ecommerce_detail(
        request.capture,
        request.artifact_reader,
    )

    assert result.admitted_source_objects == 2


def test_ambiguous_dom_price_threshold_is_configurable(monkeypatch) -> None:
    from app.extraction import pipeline as extraction_pipeline

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><body></body></html>",
        "https://shop.test/products/widget",
    )
    subject_id = "offer:dom:product"
    prices = tuple(
        evidence(
            request.capture,
            "html",
            "dom",
            "offer.price",
            str(value),
            SourceLocator(kind="css_selector", value=f".price-{value}"),
            hint=EntityHint(entity_type="offer"),
            subject_id=subject_id,
        )
        for value in (10, 11, 12, 13)
    )

    monkeypatch.setattr(
        extraction_pipeline,
        "DETAIL_AMBIGUOUS_DOM_PRICE_VALUE_THRESHOLD",
        5,
    )

    flagged = extraction_pipeline.normalize_ecommerce_detail(
        prices,
        page_url="https://shop.test/products/widget",
    )

    assert not any("ambiguous_page_price" in row.flags for row in flagged)


def test_gtin_normalization_rejects_bad_check_digit() -> None:
    from app.extraction import pipeline as extraction_pipeline

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><body></body></html>",
        "https://shop.test/products/widget",
    )
    gtin = evidence(
        request.capture,
        "html",
        "jsonld",
        "product.gtin",
        "4006381333932",
        SourceLocator(kind="json_pointer", value="/gtin13"),
        hint=EntityHint(entity_type="product"),
    )

    normalized = extraction_pipeline.normalize_ecommerce_detail(
        (gtin,),
        page_url="https://shop.test/products/widget",
    )

    assert normalized[0].value == "4006381333932"
    assert "invalid_gtin" in normalized[0].flags


def test_page_identity_brand_flags_partial_page_brand_candidate() -> None:
    from app.extraction import pipeline as extraction_pipeline

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><body></body></html>",
        "https://shop.test/products/widget",
    )
    public_brand = evidence(
        request.capture,
        "html",
        "jsonld",
        "product.brand",
        "Example",
        SourceLocator(kind="json_pointer", value="/brand/name"),
        hint=EntityHint(entity_type="product"),
        subject_id="subject:product",
    )
    page_brand = evidence(
        request.capture,
        "html",
        "opengraph",
        "product.brand",
        "Example Store",
        SourceLocator(kind="css_selector", value="meta[property='og:site_name']"),
        hint=EntityHint(entity_type="product"),
        subject_id="subject:product",
        brand_role="site_identity",
    )

    flagged = extraction_pipeline.normalize_ecommerce_detail(
        (public_brand, page_brand),
        page_url="https://shop.test/products/widget",
    )

    assert "product_name_as_brand" in flagged[0].flags


def test_active_provider_marker_does_not_hide_product_identity() -> None:
    marker = "px-captcha"
    classification = classify_blocked_page(
        f"""
        <html>
          <head>
            <script type="application/ld+json">
            {{
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Trail Shoe"
            }}
            </script>
          </head>
          <body>
            <main><h1>Trail Shoe</h1></main>
            <div>{marker}</div>
          </body>
        </html>
        """,
        200,
    )

    assert classification.blocked is False
    assert classification.outcome == "ok"


def test_blocked_capture_does_not_publish_public_records() -> None:
    marker = "px-captcha"
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        f"""
        <script type="application/ld+json">
        {{"@context":"https://schema.org","@type":"Product","name":"Blocked Widget","url":"https://shop.test/products/challenge-shell"}}
        </script>
        <html><body><div data-description='{marker}'>{marker}</div></body></html>
        """,
        "https://shop.test/products/challenge-shell",
    )
    blocked_capture = request.capture.model_copy(
        update={
            "blocked": True,
            "acquisition_outcome": "challenge_page",
            "browser_attempted": True,
        }
    )

    result = extract(request.model_copy(update={"capture": blocked_capture}))

    assert result.verdict == "blocked"
    assert result.records == ()
    assert result.evidence == ()
    assert len(result.evidence_dispositions) == len(result.evidence)
    assert any(
        finding.rule_id == "ACQUISITION_BLOCKED" and finding.blocking
        for finding in result.findings
    )


def test_weak_brand_token_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Mostro Ecstasy Sneakers",
          "brand": "green",
          "description": "A complete product description for a low-profile sneaker.",
          "image": "https://shop.test/images/mostro.jpg",
          "url": "https://shop.test/products/mostro-ecstasy"
        }
        </script>
        """,
        "https://shop.test/products/mostro-ecstasy",
    )

    assert result.records
    assert result.records[0].get("brand") is None
    assert result.verdict in {"partial", "review"}


def test_product_name_cannot_be_published_as_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Millennium Falcon",
          "brand": "Millennium Falcon",
          "description": "A detailed building set description for collectors.",
          "image": "https://shop.test/images/millennium-falcon.jpg",
          "url": "https://shop.test/products/millennium-falcon"
        }
        </script>
        """,
        "https://shop.test/products/millennium-falcon",
    )

    assert result.records
    assert result.records[0].get("brand") is None


def test_valid_multiword_brand_is_preserved() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Curve Wide Leg Pants",
          "brand": "ASOS DESIGN",
          "description": "Wide-leg pants with a structured drape and soft finish.",
          "image": "https://shop.test/images/curve-pants.jpg",
          "url": "https://shop.test/products/curve-wide-leg-pants"
        }
        </script>
        """,
        "https://shop.test/products/curve-wide-leg-pants",
    )

    assert result.records[0]["brand"] == "ASOS DESIGN"


def test_ellipsis_description_is_rejected_when_complete_evidence_exists() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="description" content="Complete product description with three durable balls supplied in protective tubes.">
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Padel Balls",
            "brand": "KUIKMA",
            "description": "This tri-pack contains 3 tubes of 3...",
            "image": "https://shop.test/images/padel-balls.jpg",
            "url": "https://shop.test/products/padel-balls"
          }
          </script>
        </head>
        """,
        "https://shop.test/products/padel-balls",
    )

    assert result.records
    assert result.records[0]["description"].startswith("Complete product description")


def test_product_url_can_recover_brand_prefix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Structured Commuter Backpack",
          "description": "A structured commuter backpack with padded storage.",
          "image": "https://shop.test/images/commuter-backpack.jpg",
          "url": "https://shop.test/products/calvin-klein-structured-commuter-backpack"
        }
        </script>
        """,
        "https://shop.test/products/calvin-klein-structured-commuter-backpack",
    )

    assert result.records[0]["brand"] == "Calvin Klein"


def test_product_jsp_endpoint_title_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>product.jsp</h1></main>",
        "https://shop.test/catalog/product.jsp?id=12345",
    )

    assert not result.records or result.records[0].get("title") != "product.jsp"
    assert result.verdict != "success"


def test_truncated_comma_fragment_description_loses_to_complete_copy() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="description" content="Modern, effortless bedding made from breathable cotton for everyday comfort.">
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Classic Duvet Cover",
            "brand": "Brooklinen",
            "description": "Modern, effor",
            "image": "https://shop.test/images/duvet-cover.jpg",
            "url": "https://shop.test/products/classic-duvet-cover"
          }
          </script>
        </head>
        """,
        "https://shop.test/products/classic-duvet-cover",
    )

    assert result.records[0]["description"].startswith("Modern, effortless bedding")
