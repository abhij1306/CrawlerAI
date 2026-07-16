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
    assert result.evidence
    assert result.decisions
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "ecommerce_listing" for item in result.evidence)


def test_ecommerce_listing_uses_product_link_after_collection_link() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main><article class="product-card">
          <a href="/collections/shoes">Shop all shoes</a>
          <a href="/products/trail-shoe"><h2>Trail Shoe</h2><img src="shoe.jpg"></a>
          <span class="price">$129</span>
        </article></main>
        """,
        "https://shop.test/collections/all",
    )

    assert [row["url"] for row in result.records] == [
        "https://shop.test/products/trail-shoe"
    ]
    assert [row["title"] for row in result.records] == ["Trail Shoe"]


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
            </main>
            """,
            "https://shop.test/category/shoes",
            max_records=5,
        )

        assert [row["title"] for row in result.records] == ["Trail Shoe"]


def test_ecommerce_listing_preserves_brazilian_real_price_symbol() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <a href="/kit-2-cuecas/p" title="Kit 2 Cuecas">Kit 2 Cuecas</a>
            <span class="price">R$ 269</span>
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
        </section>
        """,
        "https://shop.test/collections/all",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows == [
        {
            "title": "Trail Shoe",
            "url": "https://shop.test/products/trail-shoe",
            "price": "129.00",
            "_lineage": rows[0]["_lineage"],
            "_subject_id": rows[0]["_subject_id"],
        }
    ]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "ecommerce_listing"
    assert payload["evidence"]
    assert payload["decisions"]


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
        </main>
        """,
        "https://shop.test/products",
        max_records=5,
    )
    assert [row["title"] for row in result.records] == ["Trail Shoe"]


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
        </main>
        <footer>
          <ul><li><a href="/returns/">Returns</a></li></ul>
        </footer>
        """,
        "https://shop.test/ca/en/c/mens/footwear-run/wid-example",
        max_records=20,
    )

    assert [row["title"] for row in result.records] == ["Norvan LD 4 Shoe"]
    assert [row["url"] for row in result.records] == [
        "https://shop.test/ca/en/shop/mens/norvan-ld-4-shoe"
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
          </ul>
        </main>
        """,
        "https://shop.test/category/shoes",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Trail Shoe"]


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
        </main>
        """,
        "https://shop.test/men/pants/",
        max_records=5,
    )

    assert len(result.records) == 1
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
                "</article></main>"
            )
        },
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Classic Fit Pants"
    assert result.records[0]["url"] == product_url
    assert result.records[0]["price"] == "$42.95"
    assert result.records[0]["image_url"] == (
        "https://shop.test/images/classic-fit-pants.jpg"
    )
    assert {row.artifact_id for row in result.evidence} == {"listing_visual_html"}


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
        </main>
        """,
        "https://shop.test/collections/pants",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Linen Pant"]


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
        </main>
        """,
        "https://shop.test/ca/en/c/mens/footwear",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Kragg Shoe Men's"]


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
