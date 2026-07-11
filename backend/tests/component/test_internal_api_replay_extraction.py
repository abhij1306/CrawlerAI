from __future__ import annotations

import pytest

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.crawl.pipeline.record_extraction_stage import (
    extract_records_for_acquisition_result,
)


@pytest.mark.component
def test_detail_extracts_from_empty_html_internal_api_replay_bundle() -> None:
    page_url = "https://example.com/products/replay-widget"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=1,
            url=page_url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=page_url,
        html="",
        method="api_replay",
        status_code=200,
        content_type="application/json",
        blocked=False,
        network_payloads=[
            {
                "url": "https://example.com/api/products/replay-widget.json",
                "method": "GET",
                "body": {
                    "product": {
                        "title": "Replay Widget",
                        "price": "19.99",
                        "currency": "USD",
                        "sku": "RW-100",
                        "url": page_url,
                    }
                },
            }
        ],
    )

    result = extract_records_for_acquisition_result(
        acquisition,
        "ecommerce_detail",
        max_records=1,
        requested_page_url=page_url,
        requested_fields=["title", "price"],
    )

    assert result.records
    assert result.records[0].title == "Replay Widget"
    assert result.records[0]._field_sources["title"] == ["network"]
    assert "insufficient_input_bundle" not in result.diagnostics.failure_codes


@pytest.mark.component
def test_job_listing_extracts_from_empty_html_internal_api_replay_bundle() -> None:
    page_url = "https://example.com/jobs?page=1"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=1,
            url=page_url,
            plan=AcquisitionIntent(surface="job_listing"),
        ),
        final_url=page_url,
        html="",
        method="api_replay",
        status_code=200,
        content_type="application/json",
        blocked=False,
        network_payloads=[
            {
                "body": {
                    "pageUrl": page_url,
                    "jobs": [
                        {
                            "title": "Software Engineer",
                            "url": "https://example.com/jobs/software-engineer",
                            "location": "Remote",
                            "company": "Example Co",
                        },
                        {
                            "title": "Data Engineer",
                            "url": "https://example.com/jobs/data-engineer",
                            "location": "Remote",
                            "company": "Example Co",
                        },
                    ],
                }
            }
        ],
    )

    result = extract_records_for_acquisition_result(
        acquisition,
        "job_listing",
        max_records=10,
        requested_page_url=page_url,
    )

    assert result.verdict == "success"
    assert {record.title for record in result.records} == {
        "Software Engineer",
        "Data Engineer",
    }
