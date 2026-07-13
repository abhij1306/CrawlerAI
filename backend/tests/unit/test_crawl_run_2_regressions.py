"""Distilled regressions for the Crawl-Run-2 evaluation & ownership fixes.

Each test reproduces the minimal shape of a defect the comparison report
(``CrawlerAI_Latest_vs_Previous_Crawl_Comparison.md``) surfaced in crawl run 2
(result IDs 96-191), so the follow-on fixes cannot silently regress. Fixtures
are synthetic; the audited HTML lives in the gitignored ``backend/artifacts``
tree and is not committed.
"""

from __future__ import annotations

import json

import pytest

from app.extraction import Surface, extract
from app.extraction.contracts import Finding
from app.extraction.result_building import _review_required
from app.extraction.entities import EntitySet, OfferEntity
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.validation import _validate_offers

from tests.unit.extraction_pipeline_test_support import _extract

pytestmark = pytest.mark.unit


# --- Slice A: offer-finding public-projection scope (§4.1) ------------------


def _offer(
    entity_id: str, *, variant_entity_id: str | None, **facts: str
) -> OfferEntity:
    return OfferEntity(
        entity_id=entity_id,
        product_entity_id="product:1",
        variant_entity_id=variant_entity_id,
        group_id="g",
        request_context_id="ctx",
        fact_evidence={f"offer.{k}": (v,) for k, v in facts.items()},
    )


def _offer_findings(*offers: OfferEntity):
    return _validate_offers((), EntitySet(offers=offers))


def _scopes(findings, rule_id: str) -> set[str]:
    return {f.scope for f in findings if f.rule_id == rule_id}


def test_split_product_offers_publishing_both_stay_candidate_scope() -> None:
    """Result 98: one product-level offer carries price-only and a *separate*
    product-level offer carries currency-only. The parent projection merges them
    and publishes both, so neither incompleteness is a public integrity gap —
    both findings must be diagnostic-only (``candidate``), never selected_entity.
    """
    findings = _offer_findings(
        _offer("offer:price", variant_entity_id=None, price="138.75"),
        _offer("offer:currency", variant_entity_id=None, currency="USD"),
    )

    assert _scopes(findings, "PRICE_WITHOUT_CURRENCY") == {"candidate"}
    assert _scopes(findings, "CURRENCY_WITHOUT_PRICE") == {"candidate"}
    # No selected_entity offer-pair finding => no false review / root cause.
    assert not any(
        f.scope == "selected_entity"
        and f.rule_id in {"PRICE_WITHOUT_CURRENCY", "CURRENCY_WITHOUT_PRICE"}
        for f in findings
    )


def test_genuinely_currencyless_parent_still_reports_selected_entity() -> None:
    """When NO product-level offer supplies the currency, a price-without-currency
    offer is a real public gap and must stay a selected_entity page finding."""
    findings = _offer_findings(
        _offer("offer:price", variant_entity_id=None, price="138.75"),
    )

    assert _scopes(findings, "PRICE_WITHOUT_CURRENCY") == {"selected_entity"}


def test_variant_bound_incomplete_offer_stays_candidate() -> None:
    """A variant-bound offer's incompleteness is candidate evidence regardless of
    the parent projection — it never becomes a page-level finding."""
    findings = _offer_findings(
        _offer("offer:v1", variant_entity_id="variant:1", price="99.00"),
    )

    assert _scopes(findings, "PRICE_WITHOUT_CURRENCY") == {"candidate"}


# --- Slice C: unified critical-field contract (§4.5) -----------------------


def _no_commercial_signal_html(*, title: str) -> str:
    """A product detail page that publishes core descriptive fields but exposes
    no price/currency anywhere — the shape of results 137 (Mytheresa) & 154
    (Sony), which used to score a clean ``success``/``verified``."""
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title,
            "brand": {"@type": "Brand", "name": "Atelier"},
            "description": "A finely tailored garment for every occasion.",
            "sku": "P01155657",
            "url": "https://shop.test/products/no-price",
            "image": ["https://shop.test/i/no-price.jpg"],
        }
    )
    return (
        f"<html><head><title>{title}</title>"
        f'<script type="application/ld+json">{payload}</script>'
        f"</head><body><main><h1>{title}</h1></main></body></html>"
    )


