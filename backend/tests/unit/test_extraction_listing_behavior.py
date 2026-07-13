# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


def test_ecommerce_listing_cutover_materializes_with_lineage() -> None:
    html = """
    <main>
      <article class="product-card">
        <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
        <span class="price">$129.00</span>
        <img src="/images/trail.jpg">
      </article>
      <article class="product-card">
        <a href="/products/day-pack"><h2>Day Pack</h2></a>
        <span class="price">$89.00</span>
      </article>
    </main>
    """
    result = _extract(
        "ecommerce_listing",
        html,
        "https://shop.test/collections/all",
        max_records=5,
    )
    assert result.verdict == "success"
    assert result.recipe_execution is not None
    assert result.recipe_execution.outcomes
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    assert all(row["_lineage"]["title"] for row in result.records)


def test_ecommerce_listing_reads_hyphenated_data_test_id_product_cards() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <div data-test-id="product-card">
            <a href="/en-gb/p/men-10029/classic-boat-loafer-TB0A447GW01">
              <img
                src="/images/classic-boat-loafer.jpg"
                alt="Classic Boat Loafer for Men"
              >
              <span>Classic Boat Loafer for Men</span>
            </a>
            <span>£70.00</span>
          </div>
          <div data-test-id="product-card">
            <a href="/en-gb/p/men-10029/field-trekker-low-TB0A2A58015">
              <img src="/images/field-trekker.jpg" alt="Field Trekker Low">
              <span>Field Trekker Low</span>
            </a>
            <span>£65.00</span>
          </div>
        </main>
        """,
        "https://www.timberland.com/en-gb/c/sales/mens-sale-10185",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == [
        "Classic Boat Loafer for Men",
        "Field Trekker Low",
    ]


def test_ecommerce_listing_reads_drifted_test_data_product_card_attrs() -> None:
    for attr_name in ("test-data-id", "test-dataid"):
        result = _extract(
            "ecommerce_listing",
            f"""
            <main>
              <div {attr_name}="product-card">
                <a href="/p/trail-shoe" title="Trail Shoe">Trail Shoe</a>
                <span data-price="$99.00"></span>
              </div>
              <div {attr_name}="product-card">
                <a href="/p/day-pack" title="Day Pack">Day Pack</a>
                <span data-price="$79.00"></span>
              </div>
            </main>
            """,
            "https://shop.test/category/shoes",
            max_records=5,
        )

        assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}


def test_ecommerce_listing_preserves_brazilian_real_price_symbol() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <a href="/kit-2-cuecas/p" title="Kit 2 Cuecas">Kit 2 Cuecas</a>
            <span class="price">R$ 269</span>
          </article>
          <article class="product-card">
            <a href="/kit-3-cuecas/p" title="Kit 3 Cuecas">Kit 3 Cuecas</a>
            <span class="price">R$ 299</span>
          </article>
        </main>
        """,
        "https://www.calvinklein.com.br/masculino/underwear/kits-de-cueca",
        max_records=5,
    )

    assert result.records[0]["price"] == "R$ 269"


def test_ecommerce_listing_result_is_replayable() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <section>
          <div class="product-tile">
            <a href="/products/trail-shoe" title="Trail Shoe">Trail Shoe</a>
            <div data-price="129.00"></div>
          </div>
          <div class="product-tile">
            <a href="/products/day-pack" title="Day Pack">Day Pack</a>
            <div data-price="89.00"></div>
          </div>
        </section>
        """,
        "https://shop.test/collections/all",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert {(row["title"], row["url"], row["price"]) for row in rows} == {
        ("Trail Shoe", "https://shop.test/products/trail-shoe", "129.00"),
        ("Day Pack", "https://shop.test/products/day-pack", "89.00"),
    }
    assert all(row["_lineage"] and row["_subject_id"] for row in rows)
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "ecommerce_listing"
    assert payload["recipe_execution"]["outcomes"]


def test_ecommerce_listing_filters_docs_utility_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <li><a href="/docs" title="API">API</a></li>
          <li><a href="/file-download" title="File Download">File Download</a></li>
          <li><a href="/sitemap.xml" title="Sitemap">Sitemap</a></li>
          <div class="row product">
            <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
          </div>
          <div class="row product">
            <a href="/products/day-pack"><h2>Day Pack</h2></a>
          </div>
        </main>
        """,
        "https://shop.test/products",
        max_records=5,
    )
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}


