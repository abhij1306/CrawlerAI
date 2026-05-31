from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.extract.detail.assembly import dom_completion as detail_dom_completion
from app.services.extract.detail.images import materialize as detail_image_materialize
from app.services.extract.detail.identity import (
    structured_pruning as detail_structured_pruning,
)
from app.services.config._export_data import load_export_data
from app.services.extraction_context import (
    ExtractionContext,
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.pipeline.extract_records import extract_records
from app.services.selector_self_heal import (
    validated_xpath_rules,
    selector_heal_improved_record,
    reduce_html_for_selector_synthesis,
    selector_self_heal_targets,
)

requires_dom_completion = detail_dom_completion._requires_dom_completion
materialize_image_fields = detail_image_materialize._materialize_image_fields
prune_irrelevant_detail_structured_payload = (
    detail_structured_pruning._prune_irrelevant_detail_structured_payload
)


@pytest.mark.regression
def test_extract_records_prefers_higher_priority_adapter_value_even_when_dom_value_exists() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <span class="price">$999.99</span>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price"],
        adapter_records=[{"price": "19.99", "_source": "adapter"}],
    )[0]

    assert record["title"] == "Widget Prime"
    assert record["price"] == "19.99"
    assert "adapter" in str(record["_field_sources"]["price"])
    assert "dom_selector" in str(record["_field_sources"]["price"])
    assert record["_source"] == "adapter"


def testrequires_dom_completion_uses_raw_variant_cues_after_pruning() -> None:
    soup = BeautifulSoup("<main><h1>Widget</h1></main>", "html.parser")
    raw_soup = BeautifulSoup(
        """
        <main>
          <form class="product-form">
            <select name="size"><option>S</option><option>M</option></select>
          </form>
        </main>
        """,
        "html.parser",
    )

    assert requires_dom_completion(
        record={"title": "Widget", "image_url": "https://example.com/widget.jpg"},
        surface="ecommerce_detail",
        requested_fields=None,
        selector_rules=None,
        soup=soup,
        breadcrumb_soup=raw_soup,
    )


def testrequires_dom_completion_ignores_logo_only_image_cue() -> None:
    """Generic page images should not force detail DOM completion."""
    soup = BeautifulSoup("<main><h1>Widget</h1></main>", "html.parser")
    raw_soup = BeautifulSoup(
        """
        <header>
          <img class="site-logo" src="/logo.png" />
        </header>
        """,
        "html.parser",
    )

    assert not requires_dom_completion(
        record={"title": "Widget"},
        surface="ecommerce_detail",
        requested_fields=None,
        selector_rules=None,
        soup=soup,
        breadcrumb_soup=raw_soup,
    )


@pytest.mark.regression
def test_requires_dom_completion_when_structured_category_conflicts_with_dom_breadcrumb() -> None:
    soup = BeautifulSoup(
        """
        <html><body>
          <nav aria-label="Breadcrumb">
            <a>Home</a><a>Women</a><a>Bags</a>
          </nav>
          <main><h1>Widget Bag</h1><img src="/bag.jpg"><span>$10</span></main>
        </body></html>
        """,
        "html.parser",
    )

    assert requires_dom_completion(
        record={
            "title": "Widget Bag",
            "category": "Women > Shoes",
            "price": "10",
            "image_url": "https://example.com/bag.jpg",
            "url": "https://example.com/products/widget-bag",
        },
        surface="ecommerce_detail",
        requested_fields=[],
        selector_rules=[],
        soup=soup,
        breadcrumb_soup=soup,
    )


