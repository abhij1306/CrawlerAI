# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


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


@pytest.mark.parametrize(
    ("url", "title", "description", "image", "bad_brand", "expected"),
    [
        (
            "https://ar.puma.com/pd/zapatillas-mostro/397328.html",
            "Zapatillas Mostro Ecstasy unisex",
            "PUMA Mostro heritage sneaker.",
            "https://images.puma.com/397328.png",
            "green",
            "PUMA",
        ),
        (
            "https://www.aesop.com/candles/aganice/HM03.html",
            "Aganice Aromatique Candle",
            "Aesop home fragrance candle.",
            "https://www.aesop.com/images/Aesop_Aganice.jpg",
            "Fragrance",
            "Aesop",
        ),
        (
            "https://www.usa.canon.com/shop/p/eos-r5",
            "EOS R5 Body",
            "Canon full-frame camera body.",
            "https://s7d1.scene7.com/is/image/canon/eos-r5",
            "Register",
            "Canon",
        ),
        (
            "https://www.maccosmetics.com/product/eye-shadow",
            "Eye Shadow",
            "Highly pigmented pressed eye shadow.",
            "https://www.maccosmetics.com/media/eye-shadow.jpg",
            "& More",
            "Mac",
        ),
        (
            "https://www.karenmillen.com/product/cotton-trouser",
            "Cotton Utility Button Detail Trouser",
            "Karen Millen tailored trouser.",
            "https://media.karenmillen.com/trouser.jpg",
            "Karen",
            "Karen Millen",
        ),
        (
            "https://www.phase-eight.com/product/lucinda-dress.html",
            "Lucinda Spot Midi Dress",
            "Phase Eight occasion dress.",
            "https://www.phase-eight.com/images/lucinda.jpg",
            "Phase",
            "Phase Eight",
        ),
        (
            "https://www.calvinklein.us/bags/structured-commuter-bag.html",
            "Structured Commuter Bag",
            "Calvin Klein commuter bag.",
            "https://calvinklein.scene7.com/is/image/CalvinKlein/bag",
            "Calvin",
            "Calvin Klein",
        ),
        (
            "https://www.asos.com/asos-curve/asos-design-curve-pants/prd/1",
            "ASOS DESIGN Curve Pants",
            "ASOS DESIGN curve pants.",
            "https://images.asos-media.com/products/asos-design-curve-pants/1.jpg",
            "ASOS",
            "ASOS DESIGN",
        ),
        (
            "https://www.williams-sonoma.com/products/breville-the-bambino-plus/",
            "Breville Bambino Plus Espresso Machine",
            "Breville Bambino Plus espresso machine.",
            "https://assets.wsimgs.com/breville-bambino.jpg",
            "Breville Bambino",
            "Breville",
        ),
        (
            "https://www.firstcry.com/babyhug/babyhug-denim-top/1/product-detail",
            "Babyhug Denim Woven Sleeveless Top",
            "Babyhug denim top for children.",
            "https://cdn.test/babyhug-denim.jpg",
            "at",
            "Babyhug",
        ),
        (
            "https://www.therevolverclub.com/products/technics-sl-1200mk7",
            "Technics SL-1200MK7 Turntable",
            "Technics direct-drive turntable.",
            "https://cdn.test/technics-sl1200.jpg",
            "India | The",
            "Technics",
        ),
        (
            "https://www.lego.com/product/millennium-falcon-75192",
            "Millennium Falcon",
            "Travel the LEGO galaxy.",
            "https://www.lego.com/images/75192.png",
            "Millennium Falcon",
            "Lego",
        ),
        (
            "https://www.balmainbeauty.com/fragrance/carbone",
            "Carbone Eau de Parfum",
            "Balmain musk fragrance.",
            "https://www.balmainbeauty.com/images/carbone.png",
            "Fragrance",
            "Balmain",
        ),
    ],
)
def test_page_identity_replaces_known_weak_or_partial_brand_shapes(
    url: str,
    title: str,
    description: str,
    image: str,
    bad_brand: str,
    expected: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"""
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": {json.dumps(title)},
          "brand": {json.dumps(bad_brand)},
          "description": {json.dumps(description)},
          "image": {json.dumps(image)},
          "url": {json.dumps(url)}
        }}
        </script>
        """,
        url,
    )

    assert result.records[0]["brand"].casefold() == expected.casefold()


