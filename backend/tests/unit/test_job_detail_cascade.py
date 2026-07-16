"""Slice 4 / Task B1: job_detail routes through ``run_detail_cascade``.

The job-detail surface now shares the spec-driven detail cascade seam commerce
uses (structured JSON-LD JobPosting floor -> DOM floor). These tests prove the
structured floor publishes a JobPosting, the DOM floor fuses onto the single
structured subject, the cascade reads the rendered document, and no commerce
facts leak in (the ``allowed_facts`` filter is job-aware).
"""

from __future__ import annotations

import pytest

from app.extraction import extract
from app.extraction.cascade import run_detail_cascade
from app.extraction.contracts import (
    ArtifactRef,
    CaptureBundle,
    RequestContext,
    ExtractionRequest,
)
from app.extraction.replay import MemoryArtifactReader
from app.extraction.surfaces import COMMERCE_FACTS, JOB_FACTS, Surface, surface_spec
from app.core.shared.ids import content_sha256, stable_id

pytestmark = pytest.mark.unit


_JOB_POSTING_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Senior Platform Engineer",
  "identifier": "JOB-42",
  "url": "https://jobs.test/j/42",
  "hiringOrganization": {"@type": "Organization", "name": "Invoro"},
  "jobLocation": {
    "@type": "Place",
    "address": {"addressLocality": "Berlin", "addressCountry": "DE"}
  },
  "description": "Build the platform."
}
</script>
</head>
<body><main><h1>Senior Platform Engineer</h1></main></body>
</html>
"""
_JOB_URL = "https://jobs.test/j/42"


def _job_request(html: str, url: str = _JOB_URL) -> ExtractionRequest:
    from app.extraction.replay import fixture_request_from_inputs

    return fixture_request_from_inputs(Surface.JOB_DETAIL, html, url)


def _two_artifact_request(
    *, http_html: str, rendered_html: str, url: str
) -> ExtractionRequest:
    """A capture carrying BOTH an http_html and a rendered_html artifact.

    ``html_doc`` prefers the rendered artifact, so a field present only in the
    rendered HTML proves the cascade read the rendered document, not the raw
    HTTP body.
    """
    payloads = {"http": http_html, "rendered": rendered_html}
    refs = (
        ArtifactRef(
            artifact_id="http",
            artifact_type="http_html",
            content_sha256=content_sha256(http_html),
            storage_uri="memory://http",
            media_type="text/html",
        ),
        ArtifactRef(
            artifact_id="rendered",
            artifact_type="rendered_html",
            content_sha256=content_sha256(rendered_html),
            storage_uri="memory://rendered",
            media_type="text/html",
        ),
    )
    bundle = CaptureBundle(
        schema_version="capture.v1",
        bundle_id=stable_id("bundle", url, http_html[:40]),
        run_id=0,
        requested_url=url,
        final_url=url,
        request_context=RequestContext(context_id=stable_id("ctx", url)),
        artifacts=refs,
        acquisition_outcome="ok",
    )
    reader = MemoryArtifactReader(payloads)
    return ExtractionRequest(
        surface=Surface.JOB_DETAIL, capture=bundle, artifact_reader=reader
    )


def test_job_detail_structured_floor_publishes_jobposting() -> None:
    """The JSON-LD JobPosting floor publishes title/company/location, and every
    published evidence row carries the job_detail surface."""
    result = extract(_job_request(_JOB_POSTING_HTML))

    assert result.verdict == "success"
    record = result.records[0]
    assert record["title"] == "Senior Platform Engineer"
    assert record["company"] == "Invoro"
    assert record["location"] == "Berlin, DE"
    assert all(row.surface is Surface.JOB_DETAIL for row in result.evidence)


def test_job_detail_dom_floor_fuses_onto_structured_subject() -> None:
    """DOM rows rebind onto the single structured JobPosting subject id, so
    structured and DOM evidence share one subject inside the cascade."""
    request = _job_request(_JOB_POSTING_HTML)
    harvest = run_detail_cascade(
        request, request.artifact_reader, surface_spec(Surface.JOB_DETAIL)
    )

    collector_ids = {row.collector_id for row in harvest.evidence}
    assert {"job_jsonld", "job_dom"} <= collector_ids
    subject_ids = {row.subject_id for row in harvest.evidence if row.subject_id}
    assert len(subject_ids) == 1


def test_job_detail_reads_rendered_document() -> None:
    """A JobPosting present ONLY in the rendered artifact is extracted, proving
    the cascade reads the rendered-preferring document for JS-rendered pages."""
    shell = "<html><body><main></main></body></html>"
    result = extract(
        _two_artifact_request(
            http_html=shell,
            rendered_html=_JOB_POSTING_HTML,
            url=_JOB_URL,
        )
    )

    assert result.verdict == "success"
    assert result.records[0]["title"] == "Senior Platform Engineer"


def test_job_detail_cascade_emits_no_commerce_facts() -> None:
    """The job-detail cascade admits only job.* facts; no commerce fact type
    (e.g. product.*/offer.*) leaks through the ``allowed_facts`` filter."""
    request = _job_request(_JOB_POSTING_HTML)
    harvest = run_detail_cascade(
        request, request.artifact_reader, surface_spec(Surface.JOB_DETAIL)
    )

    fact_types = {row.fact_type for row in harvest.evidence}
    assert fact_types
    assert fact_types <= JOB_FACTS
    commerce_only = COMMERCE_FACTS - JOB_FACTS
    assert not (fact_types & commerce_only)