def test_product_with_no_price_is_partial_and_not_verified() -> None:
    """Crawl-Run-2 §4.5: price + currency are completeness-critical. A product
    record that publishes neither must be ``partial`` / trust ``partial`` with
    both listed in ``missing_critical_fields`` — never ``success``/``verified`` —
    yet must NOT be force-routed to review on that basis alone."""
    result = _extract(
        "ecommerce_detail",
        _no_commercial_signal_html(title="Silk Blouse"),
        "https://shop.test/products/no-price",
    )

    assert result.verdict == "partial"
    assert result.diagnostics.trust_state == "partial"
    assert result.diagnostics.review_required is False
    missing = set(result.diagnostics.missing_critical_fields)
    assert {"price", "currency"} <= missing


def test_complete_commercial_record_stays_success_verified() -> None:
    """The unconditional price/currency contract must not penalise a record that
    genuinely publishes both — it stays ``success``/``verified``."""
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Trail Shoe",
            "brand": {"@type": "Brand", "name": "Invoro"},
            "description": "A durable trail shoe for long-distance runs.",
            "sku": "TS-1",
            "url": "https://shop.test/products/trail-shoe",
            "image": ["https://shop.test/i/trail.jpg"],
            "offers": {
                "@type": "Offer",
                "price": "129.00",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "url": "https://shop.test/products/trail-shoe",
            },
        }
    )
    result = _extract(
        "ecommerce_detail",
        f"<html><head><title>Trail Shoe</title>"
        f'<script type="application/ld+json">{payload}</script>'
        f"</head><body><main><h1>Trail Shoe</h1></main></body></html>",
        "https://shop.test/products/trail-shoe",
    )

    assert result.verdict == "success"
    assert result.diagnostics.trust_state == "verified"
    assert not ({"price", "currency"} & set(result.diagnostics.missing_critical_fields))


# --- Slice D: risk-based review routing (§4.4) ------------------------------


def _finding(rule_id: str, *, scope: str = "page") -> Finding:
    return Finding(
        finding_id=f"finding:{rule_id}:{scope}",
        rule_id=rule_id,
        severity="high",
        scope=scope,  # type: ignore[arg-type]
        entity_ids=(),
        evidence_ids=(),
        message=rule_id,
        blocking=False,
    )


def _routing_request():
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<html><head><title>x</title></head><body><main></main></body></html>",
        "https://shop.test/products/x",
    )


def test_child_join_failed_page_finding_routes_to_review() -> None:
    """Result 118 (Nike): a ``CHILD_JOIN_FAILED`` public join failure drops variant
    commercial data — it is a public-output risk and must force operator review."""
    assert (
        _review_required(
            _routing_request(),
            verdict="success",
            findings=(_finding("CHILD_JOIN_FAILED", scope="page"),),
            field_states=(),
            retry=None,
        )
        is True
    )


def test_candidate_scope_offer_pair_findings_do_not_route() -> None:
    """The 33 ex-false-success pages (result 98 shape): once the offer-pair
    findings are diagnostic-only ``candidate`` scope, they must not route."""
    assert (
        _review_required(
            _routing_request(),
            verdict="success",
            findings=(
                _finding("PRICE_WITHOUT_CURRENCY", scope="candidate"),
                _finding("CURRENCY_WITHOUT_PRICE", scope="candidate"),
            ),
            field_states=(),
            retry=None,
        )
        is False
    )


def test_partial_missing_commercial_without_risk_does_not_route() -> None:
    """Per the user decision: missing price/currency alone (results 137/154) yields
    a ``partial`` verdict but must NOT force review absent another risk signal.
    ``MISSING_CONTRACT_FIELD`` is deliberately not in the routing risk set."""
    assert (
        _review_required(
            _routing_request(),
            verdict="partial",
            findings=(_finding("MISSING_CONTRACT_FIELD", scope="selected_entity"),),
            field_states=(),
            retry=None,
        )
        is False
    )