def test_materializes_once_with_lineage_and_quality() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "Invoro"
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert result.verdict == "success"
    assert record["_lineage"]["price"]["derived_fact_id"]
    assert record["_field_sources"]["title"] == ["jsonld"]
    assert record["_field_sources"]["price"] == ["jsonld"]
    assert result.evidence
    assert "selected" not in record["variants"][0]


def test_missing_default_contract_field_cannot_report_clean_success() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trail Shoe",
          "brand": "Invoro",
          "url": "https://shop.test/products/trail-shoe",
          "image": "https://shop.test/i/trail.jpg",
          "offers": {"price": "129", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert result.verdict == "partial"
    assert any(
        finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "description"
        for finding in result.findings
    )


def test_detail_contract_reports_selected_record_completeness() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Loco Bag",
          "url": "https://shop.test/products/loco-bag"
        }
        </script>
        """,
        "https://shop.test/products/loco-bag",
    )

    assert result.records
    assert result.verdict == "partial"
    # Price + currency are unconditionally part of the completeness contract
    # (Crawl-Run-2 §4.5), so a name+url-only record scores 2/7 and reports the
    # commercial fields as missing alongside the descriptive ones.
    assert result.metrics.completeness_score == pytest.approx(2 / 7)
    missing_fields = {
        finding.metadata.get("field")
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    }
    assert missing_fields == {
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
    }
    completeness = next(
        finding
        for finding in result.findings
        if finding.rule_id == "RECORD_COMPLETENESS"
    )
    assert completeness.metadata["missing_fields"] == (
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
    )


def test_sellable_offer_requires_atomic_price_and_currency_contract() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Complete Product",
          "brand": "Invoro",
          "description": "A complete product description with durable materials.",
          "image": "https://shop.test/i/complete.jpg",
          "url": "https://shop.test/products/complete",
          "offers": {"price": "49"}
        }
        </script>
        """,
        "https://shop.test/products/complete",
    )

    assert result.verdict == "partial"
    missing_fields = {
        finding.metadata.get("field")
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    }
    assert {"price", "currency"} <= missing_fields


def test_explicit_visible_product_brand_label_is_collected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Classic Slip-On Shoe</h1>
          <div class="product-brand">Brand: Vans</div>
          <img data-product-image src="https://shop.test/i/slip-on.jpg">
          <div data-price="65"></div>
          <div data-currency="USD"></div>
        </main>
        """,
        "https://shop.test/products/classic-slip-on-shoe",
    )

    assert result.records[0]["brand"] == "Vans"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Vans"
        and row.collector_id == "dom"
        for row in result.evidence
    )


def test_designed_by_data_attribute_recovers_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Luna Leather Bag</h1>
          <span data-designer-name="3.1 Phillip Lim"></span>
          <img data-product-image src="https://shop.test/i/luna.jpg">
        </main>
        """,
        "https://shop.test/products/luna-leather-bag",
    )

    assert result.records[0]["brand"] == "3.1 Phillip Lim"