@pytest.mark.regression
def test_requires_dom_completion_skips_unrequested_variant_probe_for_complete_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    soup = BeautifulSoup("<main><h1>Widget</h1></main>", "html.parser")
    raw_soup = BeautifulSoup(
        """
        <main>
          <form class="product-form">
            <select name="size"><option>S</option><option>M</option></select>
          </form>
        </main>
        """,
        "html.parser",
    )

    def _unexpected_variant_probe(_soup: BeautifulSoup) -> bool:
        raise AssertionError("variant DOM probe should be skipped for complete records")

    monkeypatch.setattr(
        detail_dom_completion,
        "variant_dom_cues_present",
        _unexpected_variant_probe,
    )

    assert not requires_dom_completion(
        record={
            "title": "Widget",
            "price": "10.00",
            "image_url": "https://example.com/widget.jpg",
            "url": "https://example.com/products/widget",
            "description": (
                "This widget description is intentionally long enough to avoid thin-content "
                "fallback and it explains the product materials, use cases, durability, "
                "fit, setup expectations, support policy, and care guidance in plain language."
            ),
            "product_details": (
                "Widget details include materials, dimensions, warranty coverage, "
                "compatibility notes, and usage guidance for normal operation."
            ),
            "additional_images": ["https://example.com/widget-2.jpg"],
            "specifications": "Material: Steel",
            "_field_sources": {
                "description": ["adapter"],
                "product_details": ["adapter"],
                "specifications": ["adapter"],
            },
        },
        surface="ecommerce_detail",
        requested_fields=None,
        selector_rules=None,
        soup=soup,
        breadcrumb_soup=raw_soup,
    )


@pytest.mark.regression
def test_prepare_extraction_context_caches_original_dom_objects() -> None:
    context = prepare_extraction_context(
        "<html><body><main><h1>Widget</h1></main></body></html>"
    )

    cached_soup = context.original_soup
    cached_dom_parser = context.original_dom_parser
    assert context.original_soup is cached_soup
    assert context.original_dom_parser is cached_dom_parser


@pytest.mark.regression
def test_collect_structured_source_payloads_extracts_vtex_string_price_from_id_ref() -> (
    None
):
    html = "<html><body><main><h1>Widget</h1></main></body></html>"
    state = {
        "Product:sp-1": {
            "productId": "1",
            "productName": "Widget One",
            "linkText": "widget-one",
            "priceRange": {
                "sellingPrice": {
                    "type": "id",
                    "id": "$Product:sp-1.priceRange.sellingPrice",
                }
            },
            "items": [{"type": "id", "id": "sku-1"}],
        },
        "$Product:sp-1.priceRange.sellingPrice": {
            "lowPrice": "21.00",
        },
        "sku-1": {
            "images": [
                {
                    "imageUrl": "https://cdn.example.com/widget-one.jpg",
                }
            ]
        },
        "Product:sp-2": {
            "productId": "2",
            "productName": "Widget Two",
            "linkText": "widget-two",
            "priceRange": {
                "sellingPrice": {
                    "lowPrice": 33.0,
                }
            },
            "items": [{"images": [{"imageUrl": "https://cdn.example.com/widget-two.jpg"}]}],
        },
    }
    context = ExtractionContext(
        original_html=html,
        cleaned_html=html,
        dom_parser=LexborHTMLParser(html),
        _js_state_objects={"__STATE__": state},
    )

    payloads = collect_structured_source_payloads(
        context,
        page_url="https://store.example.com/collections/widgets",
        surface="ecommerce_listing",
    )

    embedded_json = dict(payloads)["embedded_json"]
    item_list = embedded_json[0]["itemListElement"]
    first_item = item_list[0]["item"]

    assert first_item["offers"]["price"] == 21.0
    assert first_item["image"] == "https://cdn.example.com/widget-one.jpg"


