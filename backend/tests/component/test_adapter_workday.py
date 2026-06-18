from __future__ import annotations

import pytest

from app.services.adapters.workday import WorkdayAdapter




@pytest.mark.asyncio
@pytest.mark.component
async def test_workday_adapter_does_not_duplicate_localized_prefix_in_listing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Assembler",
                    "externalPath": "/en-US/External/job/US-WI/Assembler_REQ-1",
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert result.records[0]["url"] == (
        "https://example.wd5.myworkdayjobs.com/en-US/External/job/US-WI/Assembler_REQ-1"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_workday_adapter_extracts_listing_from_cxs_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Sports Medicine Territory Manager (Lexington, KY)",
                    "externalPath": "/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
                    "locationsText": "US - Lexington",
                    "postedOn": "Posted Yesterday",
                    "bulletFields": ["R89546"],
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    html = (
        '<a href="/en-US/External/job/US---Lexington/'
        'Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1">'
        "Sports Medicine Territory Manager (Lexington, KY)</a>"
    )

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/External",
        html,
        "job_listing",
    )

    assert (
        calls[0][0]
        == "https://smithnephew.wd5.myworkdayjobs.com/wday/cxs/smithnephew/External/jobs"
    )
    assert calls[0][1]["method"] == "POST"
    assert result.records == [
        {
            "title": "Sports Medicine Territory Manager (Lexington, KY)",
            "url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "apply_url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "location": "US - Lexington",
            "posted_date": "Posted Yesterday",
            "job_id": "R89546",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_workday_adapter_falls_back_to_html_when_detail_title_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "jobPostingInfo": {
                "title": "",
                "jobDescription": "",
            }
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
        "<html><body><h1>HTML fallback title</h1><p>HTML fallback description</p></body></html>",
        "job_detail",
    )

    assert result.records == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_workday_adapter_normalizes_listing_paths_without_leading_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Assembler",
                    "externalPath": "job/US-WI/Assembler_REQ-1",
                }
            ],
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert result.records[0]["url"] == (
        "https://example.wd5.myworkdayjobs.com/en-US/External/job/US-WI/Assembler_REQ-1"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_workday_adapter_extracts_detail_from_cxs_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    captured_urls: list[str] = []

    async def _fake_request_json(url: str, **kwargs):
        del kwargs
        captured_urls.append(url)
        return {
            "jobPostingInfo": {
                "title": "Sports Medicine Territory Manager (Lexington, KY)",
                "jobDescription": "<p>Lead the territory.</p><h2>Benefits</h2><p>Health and dental.</p>",
                "location": "US - Lexington",
                "postedOn": "Posted Yesterday",
                "timeType": "Full time",
                "jobReqId": "R89546",
                "externalUrl": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
                "country": "United States",
            },
            "hiringOrganization": {"name": "Smith+Nephew"},
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    result = await adapter.extract(
        "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
        "",
        "job_detail",
    )

    assert captured_urls == [
        "https://smithnephew.wd5.myworkdayjobs.com/wday/cxs/smithnephew/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1"
    ]
    assert result.records == [
        {
            "title": "Sports Medicine Territory Manager (Lexington, KY)",
            "url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "apply_url": "https://smithnephew.wd5.myworkdayjobs.com/en-US/External/job/US---Lexington/Sports-Medicine-Territory-Manager--Lexington--KY-_R89546-1",
            "location": "US - Lexington",
            "posted_date": "Posted Yesterday",
            "job_type": "Full time",
            "job_id": "R89546",
            "country": "United States",
            "company": "Smith+Nephew",
            "description": "Lead the territory. Benefits Health and dental.",
            "benefits": "Health and dental.",
        }
    ]