def test_jsonld_manufacturer_name_alias_recovers_nested_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Cinema Camera",
          "manufacturerName": "Sony",
          "url": "https://shop.test/products/cinema-camera",
          "image": "https://shop.test/i/camera.jpg"
        }
        </script>
        """,
        "https://shop.test/products/cinema-camera",
    )

    assert result.records[0]["brand"] == "Sony"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Sony"
        and row.brand_role == "manufacturer"
        for row in result.evidence
    )


def test_structured_manufacturer_beats_retailer_identity_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Day-Date 18038 Champagne",
          "manufacturer": {"@type": "Brand", "name": "Rolex"},
          "url": "https://amsterdamvintagewatches.test/shop/rolex-day-date-18038-champagne",
          "offers": {"seller": {"@type": "Organization", "name": "Amsterdam Vintage Watches"}}
        }
        </script>
        <main><span class="product-brand retailer-name">Amsterdam Vintage Watches</span></main>
        """,
        "https://amsterdamvintagewatches.test/shop/rolex-day-date-18038-champagne",
    )

    assert result.records[0]["brand"] == "Rolex"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Amsterdam Vintage Watches"
        and row.brand_role == "retailer"
        and "non_manufacturer_brand_role" in row.flags
        for row in result.evidence
    )


def test_js_state_store_container_does_not_reclassify_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"store":{"product":{
          "name":"Studio Monitor",
          "url":"https://shop.test/products/studio-monitor",
          "brand":{"name":"Audio Guild"}
        }}}}
        </script>
        <main><h1>Studio Monitor</h1></main>
        """,
        "https://shop.test/products/studio-monitor",
    )

    assert result.records[0]["brand"] == "Audio Guild"


def test_registered_title_marker_recovers_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Acme® Trail Shoe</h1>
          <img data-product-image src="https://shop.test/i/trail.jpg">
        </main>
        """,
        "https://shop.test/products/acme-trail-shoe",
    )

    assert result.records[0]["brand"] == "Acme®"
    assert not any(
        row.fact_type == "product.brand"
        and row.metadata.get("derived_by") == "brand_from_title_marker"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Acme®"
        and row.rule_id == "brand_from_title_marker"
        for row in result.derived_facts
    )


def test_jsonld_brand_reference_url_is_not_public_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Basin Convertible Pants",
          "brand": {
            "@type": "Brand",
            "@id": "https://shop.test/en-us#brand"
          },
          "url": "https://shop.test/products/basin-convertible-pants",
          "offers": {"price": "130", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/basin-convertible-pants",
    )

    assert result.records
    assert result.records[0].get("brand") is None
    assert all(
        evidence.value != "https://shop.test/en-us#brand"
        or "brand_url" in evidence.flags
        for evidence in result.evidence
        if evidence.fact_type == "product.brand"
    )


def test_ecommerce_detail_homepage_does_not_materialize_promotional_product() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>All Mens Sale</h1>
          <img src="https://cdn.shop.test/promotions/sale-card.jpg">
          <button>Leggings Size Guide</button>
        </main>
        """,
        "https://shop.test/",
    )

    assert result.records == ()


def test_apostrophe_prefixed_numeric_brand_is_normalized_before_resolution() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "47 NY Yankees Clean Up Cap",
          "brand": {"@type": "Brand", "name": "'47"},
          "url": "https://retailer.test/products/47-yankees-clean-up-cap"
        }
        </script>
        """,
        "https://retailer.test/products/47-yankees-clean-up-cap",
    )

    assert result.records[0]["brand"] == "47"


