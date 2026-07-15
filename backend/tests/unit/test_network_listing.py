"""Slice 1: network-JSON repeated-array listing floor.

Pins the site-agnostic contract of ``collect_network_listing``: it materializes
the strongest repeated JSON array (>= 2 members) whose members each carry the
schema's title and a same-host detail URL, and grounds bare response IDs to
page-local detail anchors when the array has no direct URL field.
"""

from __future__ import annotations

import pytest

from app.extraction.network_listing import collect_network_listing
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit

PAGE = "https://shop.test/c/kitchen"


def _collect(html: str, network_payloads, *, page_url: str = PAGE):
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        html,
        page_url,
        max_records=10,
        network_payloads=list(network_payloads),
    )
    return collect_network_listing(
        request.capture, request.artifact_reader, surface=Surface.ECOMMERCE_LISTING
    )


def test_repeated_array_materializes_same_host_records() -> None:
    payload = {
        "body": {
            "results": [
                {"name": "Kettle", "url": "https://shop.test/p/kettle-1", "price": "29"},
                {"name": "Mixer", "url": "https://shop.test/p/mixer-2", "price": "59"},
            ]
        }
    }
    rows = _collect("<html><body></body></html>", (payload,))
    assert rows
    subjects = {row.subject_id for row in rows}
    assert len(subjects) == 2
    titles = {row.value for row in rows if row.fact_type == "product.title"}
    assert titles == {"Kettle", "Mixer"}
    urls = {row.value for row in rows if row.fact_type == "product.url"}
    assert urls == {
        "https://shop.test/p/kettle-1",
        "https://shop.test/p/mixer-2",
    }


def test_singleton_array_is_rejected() -> None:
    payload = {
        "body": {
            "results": [
                {"name": "Kettle", "url": "https://shop.test/p/kettle-1"},
            ]
        }
    }
    assert _collect("<html><body></body></html>", (payload,)) == []


def test_off_host_url_row_drops_out() -> None:
    # The second row's URL is off-host; without a same-host URL it has no url
    # fact, so the array fails the "every member has title + url" gate.
    payload = {
        "body": {
            "items": [
                {"name": "Kettle", "url": "https://shop.test/p/kettle-1"},
                {"name": "Mixer", "url": "https://other.test/p/mixer-2"},
            ]
        }
    }
    assert _collect("<html><body></body></html>", (payload,)) == []


def test_id_grounds_to_detail_anchor_url() -> None:
    # Rows carry only opaque ids; the same-host detail anchors on the page let
    # the floor ground each id to a real detail URL without site rules. Uses the
    # JOB_LISTING lens because id->url grounding is driven by the schema's
    # ``network_identity_keys`` (empty for commerce, populated for jobs); the
    # network floor module itself is schema-agnostic.
    html = """
    <html><body>
      <a href="/jobs/backend?jobId=req-101">Backend Engineer</a>
      <a href="/jobs/data?jobId=req-102">Data Engineer</a>
    </body></html>
    """
    payload = {
        "body": {
            "jobs": [
                {"title": "Backend Engineer", "jobId": "req-101"},
                {"title": "Data Engineer", "jobId": "req-102"},
            ]
        }
    }
    request = fixture_request_from_inputs(
        Surface.JOB_LISTING,
        html,
        "https://jobs.test/careers",
        max_records=10,
        network_payloads=[payload],
    )
    rows = collect_network_listing(
        request.capture, request.artifact_reader, surface=Surface.JOB_LISTING
    )
    assert rows
    urls = {row.value for row in rows if row.fact_type == "job.url"}
    assert urls == {
        "https://jobs.test/jobs/backend?jobId=req-101",
        "https://jobs.test/jobs/data?jobId=req-102",
    }