def test_ecommerce_listing_rejects_site_chrome_and_unproven_category_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <header>
          <nav>
            <ul>
              <li><a href="/customer-service/">Customer Service</a></li>
              <li><a href="/ca/en/c/womens/">Women</a></li>
            </ul>
          </nav>
        </header>
        <main>
          <ul class="category-links">
            <li><a href="/ca/en/c/mens/footwear/">Men's Footwear</a></li>
            <li><a href="#">Store Directory</a></li>
          </ul>
          <article class="product-card">
            <a href="/ca/en/shop/mens/norvan-ld-4-shoe" title="Norvan LD 4 Shoe">
              <img src="/images/norvan.jpg">
            </a>
            <span class="price">$200.00</span>
          </article>
          <article class="product-card">
            <a href="/ca/en/shop/mens/norvan-ld-5-shoe" title="Norvan LD 5 Shoe">
              <img src="/images/norvan-5.jpg">
            </a>
            <span class="price">$210.00</span>
          </article>
        </main>
        <footer>
          <ul><li><a href="/returns/">Returns</a></li></ul>
        </footer>
        """,
        "https://shop.test/ca/en/c/mens/footwear-run/wid-example",
        max_records=20,
    )

    assert [row["title"] for row in result.records] == [
        "Norvan LD 4 Shoe",
        "Norvan LD 5 Shoe",
    ]
    assert [row["url"] for row in result.records] == [
        "https://shop.test/ca/en/shop/mens/norvan-ld-4-shoe",
        "https://shop.test/ca/en/shop/mens/norvan-ld-5-shoe",
    ]


def test_ecommerce_listing_restores_market_locale_shop_product_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <div data-product-id="category-card">
            <a href="/c/mens/footwear-climb/wid-kjyr4dq9">
              <img src="/images/climb.jpg" alt="A hiker on rocks">
              <span>Climb Footwear</span>
            </a>
          </div>
          <div data-product-id="x000010397">
            <a
              href="https://www.arcteryx.com/mens/norvan-ld-4-gtx-shoe-0397"
              title="Norvan LD 4 GTX Shoe Men's"
            >
              <img src="/images/norvan.jpg" alt="Norvan LD 4 GTX Shoe Men's">
            </a>
            <span class="price">$260.00</span>
          </div>
        </main>
        """,
        "https://arcteryx.com/ca/en/c/mens/footwear-run/wid-kjyr4dq9",
        max_records=20,
    )

    assert [row["title"] for row in result.records] == ["Norvan LD 4 GTX Shoe Men's"]
    assert [row["url"] for row in result.records] == [
        "https://www.arcteryx.com/ca/en/shop/mens/norvan-ld-4-gtx-shoe-0397"
    ]


def test_ecommerce_listing_empty_http_result_requests_browser_retry() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article><span class="price">15</span></article>
          <article><span class="price">20</span></article>
        </main>
        """,
        "https://www.calvinklein.com.br/masculino/underwear/kits-de-cueca",
        max_records=20,
    )

    assert result.records == ()
    assert result.verdict == "empty"
    assert result.retry_request is not None
    assert result.retry_request.required is True
    assert result.retry_request.reason == "empty_extraction"


def test_ecommerce_listing_keeps_generic_card_with_price_and_detail_link() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <ul>
            <li>
              <a href="/p/trail-shoe" title="Trail Shoe">Trail Shoe</a>
              <span class="price">$99.00</span>
            </li>
            <li>
              <a href="/p/day-pack" title="Day Pack">Day Pack</a>
              <span class="price">$79.00</span>
            </li>
          </ul>
        </main>
        """,
        "https://shop.test/category/shoes",
        max_records=5,
    )

    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}