def test_ecommerce_detail_locale_root_does_not_materialize_embedded_products() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {
          "product": {
            "name": "NY Yankees Clean Up Cap",
            "price": "35",
            "currency": "USD",
            "variants": [
              {"variantId": "shoe", "sku": "U9929NF", "size": "UK 4 UK 5"}
            ]
          }
        }
        </script>
        """,
        "https://shop.test/us/",
    )

    assert result.records == ()
    assert result.verdict == "empty"


def test_jsonld_product_group_uses_shade_as_color_axis() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Eye Shadow",
      "url": "https://shop.test/products/eye-shadow",
      "hasVariant": [
        {
          "@type": "Product",
          "sku": "MY6RPE",
          "name": "Eye Shadow - Carbon - .05 oz / 1.5 g",
          "color": "Black",
          "size": ".05 oz / 1.5 g",
          "offers": {
            "@type": "Offer",
            "url": "https://shop.test/products/eye-shadow?shade=Carbon",
            "price": "25",
            "priceCurrency": "USD",
            "availability": "http://schema.org/InStock"
          }
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/eye-shadow")
    assert result.records[0]["variants"] == [
        {
            "variant_id": "MY6RPE",
            "sku": "MY6RPE",
            "price": "25.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Carbon",
            "size": ".05 oz / 1.5 g",
        }
    ]


def test_gender_microdata_title_and_brand_as_variant_color_are_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        [
          {
            "@type":"ProductGroup",
            "name":"Nylon tank top - Barrow - Boys | Luisaviaroma",
            "brand":"Barrow",
            "url":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027",
            "offers":{"price":"7028","priceCurrency":"INR"}
          },
          {
            "@type":"Product",
            "isVariantOf":{"@id":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027"},
            "sku":"83I-UKD027-MDgw0-5610",
            "size":"8Y",
            "color":"Barrow",
            "offers":{"price":"7028","priceCurrency":"INR"}
          },
          {
            "@type":"Product",
            "isVariantOf":{"@id":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027"},
            "sku":"83I-UKD027-MDgw0-5612",
            "size":"12Y",
            "color":"Barrow",
            "offers":{"price":"7028","priceCurrency":"INR"}
          }
        ]
        </script>
        <span itemprop="name">Short-sleeved T-shirts</span>
        <main><h1>Barrow Nylon tank top</h1></main>
        """,
        "https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027",
    )

    record = result.records[0]
    assert record["title"] == "Barrow Nylon tank top"
    assert {row["size"] for row in record["variants"]} == {"8Y", "12Y"}
    assert all("color" not in row for row in record["variants"])