# --- Slice E: selected-target lineage and embedded structured payloads -------


def test_product_group_id_links_jsonld_parent_to_network_variant_root() -> None:
    """Result 118 (Nike): network/js_state can select the variant-specific final
    URL as the product root while JSON-LD keeps the ProductGroup parent on the
    canonical group URL. The shared product-group id must link those roots before
    selected-target pruning, or the brand is rejected as outside_selected_target
    and embedded variant offers become public child-join failures.
    """
    product_group = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Air Force 1",
        "brand": {"@type": "Brand", "name": "Acme"},
        "productGroupID": "CW2288",
        "url": "https://shop.test/t/air-force-1",
        "variesBy": ["size"],
        "hasVariant": [
            {
                "@type": "Product",
                "@id": "https://shop.test/t/air-force-1/CW2288-111#size-9",
                "name": "Air Force 1 / White / 9",
                "size": "9",
                "url": "https://shop.test/t/air-force-1/CW2288-111",
                "offers": {
                    "@type": "Offer",
                    "price": "115",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                },
            }
        ],
    }

    result = _extract(
        "ecommerce_detail",
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(product_group)}</script>'
        "</head><body><main><h1>Air Force 1</h1></main></body></html>",
        "https://shop.test/t/air-force-1/CW2288-111",
        network_payloads=(
            {
                "body": {
                    "data": {
                        "product": {
                            "productCode": "CW2288",
                            "name": "Air Force 1",
                            "url": "https://shop.test/t/air-force-1/CW2288-111",
                            "price": "115",
                            "currency": "USD",
                            "variants": [
                                {
                                    "variantId": "CW2288-111-9",
                                    "sku": "CW2288-111-9",
                                    "size": "9",
                                    "price": "115",
                                    "currency": "USD",
                                    "available": True,
                                }
                            ],
                        }
                    }
                }
            },
        ),
    )

    assert result.records[0]["brand"] == "Acme"
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )
    assert any(row.get("size") == "9" for row in result.records[0]["variants"])


def test_schema_productgroup_attribute_is_collected_as_structured_product() -> None:
    """Result 179 (Ralph Lauren): no ld+json script was present, but the page
    carried escaped ProductGroup JSON in a DOM attribute. That is structured
    product evidence, not a hostname/site-brand inference.
    """
    product_group = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Cable-Knit Cotton Quarter-Zip Sweater",
        "brand": {"@type": "Brand", "name": "Polo Ralph Lauren"},
        "productGroupID": "RL-100",
        "url": "https://shop.test/products/cable-knit-cotton-quarter-zip-sweater",
        "offers": {
            "@type": "Offer",
            "price": "148",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    html = (
        "<html><body><main><h1>Cable-Knit Cotton Quarter-Zip Sweater</h1>"
        f"<div id='pdp-schema-objects' schema-productgroup='{json.dumps(product_group)}'>"
        "</div></main></body></html>"
    )

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/cable-knit-cotton-quarter-zip-sweater",
    )

    assert result.records[0]["brand"] == "Polo Ralph Lauren"
    assert result.records[0]["price"] == "148.00"
    assert result.records[0]["currency"] == "USD"


# --- Slice F: variant-option value semantics (§4.2) -------------------------


def test_is_rejected_option_value_gates_navigation_and_opaque_ids() -> None:
    """The value-level gate rejects the exact noise seen in run 2 while keeping
    genuine sizes/colors: 190 (SHOP BY TANK SIZE), 186 (Travel Sizes + Minis),
    134 (opaque Shopify variant ids), 110 (Shop By Color)."""
    from app.core.config.extraction_rules import is_rejected_option_value

    rejected = (
        "Shop SHOP BY TANK SIZE",
        "SHOP BY TANK SIZE",
        "Shop By Color",
        "Travel Sizes + Minis",
        "Travel Sizes",
        "Minis",
        "3 more colors",
        "42434363129927",
        "Compare",
    )
    for value in rejected:
        assert is_rejected_option_value(value) is True, value

    retained = (
        "Size 4-4.5",
        "Size 14-14.5 (not available)",
        "44",
        "9",
        "Heritage Royal",
        "Black",
        "XL",
        "EU 42",
    )
    for value in retained:
        assert is_rejected_option_value(value) is False, value