def test_ecommerce_listing_reads_product_tile_metadata_after_image_link() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <div
            data-tile-type="product"
            data-cnstrc-item-name="Classic Fit Pants"
            data-cnstrc-item-id="SKU123"
          >
            <a href="/p/classic-fit-pants/SKU123.html">
              <img src="/images/classic-fit-pants.jpg" alt="Classic Fit Pants">
            </a>
            <a href="/p/classic-fit-pants/SKU123.html">Classic Fit Pants</a>
            <span>31-Inch Inseam</span>
            <span>$42.95</span>
          </div>
          <div
            data-tile-type="product"
            data-cnstrc-item-name="Slim Fit Pants"
            data-cnstrc-item-id="SKU124"
          >
            <a href="/p/slim-fit-pants/SKU124.html">
              <img src="/images/slim-fit-pants.jpg" alt="Slim Fit Pants">
            </a>
            <a href="/p/slim-fit-pants/SKU124.html">Slim Fit Pants</a>
            <span>$44.95</span>
          </div>
        </main>
        """,
        "https://shop.test/men/pants/",
        max_records=5,
    )

    assert len(result.records) == 2
    assert result.records[0]["title"] == "Classic Fit Pants"
    assert (
        result.records[0]["url"] == "https://shop.test/p/classic-fit-pants/SKU123.html"
    )
    assert result.records[0]["price"] == "$42.95"
    assert (
        result.records[0]["image_url"]
        == "https://shop.test/images/classic-fit-pants.jpg"
    )


def test_ecommerce_listing_uses_browser_visual_artifact_when_html_has_no_cards() -> (
    None
):
    product_url = "https://shop.test/p/classic-fit-pants/SKU123.html"
    result = _extract(
        "ecommerce_listing",
        "<main><h1>Men's Pants</h1></main>",
        "https://shop.test/men/pants/",
        max_records=5,
        artifacts={
            "listing_visual_html": (
                '<main><article data-product-id="visual-0">'
                f'<a href="{product_url}" title="View product">View product</a>'
                f'<a href="{product_url}" title="Classic Fit Pants">Classic Fit Pants</a>'
                '<img src="https://shop.test/images/classic-fit-pants.jpg">'
                '<span class="price">$42.95</span>'
                '</article><article data-product-id="visual-1">'
                '<a href="https://shop.test/p/slim-fit-pants/SKU124.html" title="Slim Fit Pants">Slim Fit Pants</a>'
                '<img src="https://shop.test/images/slim-fit-pants.jpg">'
                '<span class="price">$44.95</span>'
                "</article></main>"
            )
        },
    )

    assert len(result.records) == 2
    assert result.records[0]["title"] == "Classic Fit Pants"
    assert result.records[0]["url"] == product_url
    assert result.records[0]["price"] == "$42.95"
    assert result.records[0]["image_url"] == (
        "https://shop.test/images/classic-fit-pants.jpg"
    )
    assert all(
        "listing_visual_html" in row["_lineage"]["title"]["source_path"]
        for row in result.records
    )


def test_ecommerce_listing_uses_one_artifact_when_capture_sources_overlap() -> None:
    html = """
    <main>
      <article class="product-card">
        <a href="/p/trail-shoe" title="Trail Shoe">Trail Shoe</a>
        <span class="price">$99.00</span>
      </article>
      <article class="product-card">
        <a href="/p/day-pack" title="Day Pack">Day Pack</a>
        <span class="price">$79.00</span>
      </article>
    </main>
    """
    result = _extract(
        "ecommerce_listing",
        html,
        "https://shop.test/category/shoes",
        max_records=5,
        artifacts={"listing_visual_html": html},
    )

    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}


def test_ecommerce_listing_accepts_same_site_subdomain_detail_url() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <a href="https://www.shop.test/products/trail-shoe" title="Trail Shoe">
              <img src="/images/trail-shoe.jpg">
            </a>
            <span class="price">$120.00</span>
          </article>
          <article class="product-card">
            <a href="https://external.test/products/other" title="Other Shoe">
              <img src="/images/other-shoe.jpg">
            </a>
            <span class="price">$90.00</span>
          </article>
        </main>
        """,
        "https://m.shop.test/collections/shoes",
        max_records=5,
    )

    assert [row["url"] for row in result.records] == [
        "https://www.shop.test/products/trail-shoe"
    ]


def test_ecommerce_listing_rejects_selected_state_as_product_title() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <button class="product-title" aria-selected="true">Cor selecionada</button>
            <a href="/products/linen-pant" aria-label="View product">
              <img src="/images/linen-pant.jpg">
            </a>
            <span class="price">$79.00</span>
          </article>
        </main>
        """,
        "https://shop.test/collections/pants",
        max_records=5,
    )

    assert not result.records


def test_ecommerce_listing_uses_title_from_product_link_scope() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <button class="product-title" aria-selected="true">Selected blue</button>
            <a href="/products/linen-pant" title="Linen Pant">Shop now</a>
            <span class="price">$79.00</span>
          </article>
          <article class="product-card">
            <a href="/products/canvas-pant" title="Canvas Pant">Shop now</a>
            <span class="price">$89.00</span>
          </article>
        </main>
        """,
        "https://shop.test/collections/pants",
        max_records=5,
    )

    assert {row["title"] for row in result.records} == {"Linen Pant", "Canvas Pant"}


