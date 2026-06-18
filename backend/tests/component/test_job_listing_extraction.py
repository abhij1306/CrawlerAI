from __future__ import annotations

import pytest

from app.services.extract.listing_candidate_ranking import (
    job_listing_title_is_hub,
    job_listing_url_is_hub,
    job_listing_url_looks_like_posting,
)
from app.services.extract.detail.identity.core import listing_url_is_structural
from app.services.extract.listing_visual import visual_listing_records
from app.services.listing_extractor import (
    extract_listing_records,
)
from app.services.shared.text_coerce import is_title_noise




@pytest.mark.component
def test_extract_listing_records_preserves_job_cards_inside_filtered_container() -> (
    None
):
    html = """
    <html>
      <body>
        <div class="cmplz-cookiebanner">
          <a href="#">Manage options</a>
        </div>
        <div class="filtered-jobs">
          <div class="pp-content-post pp-content-grid-post job_listing">
            <a class="atlas_js_job_title" href="https://atlasmedstaff.com/job/1475832-rn-telemetry-prescott-arizona/">
              RN: Telemetry
            </a>
            <p>Prescott, Arizona</p>
            <p>$1,886/wk est</p>
          </div>
        </div>
      </body>
    </html>
    """

    records = extract_listing_records(
        html,
        "https://atlasmedstaff.com/job-search/",
        "job_listing",
        max_records=5,
    )

    assert records == [
        {
            "source_url": "https://atlasmedstaff.com/job-search/",
            "_source": "dom_listing",
            "title": "RN: Telemetry",
            "url": "https://atlasmedstaff.com/job/1475832-rn-telemetry-prescott-arizona/",
            "salary": "$1,886",
        }
    ]


@pytest.mark.component
def test_job_listing_url_looks_like_posting_uses_segment_tokenization_for_non_listing_hubs() -> (
    None
):
    assert not job_listing_url_looks_like_posting(
        "https://jobs.example.com/jobs/search-results/role-12345-senior-engineer"
    )


@pytest.mark.component
def test_job_listing_filters_remote_category_hub_links() -> None:
    page_url = "https://euremotejobs.com/"
    html = """
    <html>
      <body>
        <footer>
          <a href="https://euremotejobs.com/jobs/remote-marketing-jobs/">Remote Marketing Jobs</a>
          <a href="https://euremotejobs.com/jobs/remote-sales-jobs/">Remote Sales Jobs</a>
        </footer>
      </body>
    </html>
    """

    assert job_listing_title_is_hub("Remote Marketing Jobs")
    assert job_listing_url_is_hub(
        "https://euremotejobs.com/jobs/remote-marketing-jobs/"
    )
    assert extract_listing_records(html, page_url, "job_listing", max_records=10) == []


@pytest.mark.component
def test_job_listing_extracts_anchor_wrapped_job_cards() -> None:
    html = """
    <html>
      <body>
        <a href="https://euremotejobs.com/job/fraud-data-analyst/" class="job-card-link">
          <div class="job-card">
            <div class="job-logo"><img class="company_logo" alt="Patrianna"></div>
            <div class="job-details">
              <h2 class="job-title">Fraud Data Analyst</h2>
              <div class="company-name">Patrianna</div>
              <div class="job-meta">
                <div class="meta-item meta-location">EMEA</div>
                <div class="meta-item meta-type">Full Time</div>
              </div>
            </div>
            <div class="job-time">Posted 2 days ago</div>
          </div>
        </a>
      </body>
    </html>
    """

    records = extract_listing_records(
        html,
        "https://euremotejobs.com/",
        "job_listing",
        max_records=10,
    )

    assert records == [
        {
            "source_url": "https://euremotejobs.com/",
            "_source": "dom_listing",
            "title": "Fraud Data Analyst",
            "url": "https://euremotejobs.com/job/fraud-data-analyst/",
            "company": "Patrianna",
            "location": "EMEA",
            "job_type": "Full Time",
            "posted_date": "Posted 2 days ago",
        }
    ]


@pytest.mark.component
def test_visual_job_listing_rejects_unbound_neighbor_title() -> None:
    records = visual_listing_records(
        [
            {
                "tag": "a",
                "text": "Read more",
                "href": "https://dynamitejobs.com/company/movebuddhacom/remote-job/senior-wordpress-developer-2",
                "x": 40,
                "y": 100,
                "width": 120,
                "height": 20,
                "score": 16,
            },
            {
                "tag": "h3",
                "text": "Full-Time AI-Powered Video Editor",
                "x": 42,
                "y": 150,
                "width": 260,
                "height": 24,
                "score": 8,
            },
        ],
        page_url="https://dynamitejobs.com/remote-jobs",
        surface="job_listing",
        max_records=10,
        title_is_noise=is_title_noise,
        url_is_structural=listing_url_is_structural,
    )

    assert records == []