@pytest.mark.regression
def test_collect_structured_source_payloads_extracts_vtex_string_price_from_fallbacks() -> (
    None
):
    html = "<html><body><main><h1>Widget</h1></main></body></html>"
    state = {
        "Product:sp-1": {
            "productId": "1",
            "productName": "Widget One",
            "linkText": "widget-one",
            "items": [{"images": [{"imageUrl": "https://cdn.example.com/widget-one.jpg"}]}],
        },
        "$Product:sp-1.priceRange.sellingPrice": {
            "highPrice": "41.50",
        },
        "Product:sp-2": {
            "productId": "2",
            "productName": "Widget Two",
            "linkText": "widget-two",
            "items": [{"images": [{"imageUrl": "https://cdn.example.com/widget-two.jpg"}]}],
        },
        "$Product:sp-2.items.0.sellers.0.commertialOffer": {
            "Price": "55.25",
        },
    }
    context = ExtractionContext(
        original_html=html,
        cleaned_html=html,
        dom_parser=LexborHTMLParser(html),
        _js_state_objects={"__STATE__": state},
    )

    payloads = collect_structured_source_payloads(
        context,
        page_url="https://store.example.com/collections/widgets",
        surface="ecommerce_listing",
    )

    embedded_json = dict(payloads)["embedded_json"]
    item_list = embedded_json[0]["itemListElement"]

    assert item_list[0]["item"]["offers"]["price"] == 41.5
    assert item_list[1]["item"]["offers"]["price"] == 55.25


@pytest.mark.regression
def test_apply_dom_fallbacks_limits_heading_section_targets_to_section_like_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.extract.detail.assembly import (
        dom_fallbacks as detail_dom_fallbacks,
    )

    captured: dict[str, set[str]] = {}

    def _fake_extract_heading_sections(
        _soup,
        *,
        alias_lookup=None,
        allowed_fields=None,
    ) -> dict[str, str]:
        captured["allowed_fields"] = set(allowed_fields or ())
        return {}

    monkeypatch.setattr(
        detail_dom_fallbacks,
        "extract_heading_sections",
        _fake_extract_heading_sections,
    )

    html = "<html><body><main><h1>Widget</h1></main></body></html>"
    detail_dom_fallbacks.apply_dom_fallbacks(
        LexborHTMLParser(html),
        BeautifulSoup(html, "html.parser"),
        page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=["brand", "product_story"],
        candidates={},
        candidate_sources={},
        field_sources={},
        selector_trace_candidates={},
        selector_rules=None,
        add_sourced_candidate=lambda *args, **kwargs: None,
    )

    assert "description" in captured["allowed_fields"]
    assert "materials" in captured["allowed_fields"]
    assert "product_story" in captured["allowed_fields"]
    assert "brand" not in captured["allowed_fields"]


def testprune_irrelevant_detail_structured_payload_reuses_requested_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"title": 0, "tokens": 0, "codes": 0}

    def _fake_title_from_url(_url: str) -> str:
        calls["title"] += 1
        return "widget"

    def _fake_identity_tokens(_value: object) -> set[str]:
        calls["tokens"] += 1
        return {"widget"}

    def _fake_identity_codes_from_url(_url: str) -> set[str]:
        calls["codes"] += 1
        return {"sku123"}

    monkeypatch.setattr(
        "app.services.extract.detail.identity.structured_pruning._detail_title_from_url",
        _fake_title_from_url,
    )
    monkeypatch.setattr(
        "app.services.extract.detail.identity.structured_pruning._detail_identity_tokens",
        _fake_identity_tokens,
    )
    monkeypatch.setattr(
        "app.services.extract.detail.identity.structured_pruning._detail_identity_codes_from_url",
        _fake_identity_codes_from_url,
    )

    payload = {
        "offers": [
            {"@type": "Offer", "price": "19.99"},
            {
                "@type": "Product",
                "name": "Other Widget",
                "url": "https://example.com/products/other-widget",
                "sku": "OTHER123",
            },
            {
                "@type": "Product",
                "name": "Widget",
                "url": "https://example.com/products/widget",
                "sku": "SKU123",
            },
        ]
    }

    pruned = prune_irrelevant_detail_structured_payload(
        payload,
        page_url="https://example.com/products/widget",
        requested_page_url="https://example.com/products/widget",
    )

    assert pruned is not None
    assert calls == {"title": 1, "tokens": 1, "codes": 1}