def test_internal_product_card_title_is_rejected_for_visible_product_heading() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {"componentName":"Tread-Plus Product Card","description":"Internal CMS card"}
        </script>
        <main>
          <h1>Cross Training Tread</h1>
          <img src="https://cdn.shop.test/products/cross-training-tread-main.jpg">
        </main>
        """,
        "https://shop.test/shop/tread",
    )

    assert result.records[0]["title"] == "Cross Training Tread"


def test_jsonld_sibling_products_linked_to_group_materialize_as_variants() -> None:
    html = """
    <script type="application/ld+json">
    [
      {"@type":"ProductGroup","name":"Kids Tank Top","url":"https://shop.test/products/kids-tank","productGroupID":"TANK-1"},
      {"@type":"Product","IS_VARIANT_OF":{"@id":"https://shop.test/products/kids-tank"},"sku":"TANK-8","color":"Green","size":"8Y","offers":{"price":"70","priceCurrency":"USD","availability":"https://schema.org/InStock"}},
      {"@type":"Product","IS_VARIANT_OF":{"@id":"https://shop.test/products/kids-tank"},"sku":"TANK-12","color":"Green","size":"12Y","offers":{"price":"70","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
    ]
    </script>
    """.replace("IS_VARIANT_OF", "is" + "VariantOf")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/kids-tank")

    assert result.records[0]["variants"] == [
        {
            "variant_id": "TANK-12",
            "sku": "TANK-12",
            "price": "70.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Green",
            "size": "12Y",
        },
        {
            "variant_id": "TANK-8",
            "sku": "TANK-8",
            "price": "70.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Green",
            "size": "8Y",
        },
    ]


def test_jsonld_productgroup_id_links_standalone_variant_offers() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@type": "ProductGroup",
        "@id": "https://shop.test/schema/group/sony-a9",
        "productGroupID": "ILCE-9M3",
        "name": "Sony Alpha 9 III",
        "brand": {"@type": "Brand", "name": "SONY"}
      },
      {
        "@type": "Product",
        "isVariantOf": {"@id": "https://shop.test/schema/group/sony-a9"},
        "sku": "ILCE-9M3-BODY",
        "offers": {
          "@type": "Offer",
          "price": "5999.99",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      }
    ]
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/sony-a9")

    record = result.records[0]
    assert record["brand"] == "SONY"
    assert record["price"] == "5999.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["variants"] == [
        {
            "variant_id": "ILCE-9M3-BODY",
            "sku": "ILCE-9M3-BODY",
            "price": "5999.99",
            "currency": "USD",
            "availability": "in_stock",
        }
    ]
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


def test_jsonld_item_offered_offer_links_to_explicit_variant_subject() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@type": "ProductGroup",
        "@id": "https://shop.test/schema/group/shirt",
        "name": "Linen Shirt",
        "url": "https://shop.test/products/linen-shirt",
        "offers": {
          "@type": "Offer",
          "itemOffered": {"@type": "Product", "@id": "https://shop.test/schema/variant/shirt-m"},
          "price": "40.00",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      },
      {
        "@type": "Product",
        "@id": "https://shop.test/schema/variant/shirt-m",
        "isVariantOf": {"@id": "https://shop.test/schema/group/shirt"},
        "sku": "SHIRT-M",
        "size": "M"
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/linen-shirt"
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "SHIRT-M",
            "sku": "SHIRT-M",
            "price": "40.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "M",
        }
    ]
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


def test_jsonld_product_item_offered_preserves_product_offer_scope() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "@id": "https://shop.test/schema/product/desk",
          "name": "Writing Desk",
          "url": "https://shop.test/products/writing-desk",
          "offers": {
            "@type": "Offer",
            "itemOffered": {
              "@type": "Product",
              "@id": "https://shop.test/schema/product/desk"
            },
            "price": "250.00",
            "priceCurrency": "USD"
          }
        }
        </script>
        """,
        "https://shop.test/products/writing-desk",
    )

    assert result.records[0]["price"] == "250.00"
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


def test_jsonld_one_axis_variants_with_child_offers_materialize() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Suede Sneakers",
      "url": "https://shop.test/products/suede",
      "hasVariant": [
        {
          "@type": "Product",
          "color": "Red",
          "offers": {"@type": "Offer", "price": "85", "priceCurrency": "USD"}
        },
        {
          "@type": "Product",
          "color": "Blue",
          "offers": {"@type": "Offer", "price": "80", "priceCurrency": "USD"}
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/suede")
    assert result.records[0]["variants"] == [
        {"price": "80.00", "currency": "USD", "color": "Blue"},
        {"price": "85.00", "currency": "USD", "color": "Red"},
    ]


def test_js_state_image_dimensions_do_not_materialize_as_variants() -> None:
    artifacts = {
        "js_state_objects": {
            "images": [
                {"__typename": "ProductVariantImage", "width": 1206},
                {"__typename": "ProductVariantImage", "width": 4000},
            ],
            "variants": [
                {
                    "__typename": "ProductVariant",
                    "sku": "2775096",
                    "color": "Bissap Glaze",
                    "price": "24",
                    "currency": "USD",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Lip Balm</h1></body></html>",
        "https://shop.test/products/lip-balm",
        artifacts=artifacts,
    )
    assert result.records[0]["variants"] == [
        {
            "variant_id": "2775096",
            "sku": "2775096",
            "price": "24.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Bissap Glaze",
        }
    ]
    assert result.decisions


def test_identity_only_variant_with_inherited_currency_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type":"Product","name":"Cross Training Tread","url":"https://shop.test/products/tread","offers":{"priceCurrency":"USD"}}
        </script>
        """,
        "https://shop.test/products/tread",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Cross Training Tread",
                        "url": "https://shop.test/products/tread",
                        "currency": "USD",
                        "variants": [
                            {"id": "price-id-1"},
                            {"id": "price-id-2"},
                        ],
                    }
                }
            },
        ),
    )

    assert not result.records[0].get("variants")


def test_js_state_media_id_and_width_do_not_materialize_as_variant() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Lip Balm</h1></main>",
        "https://shop.test/products/lip-balm",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Lip Balm",
                    "url": "https://shop.test/products/lip-balm",
                    "price": 18,
                    "currency": "USD",
                    "media": [
                        {
                            "id": "33841425055989",
                            "width": 916,
                            "src": "https://cdn.shop.test/lip-balm.jpg",
                        }
                    ],
                }
            }
        },
    )

    assert not result.records[0].get("variants")
    assert all(row.fact_type != "variant.option.width" for row in result.evidence)


def test_responsive_layout_dimensions_do_not_materialize_as_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Rustic Cotton T-Shirt",
          "url": "https://shop.test/products/rustic-cotton-t-shirt",
          "offers": {"price": "14.90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/rustic-cotton-t-shirt",
        network_payloads=(
            {
                "body": {
                    "categories": [
                        {
                            "sdui": {
                                "responsiveLayouts": [
                                    {
                                        "id": "layout-card-1",
                                        "dimensions": {"width": 358, "height": 640},
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
        ),
    )

    assert result.records[0]["price"] == "14.90"
    assert not result.records[0].get("variants")


def test_jsonld_aggregate_offer_low_price_materializes() -> None:
    html = HTML.replace(
        '"@type": "Offer",\n    "price": "129",',
        '"@type": "AggregateOffer",\n    "lowPrice": "9.99",\n    "highPrice": "19.99",',
    )
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["price"] == "9.99"
    assert record["price_max"] == "19.99"
    assert record.get("original_price") is None
    assert record["currency"] == "USD"


def test_jsonld_aggregate_offer_child_availability_materializes() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Bambino Plus",
          "url": "https://shop.test/products/bambino-plus",
          "image": "https://shop.test/bambino.jpg",
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "499.95",
            "highPrice": "499.95",
            "priceCurrency": "USD",
            "offers": [
              {
                "@type": "Offer",
                "price": "499.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "sku": "1437371"
              },
              {
                "@type": "Offer",
                "price": "499.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "sku": "3302893"
              }
            ]
          }
        }
        </script>
        """,
        "https://shop.test/products/bambino-plus",
    )

    record = result.records[0]
    assert record["price"] == "499.95"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


def test_jsonld_offer_price_specification_materializes_atomically() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Cartier Sunglasses",
          "url": "https://shop.test/products/cartier-sunglasses",
          "image": "https://shop.test/cartier.jpg",
          "offers": {
            "@type": "Offer",
            "availability": "https://schema.org/InStock",
            "priceSpecification": {
              "@type": "UnitPriceSpecification",
              "price": "1795.00",
              "priceCurrency": "USD"
            }
          }
        }
        </script>
        """,
        "https://shop.test/products/cartier-sunglasses",
    )

    record = result.records[0]
    assert record["price"] == "1795.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    price_evidence = [row for row in result.evidence if row.fact_type == "offer.price"]
    currency_evidence = [
        row for row in result.evidence if row.fact_type == "offer.currency"
    ]
    assert price_evidence and currency_evidence
    assert price_evidence[0].group_id == currency_evidence[0].group_id


def test_jsonld_schema_online_only_availability_is_sellable() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Padel Balls",
          "url": "https://shop.test/products/padel-balls",
          "image": "https://shop.test/padel.jpg",
          "offers": {
            "@type": "Offer",
            "price": "10.99",
            "priceCurrency": "GBP",
            "availability": "https://schema.org/OnlineOnly"
          }
        }
        </script>
        """,
        "https://shop.test/products/padel-balls",
    )

    record = result.records[0]
    assert record["price"] == "10.99"
    assert record["currency"] == "GBP"
    assert record["availability"] == "in_stock"
    assert not any(
        row.fact_type == "offer.availability" and "invalid_availability" in row.flags
        for row in result.evidence
    )
