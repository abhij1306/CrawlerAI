from __future__ import annotations

import pytest

from app.services.adapters.oracle_hcm import OracleHCMAdapter




@pytest.mark.asyncio
@pytest.mark.component
async def test_oracle_hcm_adapter_does_not_swallow_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OracleHCMAdapter()

    async def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("adapter bug")

    monkeypatch.setattr(adapter, "_request_json", raise_runtime_error)
    monkeypatch.setattr(adapter, "_extract_site_number", lambda *_args, **_kwargs: "42")

    with pytest.raises(RuntimeError, match="adapter bug"):
        await adapter.try_public_endpoint(
            "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
            "",
            "job_listing",
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_oracle_hcm_adapter_accepts_list_payloads_from_shared_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OracleHCMAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return [
            {
                "Id": 123,
                "Title": "Platform Engineer",
                "PostedDate": "2026-04-20",
                "PrimaryLocation": "Remote",
            }
        ]

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_extract_site_number", lambda *_args, **_kwargs: "42")
    monkeypatch.setattr(adapter, "_extract_site_lang", lambda *_args, **_kwargs: "en")
    monkeypatch.setattr(
        adapter, "_extract_site_name", lambda *_args, **_kwargs: "Example Co"
    )
    monkeypatch.setattr(
        adapter,
        "_normalize_requisition",
        lambda requisition, **_kwargs: {
            "title": str(requisition.get("Title") or ""),
            "job_id": str(requisition.get("Id") or ""),
            "url": "https://example.com/job/123",
        },
    )

    records = await adapter.try_public_endpoint(
        "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
        surface="job_listing",
    )

    assert records == [
        {
            "title": "Platform Engineer",
            "job_id": "123",
            "url": "https://example.com/job/123",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_oracle_hcm_adapter_uses_shared_request_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OracleHCMAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "items": [
                {
                    "requisitionList": [
                        {
                            "Id": 123,
                            "Title": "Platform Engineer",
                            "PostedDate": "2026-04-20",
                            "PrimaryLocation": "Remote",
                        }
                    ]
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_extract_site_number", lambda *_args, **_kwargs: "42")
    monkeypatch.setattr(adapter, "_extract_site_lang", lambda *_args, **_kwargs: "en")
    monkeypatch.setattr(
        adapter, "_extract_site_name", lambda *_args, **_kwargs: "Example Co"
    )
    monkeypatch.setattr(
        adapter,
        "_normalize_requisition",
        lambda requisition, **_kwargs: {
            "title": str(requisition.get("Title") or ""),
            "job_id": str(requisition.get("Id") or ""),
            "url": "https://example.com/job/123",
        },
    )

    records = await adapter.try_public_endpoint(
        "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
        surface="job_listing",
    )

    assert records == [
        {
            "title": "Platform Engineer",
            "job_id": "123",
            "url": "https://example.com/job/123",
        }
    ]
    assert calls and "recruitingCEJobRequisitions" in calls[0][0]


@pytest.mark.asyncio
@pytest.mark.component
async def test_oracle_hcm_target_job_id_returns_first_matching_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OracleHCMAdapter()

    async def _fake_request_json(url: str, **kwargs):
        del url, kwargs
        return {
            "items": [
                {
                    "requisitionList": [
                        {"Id": "R1", "Title": "Platform Engineer"},
                        {"Id": "R1", "Title": "Platform Engineer Remote"},
                    ]
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter, "_extract_site_number", lambda *_args, **_kwargs: "42")
    monkeypatch.setattr(adapter, "_extract_site_lang", lambda *_args, **_kwargs: "en")
    monkeypatch.setattr(
        adapter, "_extract_site_name", lambda *_args, **_kwargs: "Example Co"
    )
    monkeypatch.setattr(
        adapter,
        "_normalize_requisition",
        lambda requisition, **_kwargs: {
            "title": str(requisition.get("Title") or ""),
            "job_id": str(requisition.get("Id") or ""),
            "url": "https://example.com/job/R1",
        },
    )

    records = await adapter.try_public_endpoint(
        "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/R1",
        surface="job_detail",
    )

    assert [record["title"] for record in records] == ["Platform Engineer"]


@pytest.mark.component
def test_oracle_hcm_adapter_accepts_window_cx_config_without_semicolon() -> None:
    adapter = OracleHCMAdapter()
    html = """
    <script>
      window.CX_CONFIG = {"app": {"siteNumber": "CX_9", "siteLang": "en"}}
    </script>
    """

    assert adapter._extract_site_number("", html) == "CX_9"


@pytest.mark.component
def test_oracle_hcm_adapter_extracts_site_number_and_job_id_from_candidate_experience_paths() -> (
    None
):
    adapter = OracleHCMAdapter()
    url = "https://example.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/R89546/"

    assert adapter._extract_site_number(url, "") == "CX_1"
    assert adapter._extract_job_id_from_url(url) == "R89546"


@pytest.mark.asyncio
@pytest.mark.component
async def test_oracle_hcm_adapter_does_not_swallow_parser_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = OracleHCMAdapter()

    async def raise_value_error(*_args: object, **_kwargs: object) -> object:
        raise ValueError("parser bug")

    monkeypatch.setattr(adapter, "_request_json", raise_value_error)
    monkeypatch.setattr(adapter, "_extract_site_number", lambda *_args, **_kwargs: "42")

    with pytest.raises(ValueError, match="parser bug"):
        await adapter.try_public_endpoint(
            "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
            "",
            "job_listing",
        )