def testmaterialize_image_fields_merges_raw_soup_gallery_when_structured_is_single() -> (
    None
):
    raw_soup = BeautifulSoup(
        """
        <main>
          <section class="product-gallery">
            <img data-lazy-src="/images/widget-1.jpg" />
            <img data-lazy-src="/images/widget-2.jpg" />
          </section>
        </main>
        """,
        "html.parser",
    )

    images, source = materialize_image_fields(
        surface="ecommerce_detail",
        candidates={"image_url": ["https://example.com/images/widget-cover.jpg"]},
        candidate_sources={"image_url": ["json_ld"]},
        page_url="https://example.com/products/widget",
        soup=BeautifulSoup("<main></main>", "html.parser"),
        raw_soup=raw_soup,
    )

    assert images == [
        "https://example.com/images/widget-cover.jpg",
        "https://example.com/images/widget-1.jpg",
        "https://example.com/images/widget-2.jpg",
    ]
    assert source == "json_ld"


@pytest.mark.regression
def test_extract_records_does_not_fabricate_discount_percentage_from_unrelated_body_text() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Elowen Wide Leg Jumpsuit</h1>
          <p>Composition: 100% cotton. Care at 30 degrees. Free shipping over 50.</p>
          <span class="price">£149.00</span>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://www.phase-eight.com/product/elowen-wide-leg-jumpsuit-10022060230.html",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price", "discount_percentage"],
    )[0]

    assert "discount_percentage" not in record
    assert "discount_percentage" not in record.get("_field_sources", {})


@pytest.mark.regression
def test_extract_records_applies_selector_rules_and_tracks_selector_source() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="product-description">Built for long mileage.</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
        selector_rules=[
            {
                "field_name": "description",
                "css_selector": ".product-description",
                "is_active": True,
            }
        ],
    )[0]

    assert record["description"] == "Built for long mileage."
    assert record["_field_sources"]["description"] == ["dom_selector"]


@pytest.mark.regression
def test_extract_records_keeps_first_match_for_long_text_fields() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="product-description">DOM fallback description.</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
        adapter_records=[{"description": "Adapter description."}],
        selector_rules=[
            {
                "field_name": "description",
                "css_selector": ".product-description",
                "is_active": True,
            }
        ],
    )[0]

    assert record["description"] == "Adapter description."
    assert "adapter" in str(record["_field_sources"]["description"])
    assert "dom_selector" in str(record["_field_sources"]["description"])
    assert record["_source"] == "adapter"


@pytest.mark.regression
def test_extract_records_uses_accordion_dom_sections_for_long_text_fields() -> None:
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <button aria-controls="description-panel">Description</button>
          <section id="description-panel">
            Built for long mileage with a reinforced toe cap.
          </section>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["description"],
    )[0]

    assert record["description"] == "Built for long mileage with a reinforced toe cap."
    assert record["_field_sources"]["description"] == ["dom_sections"]


