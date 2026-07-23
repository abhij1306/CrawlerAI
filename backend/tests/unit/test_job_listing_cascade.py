"""Slice 2: job-listing cascade seam (structured -> network -> DOM).

Pins the deterministic, selector-free listing cascade for the job-listing
surface: it routes through the SAME ``run_listing_cascade`` as commerce, admits
records via the DOM floor with no model call, rejects hub/category tiles,
accepts off-host ATS apply links, and reads the rendered artifact set (not only
top-level ``html``) so JS-rendered boards are covered.
"""

from __future__ import annotations

import pytest

from app.core.config.extraction_recipes import (
    ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID,
    LISTING_HTML_ARTIFACT_IDS,
)
from app.acquisition.listing_cards import count_cards_from_html
from app.acquisition.browser_readiness import probe_browser_readiness
from app.extraction.adapters import _harvest_job_listing
from app.extraction.cascade import LISTING_FLOOR_ORDER, run_listing_cascade
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema

pytestmark = pytest.mark.unit

PAGE = "https://careers.acme.test/jobs"

# An ATS-backed board: each posting links off-site to a Greenhouse-style host.
_OFF_HOST_BOARD_HTML = """
<html><body><div class="grid">
  <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/101">Backend Engineer</a><span>Remote - US</span></div>
  <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/102">Frontend Engineer</a><span>New York</span></div>
  <div class="job"><a href="https://boards.greenhouse.io/acme/jobs/103">Data Scientist</a><span>Berlin</span></div>
</div></body></html>
"""

# A same-site board of real postings (ultipro-style detail paths).
_SAME_HOST_BOARD_HTML = """
<html><body><div class="grid">
  <div class="job"><a href="/careers/positions/101">Backend Engineer</a><span>Remote - US</span></div>
  <div class="job"><a href="/careers/positions/102">Frontend Engineer</a><span>New York</span></div>
  <div class="job"><a href="/careers/positions/103">Data Scientist</a><span>Berlin</span></div>
</div></body></html>
"""

# A grid of category/hub tiles — each links to a "-jobs" terminal category page,
# not an individual posting. These must NOT be admitted as records.
_HUB_TILE_HTML = """
<html><body><div class="grid">
  <div class="cat"><a href="/engineering-jobs">Engineering Jobs</a></div>
  <div class="cat"><a href="/design-jobs">Design Jobs</a></div>
  <div class="cat"><a href="/marketing-jobs">Marketing Jobs</a></div>
</div></body></html>
"""

# A JS shell whose body is empty; the real board only exists in the rendered
# fragment artifact (the ``ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID`` capture).
_JS_SHELL_HTML = "<html><body><div id='root'></div></body></html>"
_RENDERED_FRAGMENT = """
<div class="grid">
  <div class="job"><a href="/careers/positions/201">Platform Engineer</a><span>Remote - US</span></div>
  <div class="job"><a href="/careers/positions/202">Product Designer</a><span>Austin</span></div>
  <div class="job"><a href="/careers/positions/203">Site Reliability Engineer</a><span>London</span></div>
</div>
"""


def _run(
    html: str,
    *,
    page_url: str = PAGE,
    artifacts: dict | None = None,
    network_payloads: list[dict] | None = None,
):
    request = fixture_request_from_inputs(
        Surface.JOB_LISTING,
        html,
        page_url,
        max_records=10,
        artifacts=artifacts,
        network_payloads=network_payloads,
    )
    schema = listing_schema(Surface.JOB_LISTING)
    assert schema is not None
    return run_listing_cascade(request, request.artifact_reader, schema)


def _no_model(collectors: set[str]) -> None:
    assert not any("model" in cid or "llm" in cid for cid in collectors)


def test_dom_floor_yields_job_records_with_zero_model_calls() -> None:
    result = _run(_SAME_HOST_BOARD_HTML)
    assert result.evidence
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"listing_dom_floor"}
    titles = {row.value for row in result.evidence if row.fact_type == "job.title"}
    assert titles == {"Backend Engineer", "Frontend Engineer", "Data Scientist"}
    _no_model(collectors)


