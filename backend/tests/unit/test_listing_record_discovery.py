"""Slice 4.2: structural record-boundary discovery is site-independent.

These tests encode the guarantees that the discovery algorithm must hold across
markup shapes WITHOUT any selectors or per-shape recognizers: it finds the
repeated content-rich product grid, collapses variant sub-links to one record
per card, and rejects navigation / promo noise.
"""

from __future__ import annotations

from app.extraction.documents import HtmlDocument
from app.extraction.listing_records import discover_listing_records

PAGE = "https://shop.test/clothing/dresses/"


def _urls(html: str, *, page_url: str = PAGE) -> list[str]:
    records = discover_listing_records(HtmlDocument("t", html), page_url=page_url)
    return [r.url for r in records]


def test_card_grid_found_and_nav_promo_rejected() -> None:
    html = """
    <html><body>
      <nav>
        <a href="/clothing/">Clothing</a>
        <a href="/shoes/">Shoes</a>
        <a href="/sale/">Sale</a>
      </nav>
      <div class="grid">
        <div class="card"><a href="/p/aida-dress-1001.html"><img src=x></a><span>$119</span></div>
        <div class="card"><a href="/p/mira-dress-1002.html"><img src=x></a><span>$99</span></div>
        <div class="card"><a href="/p/nova-dress-1003.html"><img src=x></a><span>$140</span></div>
      </div>
      <aside class="promo"><a href="/sale/"><img src=x>Shop the sale</a></aside>
    </body></html>
    """
    urls = _urls(html)
    assert [u.rsplit("/", 1)[-1] for u in urls] == [
        "aida-dress-1001.html",
        "mira-dress-1002.html",
        "nova-dress-1003.html",
    ]


def test_itemlist_shape_found_by_same_algorithm() -> None:
    # No product-URL marker, url-only anchors with images — the ItemList/<li>
    # shape must work through the identical code path as the card grid.
    html = """
    <html><body>
      <ol class="items">
        <li><a href="/toddler-shoe-2001"><img src=x></a></li>
        <li><a href="/kids-jacket-2002"><img src=x></a></li>
        <li><a href="/baby-hat-2003"><img src=x></a></li>
        <li><a href="/infant-sock-2004"><img src=x></a></li>
      </ol>
    </body></html>
    """
    urls = _urls(html)
    assert len(urls) == 4
    assert urls[0].endswith("/toddler-shoe-2001")


def test_variant_swatch_links_collapse_to_one_record_per_card() -> None:
    # Each card holds several colour-variant links to distinct URLs. Discovery
    # must return ONE record per card (top-down), not one per variant link.
    html = """
    <html><body>
      <div class="grid">
        <div class="card">
          <img src=x>
          <a href="/p/tee-red-1">Red</a>
          <a href="/p/tee-blue-1">Blue</a>
          <a href="/p/tee-green-1">Green</a>
          <span>$29</span>
        </div>
        <div class="card">
          <img src=x>
          <a href="/p/hood-red-2">Red</a>
          <a href="/p/hood-blue-2">Blue</a>
          <a href="/p/hood-green-2">Green</a>
          <span>$59</span>
        </div>
      </div>
    </body></html>
    """
    records = discover_listing_records(HtmlDocument("t", html), page_url=PAGE)
    assert len(records) == 2


def test_bare_text_link_grid_is_not_a_product_grid() -> None:
    # A large homogeneous grid of bare-text links (a footer sitemap) must NOT be
    # mistaken for products: no image, no price -> not content-rich.
    html = """
    <html><body>
      <ul class="sitemap">
        <li><a href="/help/returns">Returns</a></li>
        <li><a href="/help/shipping">Shipping</a></li>
        <li><a href="/help/contact">Contact</a></li>
        <li><a href="/help/faq">FAQ</a></li>
        <li><a href="/help/sizing">Sizing</a></li>
      </ul>
    </body></html>
    """
    assert _urls(html) == []


def test_no_records_when_no_same_site_product_anchors() -> None:
    html = """
    <html><body>
      <a href="https://other.example/p/x-1.html"><img src=x></a>
      <a href="https://third.example/p/y-2.html"><img src=x></a>
    </body></html>
    """
    assert _urls(html) == []


def test_mid_path_category_tiles_are_not_products() -> None:
    # Arcteryx-style category landing tiles nest the ``/c/`` marker mid-path with
    # an opaque terminal segment (``wid-...``). Each tile is content-rich (image)
    # and the tiles repeat homogeneously, so structural repetition alone would
    # promote them to "products". They must be rejected as category/landing URLs.
    html = """
    <html><body>
      <div class="grid">
        <div class="card">
          <a href="/ca/en/c/mens/footwear-climb/wid-abc"><img src=x></a>
          <span>Climb Footwear</span>
        </div>
        <div class="card">
          <a href="/ca/en/c/mens/footwear-hike/wid-abc"><img src=x></a>
          <span>Hike Footwear</span>
        </div>
        <div class="card">
          <a href="/ca/en/c/mens/footwear-run/wid-abc"><img src=x></a>
          <span>Run Footwear</span>
        </div>
      </div>
    </body></html>
    """
    assert _urls(html, page_url="https://arcteryx.com/ca/en/c/mens/footwear") == []


def test_product_nested_under_category_prefix_still_extracts() -> None:
    # A genuine product whose path nests under a category prefix must survive: the
    # terminal segment is a real product slug, so it is detail-like despite the
    # ``/c/`` prefix and must NOT be rejected as a category URL.
    html = """
    <html><body>
      <div class="grid">
        <div class="card">
          <a href="/ca/en/c/mens/norvan-ld-4-gtx-shoe-0397.html"><img src=x></a>
          <span>$260</span>
        </div>
        <div class="card">
          <a href="/ca/en/c/mens/kragg-approach-shoe-0078.html"><img src=x></a>
          <span>$180</span>
        </div>
      </div>
    </body></html>
    """
    urls = _urls(html, page_url="https://arcteryx.com/ca/en/c/mens/footwear")
    assert len(urls) == 2
    assert urls[0].endswith("/norvan-ld-4-gtx-shoe-0397.html")


def test_single_content_rich_result_is_not_a_dom_listing_boundary() -> None:
    # A lone card has no repeated-boundary proof. Detail-shaped or structured
    # recovery may still handle it, but the DOM listing floor must not publish it.
    html = """
    <html><body>
      <main>
        <div class="card"><a href="/p/only-dress-9001.html"><img src=x></a><span>$80</span></div>
      </main>
    </body></html>
    """
    urls = _urls(html)
    assert urls == []
