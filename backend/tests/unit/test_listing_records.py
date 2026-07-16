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
from app.extraction.listing_records import (
    discover_listing_records,
    record_key_attributes_for_schema,
    record_signal_for_schema,
)
from app.extraction.surfaces import Surface, listing_schema

pytestmark = pytest.mark.unit

PAGE = "https://shop.test/c/dresses/"

# The job-listing schema supplies a non-visual record signal (text + detail
# link, no image/price) and record-local key attributes for anchor-less cards.
_JOB_SCHEMA = listing_schema(Surface.JOB_LISTING)
_JOB_SIGNAL = record_signal_for_schema(_JOB_SCHEMA)
_JOB_KEYS = record_key_attributes_for_schema(_JOB_SCHEMA)
JOB_PAGE = "https://careers.acme.test/jobs"


def _discover(html: str, *, allow_singleton: bool = False, page_url: str = PAGE):
    doc = HtmlDocument("t", html)
    return discover_listing_records(
        doc, page_url=page_url, allow_singleton=allow_singleton
    )


def _discover_jobs(
    html: str, *, allow_singleton: bool = False, page_url: str = JOB_PAGE
):
    doc = HtmlDocument("t", html)
    return discover_listing_records(
        doc,
        page_url=page_url,
        allow_singleton=allow_singleton,
        record_signal=_JOB_SIGNAL,
        off_host_allowed=_JOB_SCHEMA.off_host_records_allowed,
        record_key_attributes=_JOB_KEYS,
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


def test_off_host_ats_grid_is_accepted_for_jobs() -> None:
    # A career page whose postings link off-site to an ATS (Greenhouse-style)
    # host. Commerce would reject the foreign hosts; the job schema's
    # off-host-allowed record set admits the whole grid.
    html = """
    <html><body><div class="grid">
      <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/101">Backend Engineer</a><span>Remote - US</span></div>
      <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/102">Frontend Engineer</a><span>New York</span></div>
      <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/103">Data Scientist</a><span>Berlin</span></div>
    </div></body></html>
    """
    boundaries = _discover_jobs(html)
    assert {b.url for b in boundaries} == {
        "https://boards.greenhouse.io/acme/jobs/101",
        "https://boards.greenhouse.io/acme/jobs/102",
        "https://boards.greenhouse.io/acme/jobs/103",
    }


def test_off_host_ats_singleton_is_accepted_on_structured_path() -> None:
    # A one-posting board whose sole posting links to a foreign ATS (Lever). DOM
    # discovery stays repetition-gated (empty), but on the structured
    # (allow_singleton) path the off-host-allowed schema admits the lone record.
    html = """
    <html><body><main>
      <div class="job"><a href="https://jobs.lever.co/acme/xyz-123">Staff Engineer</a><span>Remote - EU</span></div>
    </main></body></html>
    """
    assert _discover_jobs(html) == ()
    admitted = _discover_jobs(html, allow_singleton=True)
    assert len(admitted) == 1
    assert admitted[0].url == "https://jobs.lever.co/acme/xyz-123"


def test_anchorless_onclick_cards_with_recoverable_url_are_accepted() -> None:
    # A JS board whose cards have no <a href> — navigation happens via an
    # onclick handler that names the detail URL. Each card also carries a stable
    # data-job-id token. The card is admitted and publishes the recovered URL.
    html = """
    <html><body><ul class="list">
      <li class="card" data-job-id="901" onclick="location.href='/careers/positions/901'"><h3>Backend Engineer</h3><p>Remote - US</p></li>
      <li class="card" data-job-id="902" onclick="location.href='/careers/positions/902'"><h3>Frontend Engineer</h3><p>New York</p></li>
      <li class="card" data-job-id="903" onclick="location.href='/careers/positions/903'"><h3>Data Scientist</h3><p>Berlin</p></li>
    </ul></body></html>
    """
    boundaries = _discover_jobs(html)
    assert len(boundaries) == 3
    assert [b.index for b in boundaries] == [0, 1, 2]
    # The detail URL is recovered from the navigation affordance.
    assert {b.url for b in boundaries} == {
        "https://careers.acme.test/careers/positions/901",
        "https://careers.acme.test/careers/positions/902",
        "https://careers.acme.test/careers/positions/903",
    }


def test_anchorless_cards_with_data_url_attribute_are_accepted() -> None:
    # Navigation affordance can also be a data-* URL payload rather than an
    # onclick handler; the recovered URL still anchors the record.
    html = """
    <html><body><ul class="list">
      <li class="card" data-job-id="901" data-href="/careers/positions/901"><h3>Backend Engineer</h3><p>Remote - US</p></li>
      <li class="card" data-job-id="902" data-href="/careers/positions/902"><h3>Frontend Engineer</h3><p>New York</p></li>
    </ul></body></html>
    """
    boundaries = _discover_jobs(html)
    assert {b.url for b in boundaries} == {
        "https://careers.acme.test/careers/positions/901",
        "https://careers.acme.test/careers/positions/902",
    }


def test_anchorless_id_only_tiles_without_navigation_are_rejected() -> None:
    # Department/category tiles carry only a generic id/data-testid with NO
    # navigation affordance (no onclick target, no data-* URL). A record without
    # a recoverable detail URL is not a posting — the grid is rejected.
    html = """
    <html><body><section class="departments">
      <div id="dept-eng" data-testid="dept"><h3>Engineering</h3><p>Many open roles</p></div>
      <div id="dept-design" data-testid="dept"><h3>Design</h3><p>Many open roles</p></div>
      <div id="dept-sales" data-testid="dept"><h3>Sales</h3><p>Many open roles</p></div>
    </section></body></html>
    """
    assert _discover_jobs(html) == ()


def test_nav_and_footer_menu_is_rejected_for_jobs() -> None:
    # A header/footer menu of career links is not a record set: nav/footer
    # anchors are excluded and there is no repeated posting grid.
    html = """
    <html><body>
      <nav class="menu">
        <a href="/careers">Careers</a>
        <a href="/about">About</a>
        <a href="/jobs">Jobs</a>
      </nav>
      <footer><a href="/apply">Apply</a></footer>
    </body></html>
    """
    assert _discover_jobs(html) == ()