_CONTAMINATED_AXIS_HTML = """
<html><body><main><h1>Betta Fish</h1>
<form class="product-form">
  <select name="size" class="product-option-size">
    <option value="">Shop SHOP BY TANK SIZE</option>
    <option value="nav">SHOP BY TANK SIZE</option></select>
</form></main></body></html>
"""

_GENUINE_AXIS_HTML = """
<html><body><main><h1>Trail Shoe</h1>
<form class="product-form">
  <select name="size" class="product-option-size">
    <option value="">Choose</option>
    <option value="9">9</option><option value="10">10</option>
    <option value="11">11</option></select>
</form></main></body></html>
"""


def test_navigation_only_axis_raises_no_expected_axis_finding() -> None:
    """Petco 190: a size select whose only values are navigation phrases must
    not form an axis, so no false ``EXPECTED_VARIANT_AXIS_MISSING`` is raised."""
    result = _extract(
        "ecommerce_detail", _CONTAMINATED_AXIS_HTML, "https://shop.test/product/betta"
    )
    axis_findings = [
        finding
        for finding in result.findings
        if finding.rule_id == "EXPECTED_VARIANT_AXIS_MISSING"
    ]
    assert axis_findings == []


def test_genuine_size_axis_is_preserved() -> None:
    """The gate must not over-reject: a real numeric size axis still forms and
    still yields its ``EXPECTED_VARIANT_AXIS_MISSING`` completeness signal when
    the variants do not carry the axis value."""
    result = _extract(
        "ecommerce_detail", _GENUINE_AXIS_HTML, "https://shop.test/products/trail-shoe"
    )
    assert result.records[0]["title"] == "Trail Shoe"
    assert not result.records[0].get("variants")
    axis_findings = [
        finding
        for finding in result.findings
        if finding.rule_id == "EXPECTED_VARIANT_AXIS_MISSING"
    ]
    assert len(axis_findings) == 1
    metadata = axis_findings[0].metadata
    assert metadata["axis"] == "size"
    assert set(metadata["expected_values"]) == {"9", "10", "11"}
    assert metadata["variant_count"] == 0
    assert metadata["missing_variant_count"] == 0


# --- Slice G: shell / redirect terminal outcomes (§5.3/§5.4) --------------


_TITLE_ONLY_HTML = """
<html><head><title>Invitation</title></head>
<body><main><h1>Invitation</h1></main></body></html>
"""


def test_cross_host_redirect_with_title_only_record_is_semantic_shell() -> None:
    """Result 107: a product URL redirected to a site-closed subdomain and
    yielded only URL/title identity. It is terminal shell output, not a partial
    ecommerce product observation, even though transport returned HTTP 200."""
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _TITLE_ONLY_HTML,
        "https://siteclosed.shop.test/invitation.html",
        requested_url="https://www.shop.test/products/trail-shoe",
    )

    result = extract(request)

    assert result.verdict == "error"
    assert result.transport_outcome == "semantic_shell"
    assert result.records == ()


def test_on_site_title_only_product_remains_partial() -> None:
    """A thin same-URL product is incomplete, but URL thinness alone is not
    proof of a redirect shell. Existing partial/retry behavior must remain."""
    page_url = "https://shop.test/products/invitation"
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _TITLE_ONLY_HTML,
        page_url,
        requested_url=page_url,
    )

    result = extract(request)

    assert result.verdict == "partial"
    assert result.transport_outcome == "ok"
    assert len(result.records) == 1
