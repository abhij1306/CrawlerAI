from __future__ import annotations

import pytest

from app.services.adapters.saashr import SaaSHRAdapter
from app.services.adapters.ultipro import UltiProAdapter




@pytest.mark.asyncio
@pytest.mark.component
async def test_saashr_detail_mode_filters_to_requested_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SaaSHRAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "job_requisitions": [
                {
                    "id": 587687242,
                    "job_title": "Behavioral Health Technician",
                    "job_description": "Full description",
                    "location": {"city": "Yankton", "state": "SD"},
                },
                {
                    "id": 111,
                    "job_title": "Should Not Match",
                    "job_description": "Ignore me",
                    "location": {"city": "Sioux Falls", "state": "SD"},
                },
            ]
        }

    async def _fake_fetch_company_name(**kwargs):
        del kwargs
        return "Lewis & Clark Behavioral Health Services"

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_fetch_company_name", _fake_fetch_company_name)

    records = await adapter.try_public_endpoint(
        "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
        surface="job_detail",
    )

    assert records == [
        {
            "title": "Behavioral Health Technician",
            "job_id": "587687242",
            "url": "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
            "apply_url": "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087&ShowJob=587687242",
            "location": "Yankton, SD",
            "company": "Lewis & Clark Behavioral Health Services",
            "description": "Full description",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_saashr_adapter_handles_embedded_iframe_boards() -> None:
    html = """
    <html>
      <body>
        <iframe src="https://secure7.saashr.com/ta/6208610.careers?CareersSearch&ein_id=118959061&career_portal_id=6062087&InFrameset=1&HostedBy=lcbhs.net"></iframe>
      </body>
    </html>
    """

    assert await SaaSHRAdapter().can_handle("https://lcbhs.net/careers/", html)


@pytest.mark.asyncio
@pytest.mark.component
async def test_saashr_fetches_company_name_once_even_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SaaSHRAdapter()
    calls = {"company": 0}

    async def _fake_request_json(url: str, **kwargs):
        del kwargs
        if "job-requisitions" in url:
            return {
                "job_requisitions": [
                    {
                        "id": 1,
                        "job_title": "Behavioral Health Technician",
                    }
                ]
            }
        return {}

    async def _fake_fetch_company_name(**kwargs):
        del kwargs
        calls["company"] += 1
        return ""

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_fetch_company_name", _fake_fetch_company_name)

    records = await adapter.try_public_endpoint(
        "https://secure7.saashr.com/ta/6208610.careers?ein_id=118959061&career_portal_id=6062087",
        surface="job_listing",
    )

    assert len(records) == 1
    assert calls["company"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_ultipro_adapter_extracts_listing_from_jobboard_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = UltiProAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "opportunities": [
                {
                    "Id": "opp-1",
                    "Title": "Assembler",
                    "LocationName": "Grafton, WI",
                    "PostedDate": "2026-04-10",
                    "RequisitionNumber": "REQ-100",
                    "JobCategoryName": "Manufacturing",
                    "PostingId": "post-1",
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc",
        "",
        "job_listing",
    )

    assert calls[0][0] == (
        "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/"
        "1e739e24-c237-44f3-9f7a-310b0cec4162/JobBoardView/LoadSearchResults"
    )
    assert calls[0][1]["method"] == "POST"
    assert (
        calls[0][1]["json_body"]["opportunitySearch"]["OrderBy"][0]["Value"]
        == "postedDateDesc"
    )
    assert result.records == [
        {
            "title": "Assembler",
            "job_id": "opp-1",
            "url": "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/OpportunityDetail?opportunityId=opp-1&postingId=post-1",
            "apply_url": "https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/OpportunityDetail?opportunityId=opp-1&postingId=post-1",
            "location": "Grafton, WI",
            "posted_date": "2026-04-10",
            "requisition_id": "REQ-100",
            "category": "Manufacturing",
        }
    ]

