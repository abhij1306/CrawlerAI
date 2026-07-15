"""Slice 1: selector-free listing record-boundary discovery.

These tests pin the structural, site-independent contract of
``discover_listing_records`` — grid repetition detection, the homogeneity
tie-break between competing grids, structural-URL rejection, and the rule that
a singleton record is admissible only on the structured (``allow_singleton``)
path, never via DOM-only discovery.
"""

from __future__ import annotations

import pytest

from app.extraction.documents import HtmlDocument
from app.extraction.listing_records import discover_listing_records

pytestmark = pytest.mark.unit

PAGE = "https://shop.test/c/dresses/"


def _discover(html: str, *, allow_singleton: bool = False, page_url: str = PAGE):
    doc = HtmlDocument("t", html)
    return discover_listing_records(
        doc, page_url=page_url, allow_singleton=allow_singleton
    )


def test_repeated_grid_children_are_the_record_set() -> None:
    html = """
    <html><body><div class="grid">
      <div class="card"><a href="/p/aida-1001.html"><img src=x></a><span>$119</span></div>
      <div class="card"><a href="/p/mira-1002.html"><img src=x></a><span>$99</span></div>
      <div class="card"><a href="/p/nova-1003.html"><img src=x></a><span>$79</span></div>
    </div></body></html>
    """
    boundaries = _discover(html)
    assert len(boundaries) == 3
    assert [b.index for b in boundaries] == [0, 1, 2]
    assert {b.url for b in boundaries} == {
        "https://shop.test/p/aida-1001.html",
        "https://shop.test/p/mira-1002.html",
        "https://shop.test/p/nova-1003.html",
    }


def test_homogeneity_breaks_tie_toward_the_structural_grid() -> None:
    # Two grids each hold two product links. The homogeneous grid's children
    # share a structural signature (card > a > img + span); the mixed grid's
    # children differ in shape. The tie-break must pick the homogeneous grid.
    html = """
    <html><body>
      <aside class="mixed">
        <div><a href="/p/rail-1"><img src=x></a><span>$5</span></div>
        <section><h3><a href="/p/rail-2"><img src=x></a></h3><span>$6</span></section>
      </aside>
      <div class="grid">
        <div class="card"><a href="/p/aida-1001"><img src=x></a><span>$119</span></div>
        <div class="card"><a href="/p/mira-1002"><img src=x></a><span>$99</span></div>
      </div>
    </body></html>
    """
    boundaries = _discover(html)
    assert {b.url for b in boundaries} == {
        "https://shop.test/p/aida-1001",
        "https://shop.test/p/mira-1002",
    }


def test_structural_nav_urls_are_rejected() -> None:
    # The nav links are category/utility URLs (listing_url_is_structural) so
    # they never seed a record; only the two product cards survive.
    html = """
    <html><body>
      <nav>
        <a href="/c/dresses">Dresses</a>
        <a href="/c/shoes">Shoes</a>
        <a href="/cart">Cart</a>
      </nav>
      <div class="grid">
        <div class="card"><a href="/p/aida-1001"><img src=x></a><span>$119</span></div>
        <div class="card"><a href="/p/mira-1002"><img src=x></a><span>$99</span></div>
      </div>
    </body></html>
    """
    boundaries = _discover(html)
    assert {b.url for b in boundaries} == {
        "https://shop.test/p/aida-1001",
        "https://shop.test/p/mira-1002",
    }


def test_dom_only_singleton_is_not_a_record_without_structured_corroboration() -> None:
    # One lone content-rich product link. DOM-only discovery is repetition
    # gated, so it must return nothing unless allow_singleton is set.
    html = """
    <html><body><main>
      <div class="hero"><a href="/p/solo-9001"><img src=x></a><span>$149</span></div>
    </main></body></html>
    """
    assert _discover(html) == ()
    admitted = _discover(html, allow_singleton=True)
    assert len(admitted) == 1
    assert admitted[0].url == "https://shop.test/p/solo-9001"


def test_no_product_anchors_returns_empty() -> None:
    html = "<html><body><nav><a href='/c/all'>All</a></nav></body></html>"
    assert _discover(html) == ()