def test_ecommerce_listing_excludes_inline_style_source_from_title() -> None:
    # A product card carrying an inline <style> block must not leak the CSS
    # source (e.g. a selector string) into the scraped title. Reproduces the
    # phase-eight capture where `.product-tile__sticker--image:has(...)` surfaced
    # as a product title.
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-tile">
            <a href="/product/aida-black-shift-dress-10024280250.html" class="product-tile__title">
              <style>
                .product-tile__sticker--image:has(img.lockup-sticker) { top: 10px; }
                .lockup-sticker { max-width: 100px; height: auto; }
              </style>
              Aida Black Shift Dress
            </a>
            <span class="price">$119.00</span>
          </article>
        </main>
        """,
        "https://shop.test/clothing/dresses/",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Aida Black Shift Dress"]
    assert all(":has(" not in row["title"] for row in result.records)


@pytest.mark.parametrize("badge", ("New colour", "Best seller"))
def test_ecommerce_listing_skips_merchandising_badge_for_product_title(
    badge: str,
) -> None:
    result = _extract(
        "ecommerce_listing",
        f"""
        <main>
          <article class="product-card">
            <a href="/shop/mens/kragg-shoe-0078"><span>{badge}</span></a>
            <a href="/shop/mens/kragg-shoe-0078"><h2>Kragg Shoe Men's</h2></a>
            <img src="/images/kragg-shoe.jpg">
            <span class="price">$180.00</span>
          </article>
          <article class="product-card">
            <a href="/shop/mens/norvan-shoe-0079"><h2>Norvan Shoe Men's</h2></a>
            <img src="/images/norvan-shoe.jpg">
            <span class="price">$190.00</span>
          </article>
        </main>
        """,
        "https://shop.test/ca/en/c/mens/footwear",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == [
        "Kragg Shoe Men's",
        "Norvan Shoe Men's",
    ]


def test_ecommerce_listing_rejects_utility_url_families() -> None:
    utility_paths = (
        "/support/product-care",
        "/legal/accessibility",
        "/stores/city-directory",
        "/gift-registry/create",
        "/ca/en/help/product-care",
        "/mobile-app/download",
        "/athletes/team",
        "/ambassadors/join",
    )
    cards = "".join(
        f'<article class="product-card"><a href="{path}"><h2>Trail Shoe</h2></a></article>'
        for path in utility_paths
    )
    result = _extract(
        "ecommerce_listing",
        f"<main>{cards}</main>",
        "https://shop.test/collections/all",
        max_records=20,
    )

    assert not result.records


def test_ecommerce_listing_rejects_utility_label_as_title() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <article class="product-card">
          <a href="/products/trail-shoe" title="Customer Service">Learn more</a>
          <span class="price">$99.00</span>
        </article>
        """,
        "https://shop.test/collections/all",
        max_records=5,
    )

    assert not result.records


_ITEMLIST_LISTING = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
 {"@type":"ListItem","url":"https://shop.test/p/aida-1001.html",
  "item":{"@type":"Product","name":"Aida Dress",
    "offers":{"@type":"Offer","price":"119.00"},"image":"https://img.test/a.jpg"}},
 {"@type":"ListItem","url":"https://shop.test/p/mira-1002.html",
  "item":{"@type":"Product","name":"Mira Dress",
    "offers":{"@type":"Offer","price":"99.00"},"image":"https://img.test/m.jpg"}}
]}
</script></head>
<body><div class="grid">
 <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$119</span></div>
 <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$99</span></div>
</div></body></html>
"""


def test_ecommerce_listing_tier0_structured_floor_resolves_without_llm() -> None:
    # When every discovered record grounds to a structured source, the listing
    # resolves through the Tier 0 floor: structured-floor lineage, no LLM.
    result = _extract(
        "ecommerce_listing",
        _ITEMLIST_LISTING,
        "https://shop.test/c/dresses/",
        max_records=10,
    )
    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {"Aida Dress", "Mira Dress"}
    assert {row["url"] for row in result.records} == {
        "https://shop.test/p/aida-1001.html",
        "https://shop.test/p/mira-1002.html",
    }
    # Every published fact is sourced from the structured floor collector...
    assert all(
        row["_field_sources"]["title"] == ["listing_structured_floor"]
        for row in result.records
    )
    # ...and the floor spends zero LLM invocations (acquire-cheap fast path).
    assert result.metrics.universal_model_invocation_count == 0


def test_ecommerce_listing_without_structured_data_falls_through_to_css() -> None:
    # No JSON-LD: Tier 0 must not hold, so the CSS card collector still resolves
    # the listing (the generalized/recipe tiers replace it in a later slice).
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
            <span class="price">$129.00</span>
            <img src="/images/trail.jpg">
          </article>
          <article class="product-card">
            <a href="/products/day-pack"><h2>Day Pack</h2></a>
            <span class="price">$89.00</span>
          </article>
        </main>
        """,
        "https://shop.test/collections/all",
        max_records=5,
    )
    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    # Fell through — structured floor did not claim this page.
    assert "listing_structured_floor" not in {
        row.collector_id for row in result.evidence
    }