@pytest.mark.regression
def test_extract_records_uses_nested_wrapped_dom_sections_for_long_text_fields() -> (
    None
):
    html = """
    <html>
      <body>
        <main>
          <h1>Widget Prime</h1>
          <div class="accordion-item">
            <button>Specifications</button>
            <div class="accordion-item__body">
              <div class="rich-content">
                Rubber outsole with a reinforced toe cap.
              </div>
            </div>
          </div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["specifications"],
    )[0]

    assert record["specifications"] == "Rubber outsole with a reinforced toe cap."
    assert record["_field_sources"]["specifications"] == ["dom_sections"]


@pytest.mark.regression
def test_extract_records_applies_regex_as_post_filter_to_xpath_result() -> None:
    html = """
    <html>
      <body>
        <script>window.badSku = "SKU: 99999";</script>
        <main>
          <div class="sku">SKU: 12345</div>
        </main>
      </body>
    </html>
    """
    record = extract_records(
        html,
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["sku"],
        selector_rules=[
            {
                "field_name": "sku",
                "xpath": "//div[@class='sku']/text()",
                "regex": r"SKU:\s*(\d+)",
                "is_active": True,
            }
        ],
    )[0]

    assert record["sku"] == "12345"
    assert record["_field_sources"]["sku"] == ["dom_selector"]


@pytest.mark.regression
def test_selector_self_heal_config_falls_back_to_runtime_enabled_when_missing(
    patch_settings,
) -> None:
    patch_settings(
        selector_self_heal_enabled=True,
        selector_self_heal_min_confidence=0.77,
    )
    record = extract_records(
        "<html><body><h1>Widget Prime</h1></body></html>",
        "https://example.com/products/widget-prime",
        "ecommerce_detail",
        max_records=1,
        extraction_runtime_snapshot={
            "selector_self_heal": {"enabled": None, "min_confidence": None}
        },
    )[0]

    assert record["_self_heal"] == {
        "enabled": True,
        "triggered": False,
        "threshold": 0.77,
    }


@pytest.mark.regression
def test_selector_self_heal_targets_default_ecommerce_fields_when_requested_empty() -> (
    None
):
    class _Run:
        surface = "ecommerce_detail"
        requested_fields: list[str] = []

    targets = selector_self_heal_targets(
        run=_Run(),  # type: ignore[arg-type]
        record={"title": "Widget Prime", "price": ""},
    )

    assert "price" in targets
    assert "image_url" in targets
    assert "variants" not in targets


@pytest.mark.regression
def test_reduce_html_for_selector_synthesis_keeps_valid_content_focused_html() -> None:
    nav_noise = "".join(
        f"<a href='/collections/widgets/{index}'>Noise {index}</a>"
        for index in range(9_000)
    )
    html = f"""
    <html>
      <body>
        <nav>{nav_noise}</nav>
        <main id="product-detail">
          <article class="product">
            <h1>Widget Prime</h1>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </article>
        </main>
        <script>window.__NOISE__ = true;</script>
      </body>
    </html>
    """

    reduced = reduce_html_for_selector_synthesis(html)
    from bs4 import BeautifulSoup

    parsed = BeautifulSoup(reduced, "html.parser")
    main = parsed.find("main", attrs={"id": "product-detail"})

    assert len(reduced) <= 200_000
    assert parsed.find("nav") is None
    assert parsed.find("script") is None
    assert main is not None
    assert main.find("article", attrs={"class": "product"}) is not None
    assert "Widget Prime" in main.get_text(" ", strip=True)
    assert "Rubber outsole, reinforced toe cap." in main.get_text(" ", strip=True)


@pytest.mark.regression
def test_reduce_html_for_selector_synthesis_preserves_shadow_root_boundaries() -> None:
    reduced = reduce_html_for_selector_synthesis(
        """
        <html>
          <body>
            <product-shell>
              <template shadowrootmode="open">
                <section class="details">
                  <h2>Specs</h2>
                  <div slot="content">Waterproof membrane</div>
                </section>
              </template>
            </product-shell>
          </body>
        </html>
        """
    )

    assert "template" in reduced
    assert 'shadowrootmode="open"' in reduced
    assert "Waterproof membrane" in reduced


@pytest.mark.regression
def test_reduce_html_for_selector_synthesis_preserves_price_and_buy_box_controls() -> (
    None
):
    reduced = reduce_html_for_selector_synthesis(
        """
        <html><body>
          <main>
            <form class="buy-box" data-product-id="sku-1">
              <span class="price" data-price="229.99" itemprop="price">$229.99</span>
              <button type="button" aria-label="Size 9" data-variant-id="v9">9</button>
              <input name="sku" data-sku="sku-1" value="sku-1" />
            </form>
          </main>
        </body></html>
        """
    )

    assert 'data-price="229.99"' in reduced
    assert 'itemprop="price"' in reduced
    assert 'aria-label="Size 9"' in reduced
    assert 'data-variant-id="v9"' in reduced
    assert 'data-sku="sku-1"' in reduced
    assert 'value="sku-1"' in reduced


@pytest.mark.regression
def test_selector_synthesis_keep_worthy_tags_are_code_owned() -> None:
    from app.services.config.selectors import SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS

    exports = load_export_data(
        str(
            Path(__file__).parents[2]
            / "app"
            / "services"
            / "config"
            / "selectors.exports.json"
        )
    )

    assert "SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS" not in exports
    assert SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS == frozenset(
        {"button", "input", "select"}
    )


@pytest.mark.regression
def test_extract_records_deep_merges_structured_variant_fields_across_tiers() -> None:
    html = """
    <html>
      <body>
        <h1>Trail Runner</h1>
        <label>
          Color
          <select name="color">
            <option value="">Choose color</option>
            <option value="black">Black</option>
            <option value="olive">Olive</option>
          </select>
        </label>
      </body>
    </html>
    """

    extract_records(
        html,
        "https://example.com/products/trail-runner",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["variant_axes", "selected_variant"],
        adapter_records=[
            {
                "variant_axes": {"size": ["S", "M"]},
                "selected_variant": {
                    "sku": "TRAIL-S",
                    "option_values": {"size": "S"},
                },
            }
        ],
    )[0]


@pytest.mark.regression
def test_selector_self_heal_requires_field_level_improvement_before_persisting() -> (
    None
):
    assert (
        selector_heal_improved_record(
            before_record={"title": "Widget Prime", "price": ""},
            after_record={"title": "Widget Prime", "price": "19.99"},
            target_fields=["price"],
        )
        is True
    )
    assert (
        selector_heal_improved_record(
            before_record={"title": "Widget Prime", "price": ""},
            after_record={"title": "Widget Prime", "price": ""},
            target_fields=["price"],
        )
        is False
    )


@pytest.mark.regression
def test_selector_self_heal_converts_css_candidates_before_persisting_xpath() -> None:
    rules = validated_xpath_rules(
        html="""
        <html>
          <body>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </body>
        </html>
        """,
        candidates=[
            {
                "field_name": "specifications",
                "xpath": "div.custom-specs",
            }
        ],
        target_fields=["specifications"],
    )

    assert len(rules) == 1
    assert rules[0]["sample_value"] == "Rubber outsole, reinforced toe cap."
    assert str(rules[0]["xpath"]).startswith("//div")


@pytest.mark.regression
def test_selector_self_heal_persists_valid_css_candidates_as_css_rules() -> None:
    rules = validated_xpath_rules(
        html="""
        <html>
          <body>
            <div class="custom-specs">Rubber outsole, reinforced toe cap.</div>
          </body>
        </html>
        """,
        candidates=[
            {
                "field_name": "specifications",
                "css_selector": ".custom-specs",
            }
        ],
        target_fields=["specifications"],
    )

    assert rules == [
        {
            "field_name": "specifications",
            "css_selector": ".custom-specs",
            "xpath": None,
            "regex": None,
            "sample_value": "Rubber outsole, reinforced toe cap.",
            "source": "selector_self_heal",
            "status": "validated",
            "is_active": True,
        }
    ]


@pytest.mark.regression
def test_extract_records_tracks_dom_observed_selector_traces_for_final_dom_fields() -> None:
    record = extract_records(
        """
        <html>
          <body>
            <main>
              <h1>DOM Observed Widget</h1>
              <span class="price">$19.99</span>
            </main>
          </body>
        </html>
        """,
        "https://example.com/products/dom-observed-widget",
        "ecommerce_detail",
        max_records=1,
    )[0]

    traces = record["_selector_traces"]
    assert traces["title"]["selector_kind"] == "css_selector"
    assert traces["title"]["selector_value"] == "h1"
    assert traces["title"]["selector_source"] == "dom_observed"
    assert traces["price"]["selector_kind"] == "css_selector"
    assert (
        traces["price"]["selector_value"]
        == "[itemprop='price'], .price, .product-price"
    )
    assert traces["price"]["selector_source"] == "dom_observed"