def test_cascade_reports_floors_in_structured_network_dom_order() -> None:
    result = _run(_SAME_HOST_BOARD_HTML)
    assert result.floor_order == ("structured", "network", "dom")
    assert LISTING_FLOOR_ORDER == ("structured", "network", "dom")
    reported = tuple(o.collector_id for o in result.collector_outcomes)
    assert reported == (
        "listing_structured_floor",
        "listing_network_floor",
        "listing_dom_floor",
    )
    by_id = {o.collector_id: o.outcome for o in result.collector_outcomes}
    # No structured/network source here, so the DOM floor is the winner.
    assert by_id["listing_structured_floor"] == "no_match"
    assert by_id["listing_network_floor"] == "no_match"
    assert by_id["listing_dom_floor"] == "produced_evidence"


def test_off_host_ats_apply_links_are_accepted() -> None:
    result = _run(_OFF_HOST_BOARD_HTML)
    urls = {row.value for row in result.evidence if row.fact_type == "job.url"}
    assert urls == {
        "https://boards.greenhouse.io/acme/jobs/101",
        "https://boards.greenhouse.io/acme/jobs/102",
        "https://boards.greenhouse.io/acme/jobs/103",
    }


def test_hub_and_category_tiles_are_rejected() -> None:
    result = _run(_HUB_TILE_HTML)
    # No individual postings: the category tiles never become records.
    titles = {row.value for row in result.evidence if row.fact_type == "job.title"}
    assert titles == set()
    assert result.evidence == ()


def test_job_listing_reads_rendered_artifact_set_not_only_html() -> None:
    # The top-level html is an empty JS shell; the board lives in the rendered
    # fragment artifact. The DOM floor must still discover the postings.
    result = _run(
        _JS_SHELL_HTML,
        artifacts={ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID: [_RENDERED_FRAGMENT]},
    )
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"listing_dom_floor"}
    titles = {row.value for row in result.evidence if row.fact_type == "job.title"}
    assert titles == {
        "Platform Engineer",
        "Product Designer",
        "Site Reliability Engineer",
    }
    _no_model(collectors)


@pytest.mark.asyncio
async def test_rendered_job_listing_count_readiness_and_extract_agree() -> None:
    assert ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID in LISTING_HTML_ARTIFACT_IDS
    admitted = count_cards_from_html(
        _RENDERED_FRAGMENT,
        page_url=PAGE,
        surface=Surface.JOB_LISTING.value,
    )
    page = type("Page", (), {"url": PAGE, "locator": lambda self, selector: self})()

    async def count() -> int:
        return 0

    page.count = count
    readiness = await probe_browser_readiness(
        page,
        url=PAGE,
        surface=Surface.JOB_LISTING.value,
        html=_RENDERED_FRAGMENT,
    )
    result = _run(
        _JS_SHELL_HTML,
        artifacts={ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID: [_RENDERED_FRAGMENT]},
    )
    extracted = len(
        {row.subject_id for row in result.evidence if row.fact_type == "job.title"}
    )

    assert readiness["is_ready"] is True
    assert readiness["listing_card_count"] == admitted == extracted == 3


def test_anchorless_onclick_cards_publish_recovered_url() -> None:
    # A JS board with no <a href>; each card's onclick names the detail URL.
    # The DOM floor must recover it and emit BOTH job.title and job.url so the
    # cards can actually publish (an anchor-less card without a url is dropped
    # downstream as incomplete).
    html = """
    <html><body><ul class="list">
      <li class="card" data-job-id="901" onclick="location.href='/careers/positions/901'"><h3>Backend Engineer</h3><p>Remote - US</p></li>
      <li class="card" data-job-id="902" onclick="location.href='/careers/positions/902'"><h3>Frontend Engineer</h3><p>New York</p></li>
      <li class="card" data-job-id="903" onclick="location.href='/careers/positions/903'"><h3>Data Scientist role</h3><p>Berlin</p></li>
    </ul></body></html>
    """
    result = _run(html)
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"listing_dom_floor"}
    urls = {row.value for row in result.evidence if row.fact_type == "job.url"}
    assert urls == {
        "https://careers.acme.test/careers/positions/901",
        "https://careers.acme.test/careers/positions/902",
        "https://careers.acme.test/careers/positions/903",
    }
    _no_model(collectors)


