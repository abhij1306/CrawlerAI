"""Slice 4.3: Tier 0 structured floor grounds discovered records with no LLM.

The floor holds only when EVERY discovered record joins to a structured source
by url-identity. These tests pin that all-or-nothing contract, the JSON-LD
shapes it must read (``ItemList``/``ListItem`` and a bare ``Product`` array),
and that non-structured pages fall through (return ``None``) so the caller can
reach the generalized tier.
"""

from __future__ import annotations

from app.extraction.documents import HtmlDocument
from app.extraction.listing_records import discover_listing_records
from app.extraction.listing_tier0 import ground_boundaries

PAGE = "https://shop.test/c/dresses/"


def _ground(html: str):
    doc = HtmlDocument("t", html)
    boundaries = discover_listing_records(doc, page_url=PAGE)
    return boundaries, ground_boundaries(doc, boundaries, page_url=PAGE)


_ITEMLIST = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
  {"@type":"ListItem","url":"https://shop.test/p/aida-1001.html",
   "item":{"@type":"Product","name":"Aida Dress",
     "offers":{"@type":"Offer","price":"119.00"},"image":"https://img.test/a.jpg"}},
  {"@type":"ListItem","url":"https://shop.test/p/mira-1002.html",
   "item":{"@type":"Product","name":"Mira Dress",
     "offers":{"@type":"Offer","price":"99.00"}}}
]}
</script></head>
<body><div class="grid">
  <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$119</span></div>
  <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$99</span></div>
</div></body></html>
"""


def test_itemlist_grounds_every_record_with_pointers() -> None:
    boundaries, grounded = _ground(_ITEMLIST)
    assert len(boundaries) == 2
    assert grounded is not None
    assert len(grounded) == 2
    titles = {p.fields[0].value for _, p in grounded}
    assert titles == {"Aida Dress", "Mira Dress"}
    # Every field traces to a structured pointer — the grounding gate is mechanical.
    for _, product in grounded:
        assert all(f.pointer.startswith("jsonld:") for f in product.fields)
    # First record carries title, url, price, image.
    aida = next(p for _, p in grounded if p.fields[0].value == "Aida Dress")
    assert {f.fact_type for f in aida.fields} == {
        "product.title",
        "product.url",
        "offer.price",
        "asset.image_url",
    }


def test_partial_structured_coverage_does_not_hold_the_floor() -> None:
    # Two DOM records, but only one has a JSON-LD Product -> all-or-nothing fails.
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Aida Dress","url":"https://shop.test/p/aida-1001.html",
     "image":"x.jpg"}
    </script></head>
    <body><div class="grid">
      <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$1</span></div>
      <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$2</span></div>
    </div></body></html>
    """
    boundaries, grounded = _ground(html)
    assert len(boundaries) == 2
    assert grounded is None


def test_bare_product_array_grounds_by_url_identity() -> None:
    # No ItemList wrapper: a top-level array of Products, joined to DOM anchors
    # purely by casefolded host+path identity.
    html = """
    <html><head>
    <script type="application/ld+json">
    [{"@type":"Product","name":"Kettle","url":"https://shop.test/p/kettle-1"},
     {"@type":"Product","name":"Mixer","url":"https://shop.test/p/mixer-2"}]
    </script></head>
    <body><ul class="items">
      <li><a href="/p/kettle-1"><img src=x></a></li>
      <li><a href="/p/mixer-2"><img src=x></a></li>
    </ul></body></html>
    """
    _, grounded = _ground(html)
    assert grounded is not None
    assert {p.fields[0].value for _, p in grounded} == {"Kettle", "Mixer"}


def test_no_structured_source_falls_through() -> None:
    html = """
    <html><body><div class="grid">
      <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$1</span></div>
      <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$2</span></div>
    </div></body></html>
    """
    boundaries, grounded = _ground(html)
    assert len(boundaries) == 2  # discovery still finds boundaries...
    assert grounded is None  # ...but Tier 0 does not hold without structured data.
