from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.services.adapters.algolia_jobs import AlgoliaJobsAdapter
from app.services.adapters.firestore_jobs import FirestoreJobsAdapter




@pytest.mark.asyncio
@pytest.mark.component
async def test_algolia_jobs_adapter_extracts_public_job_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AlgoliaJobsAdapter()
    html = """
    <script>
      window.__NUXT__.config = {public:{
        algoliaApplicationId:"APPID",
        algoliaApiKey:"search-key",
        algoliaJobsIndexSuperRanked:"jobs_prod_super_ranked"
      }}
    </script>
    """
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return {
            "hits": [
                {
                    "objectID": "19640",
                    "title": "AI Policy Lead",
                    "company_name": "Talos Network",
                    "card_locations": ["Brussels, Belgium"],
                    "salary": "EUR 5,000/month",
                    "tags_role_type": ["Full-time"],
                    "description_short": "<p>Shape AI policy.</p>",
                    "url_external": "https://example.org/role",
                    "posted_at_relative": "1 day ago",
                }
            ]
        }

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    assert await adapter.can_handle("https://jobs.80000hours.org/jobs", html)
    records = await adapter.try_public_endpoint(
        "https://jobs.80000hours.org/jobs",
        html,
        "job_listing",
    )

    assert len(records) == 1
    assert records[0] == {
        "title": "AI Policy Lead",
        "url": "https://example.org/role",
        "apply_url": "https://example.org/role",
        "job_id": "19640",
        "company": "Talos Network",
        "location": "Brussels, Belgium",
        "salary": "EUR 5,000/month",
        "job_type": "Full-time",
        "posted_date": "1 day ago",
        "description": "Shape AI policy.",
    }
    assert (
        calls[0][0]
        == "https://APPID-dsn.algolia.net/1/indexes/jobs_prod_super_ranked/query"
    )
    assert calls[0][1]["headers"]["X-Algolia-Application-Id"] == "APPID"


@pytest.mark.asyncio
@pytest.mark.component
async def test_firestore_jobs_adapter_extracts_public_published_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FirestoreJobsAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_request_json(url: str, **kwargs):
        calls.append((url, kwargs))
        return [
            {
                "document": {
                    "name": "projects/djplatform/databases/(default)/documents/jobs/job123",
                    "fields": {
                        "title": {"stringValue": "Senior Python Developer"},
                        "slug": {"stringValue": "senior-python-developer"},
                        "publishedAt": {"timestampValue": "2026-05-16T00:51:48Z"},
                        "locationSlugs": {
                            "arrayValue": {"values": [{"stringValue": "PL"}]}
                        },
                        "type": {
                            "mapValue": {
                                "fields": {
                                    "name": {
                                        "mapValue": {
                                            "fields": {
                                                "display": {"stringValue": "Part Time"}
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "salary": {
                            "mapValue": {
                                "fields": {
                                    "public": {"booleanValue": True},
                                    "currency": {"stringValue": "USD"},
                                    "from": {"doubleValue": 24.63},
                                    "to": {"doubleValue": 35.58},
                                    "type": {"stringValue": "hourly"},
                                }
                            }
                        },
                        "company": {
                            "mapValue": {
                                "fields": {
                                    "username": {"stringValue": "monterail"},
                                    "name": {"stringValue": "Monterail"},
                                }
                            }
                        },
                    },
                }
            }
        ]

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)

    assert await adapter.can_handle("https://dynamitejobs.com/remote-jobs", "")
    records = await adapter.try_public_endpoint(
        "https://dynamitejobs.com/remote-jobs",
        "",
        "job_listing",
    )

    assert records == [
        {
            "title": "Senior Python Developer",
            "url": "https://dynamitejobs.com/company/monterail/remote-job/senior-python-developer",
            "job_id": "job123",
            "company": "Monterail",
            "location": "PL",
            "job_type": "Part Time",
            "posted_date": "2026-05-16T00:51:48Z",
            "salary": "USD 24.63 - 35.58 hourly",
        }
    ]
    assert urlparse(calls[0][0]).hostname == "firestore.googleapis.com"
    assert calls[0][1]["json_body"]["structuredQuery"]["where"]["fieldFilter"] == {
        "field": {"fieldPath": "status"},
        "op": "EQUAL",
        "value": {"stringValue": "published"},
    }

