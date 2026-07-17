"""Slice 4 / Task B2: URL-based disambiguation for job_detail roots.

A job-detail page can carry more than one ``JobPosting`` block (e.g. a
"similar jobs" widget). ``select_subject_targets`` used to trip
``AMBIGUOUS_JOB_ROOT`` whenever more than one root existed. It now disambiguates
by the requested URL first: the subject whose ``job.url`` evidence matches the
capture's requested/final URL is selected, and only a genuine no-match stays
ambiguous.
"""

from __future__ import annotations

import pytest

from app.extraction import extract
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


_PRIMARY_URL = "https://jobs.test/job?id=1042"
_SIMILAR_URL = "https://jobs.test/job?id=1099"


def _two_posting_html(*, primary_url: str, similar_url: str) -> str:
    return f"""
<html>
<head>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Senior Platform Engineer",
  "identifier": "JOB-42",
  "url": "{primary_url}",
  "hiringOrganization": {{"@type": "Organization", "name": "Invoro"}},
  "jobLocation": {{
    "@type": "Place",
    "address": {{"addressLocality": "Berlin", "addressCountry": "DE"}}
  }},
  "description": "Build the platform."
}}
</script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Staff Platform Engineer",
  "identifier": "JOB-99",
  "url": "{similar_url}",
  "hiringOrganization": {{"@type": "Organization", "name": "Invoro"}},
  "jobLocation": {{
    "@type": "Place",
    "address": {{"addressLocality": "Munich", "addressCountry": "DE"}}
  }},
  "description": "Similar role."
}}
</script>
</head>
<body><main><h1>Senior Platform Engineer</h1></main></body>
</html>
"""


def test_similar_jobs_widget_disambiguated_by_url() -> None:
    """Two JobPosting blocks, requested URL matches one -> resolved, and no
    AMBIGUOUS_JOB_ROOT finding is raised."""
    html = _two_posting_html(primary_url=_PRIMARY_URL, similar_url=_SIMILAR_URL)
    request = fixture_request_from_inputs(Surface.JOB_DETAIL, html, _PRIMARY_URL)

    result = extract(request)

    assert result.verdict == "success"
    assert result.records
    assert result.records[0]["title"] == "Senior Platform Engineer"
    assert not any(
        finding.rule_id == "AMBIGUOUS_JOB_ROOT" for finding in result.findings
    )


def test_job_detail_ambiguous_when_no_url_match() -> None:
    """When no posting's job.url matches the requested URL, selection stays
    ambiguous (honest failure), raising AMBIGUOUS_JOB_ROOT."""
    html = _two_posting_html(
        primary_url="https://jobs.test/job?id=1001",
        similar_url="https://jobs.test/job?id=1002",
    )
    request = fixture_request_from_inputs(
        Surface.JOB_DETAIL, html, "https://jobs.test/job?id=9999"
    )

    result = extract(request)

    assert result.verdict != "success"
    assert any(finding.rule_id == "AMBIGUOUS_JOB_ROOT" for finding in result.findings)


def test_query_string_ids_are_distinguished() -> None:
    """Finding 5: /job?id=123 vs /job?id=456 fold into distinct identity codes,
    so the requested query id selects the correct posting (not the richest)."""
    html = _two_posting_html(
        primary_url="https://jobs.test/job?id=123",
        similar_url="https://jobs.test/job?id=456",
    )
    # Request the SECOND posting's URL; query-aware codes must select it even
    # though host+path (``/job``) is identical for both postings.
    request = fixture_request_from_inputs(
        Surface.JOB_DETAIL, html, "https://jobs.test/job?id=456"
    )

    result = extract(request)

    assert result.verdict == "success"
    assert result.records
    assert result.records[0]["title"] == "Staff Platform Engineer"
    assert not any(
        finding.rule_id == "AMBIGUOUS_JOB_ROOT" for finding in result.findings
    )


def test_shared_query_id_stays_ambiguous() -> None:
    """Finding 5: two postings sharing the SAME query id share identity codes,
    so selection stays ambiguous rather than picking a fact-count winner."""
    shared = "https://jobs.test/job?id=123"
    html = _two_posting_html(primary_url=shared, similar_url=shared)
    request = fixture_request_from_inputs(Surface.JOB_DETAIL, html, shared)

    result = extract(request)

    assert result.verdict != "success"
    assert any(finding.rule_id == "AMBIGUOUS_JOB_ROOT" for finding in result.findings)
