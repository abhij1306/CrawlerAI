from __future__ import annotations

import pytest

from app.services.adapters.jibe import JibeAdapter




@pytest.mark.asyncio
@pytest.mark.component
async def test_jibe_adapter_matches_detail_records_by_slug_like_job_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = JibeAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "jobs": [
                {
                    "data": {
                        "title": "Telemetry Nurse",
                        "req_id": "REQ-1",
                        "apply_url": "/jobs/req-1",
                    }
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    records = await adapter.try_public_endpoint(
        "https://jobs.example.com/jobs/req-1",
        surface="job_detail",
    )

    assert len(records) == 1
    assert records[0]["job_id"] == "REQ-1"


@pytest.mark.component
def test_jibe_extract_search_config_rejects_non_mapping_json() -> None:
    adapter = JibeAdapter()

    assert (
        adapter._extract_search_config("<script>window.searchConfig = [];</script>")
        == {}
    )


@pytest.mark.component
def test_jibe_normalize_query_value_preserves_falsy_scalars() -> None:
    adapter = JibeAdapter()

    assert adapter._normalize_query_value(0) == "0"
    assert adapter._normalize_query_value(False) == "False"


@pytest.mark.asyncio
@pytest.mark.component
async def test_jibe_adapter_uses_shared_request_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = JibeAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "jobs": [
                {
                    "data": {
                        "title": "Telemetry Nurse",
                        "req_id": "REQ-1",
                        "apply_url": "/jobs/req-1",
                    }
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    records = await adapter.try_public_endpoint(
        "https://jobs.example.com/search?location=remote",
        surface="job_listing",
    )

    assert len(records) == 1
    assert calls
    assert calls[0][0].startswith("https://jobs.example.com/api/jobs?")


@pytest.mark.component
def test_jibe_normalize_job_preserves_job_id_in_fallback_url() -> None:
    adapter = JibeAdapter()

    record = adapter._normalize_job(
        {"data": {"title": "Telemetry Nurse", "req_id": "REQ 1/2"}},
        base_url="https://jobs.example.com",
    )

    assert record is not None
    assert record["url"] == "https://jobs.example.com/jobs/REQ 1/2"