def test_department_tiles_without_navigation_are_rejected() -> None:
    # Department/category tiles carry only a generic id/data-testid and NO
    # navigation affordance. Without a recoverable detail URL they are not job
    # records: the DOM floor must produce no evidence (honest empty), not a
    # url-less title row that falsely reports produced_evidence.
    html = """
    <html><body><section class="departments">
      <div id="dept-eng" data-testid="dept"><h3>Engineering</h3><p>Many open roles</p></div>
      <div id="dept-design" data-testid="dept"><h3>Design</h3><p>Many open roles</p></div>
      <div id="dept-sales" data-testid="dept"><h3>Sales</h3><p>Many open roles</p></div>
    </section></body></html>
    """
    result = _run(html)
    assert result.evidence == ()


def test_off_host_singleton_grounds_via_structured_floor() -> None:
    # A one-posting page: JobPosting JSON-LD corroborates a single off-host
    # Lever anchor. The structured floor (allow_singleton) must ground it even
    # though the anchor points off-host, exercising the schema-driven seam.
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","title":"Staff Engineer",
     "url":"https://jobs.lever.co/acme/xyz-123",
     "hiringOrganization":{"@type":"Organization","name":"Acme"},
     "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Remote"}}}
    </script></head>
    <body><main><div class="job">
      <a href="https://jobs.lever.co/acme/xyz-123">Staff Engineer</a><span>Remote - EU</span>
    </div></main></body></html>
    """
    result = _run(html, page_url="https://acme.test/careers/staff-engineer")
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"listing_structured_floor"}
    urls = {row.value for row in result.evidence if row.fact_type == "job.url"}
    assert urls == {"https://jobs.lever.co/acme/xyz-123"}
    _no_model(collectors)


def test_network_only_off_host_ats_rows_extract() -> None:
    # A JS shell with no DOM board; the postings arrive only as a network JSON
    # array whose urls point directly at an off-host ATS. The network floor must
    # admit them because the job schema allows off-host records.
    network = [
        {
            "body": {
                "jobs": [
                    {
                        "title": "Backend Engineer",
                        "url": "https://boards.greenhouse.io/acme/jobs/101",
                        "location": "Remote",
                    },
                    {
                        "title": "Frontend Engineer",
                        "url": "https://boards.greenhouse.io/acme/jobs/102",
                        "location": "New York",
                    },
                ]
            }
        }
    ]
    result = _run(_JS_SHELL_HTML, network_payloads=network)
    collectors = {row.collector_id for row in result.evidence}
    assert collectors == {"network_listing_floor"}
    urls = {row.value for row in result.evidence if row.fact_type == "job.url"}
    assert urls == {
        "https://boards.greenhouse.io/acme/jobs/101",
        "https://boards.greenhouse.io/acme/jobs/102",
    }
    _no_model(collectors)


def _harvest(html: str, *, page_url: str = PAGE):
    request = fixture_request_from_inputs(
        Surface.JOB_LISTING, html, page_url, max_records=10
    )
    return _harvest_job_listing(request)


def test_job_listing_routes_through_the_cascade() -> None:
    harvest = _harvest(_SAME_HOST_BOARD_HTML)
    collectors = {row.collector_id for row in harvest.evidence}
    # The cascade DOM floor is the collector on this path.
    assert collectors == {"listing_dom_floor"}
    titles = {row.value for row in harvest.evidence if row.fact_type == "job.title"}
    assert titles == {"Backend Engineer", "Frontend Engineer", "Data Scientist"}
    # The cascade's per-floor diagnostics are carried through verbatim.
    reported = {o.collector_id for o in harvest.collector_outcomes}
    assert reported == {
        "listing_structured_floor",
        "listing_network_floor",
        "listing_dom_floor",
    }
