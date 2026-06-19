from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.acquisition.contracts import (
    AcquisitionPlan,
    AcquisitionResult,
    AttemptResult,
    AttemptSpec,
)
from app.crawl.contracts import RunSummary, UrlResult
from app.extraction.contracts import CapabilityRequest
from app.persistence.contracts import (
    ArtifactManifest,
    ArtifactReference,
    AttemptArtifactSet,
    ExtractionArtifactSet,
)

pytestmark = pytest.mark.unit


def _attempt(attempt_id: str = "http-1") -> AttemptSpec:
    return AttemptSpec(
        attempt_id=attempt_id,
        transport="curl",
        timeout_seconds=3,
        reason="initial_http",
    )


def test_acquisition_plan_rejects_duplicate_attempt_ids() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="attempt_id"):
        AcquisitionPlan(
            plan_id="plan-1",
            attempts=(_attempt(), _attempt()),
            created_at=now,
            deadline=now + timedelta(seconds=10),
        )


def test_acquisition_result_requires_selected_attempt_to_exist() -> None:
    result = AttemptResult(
        attempt_id="http-1",
        outcome="success",
        final_url="https://shop.test/p/1",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError, match="selected_attempt_id"):
        AcquisitionResult(
            plan_id="plan-1",
            attempts=(result,),
            selected_attempt_id="missing",
            outcome="success",
        )


def test_capability_request_is_bounded_to_one_escalation() -> None:
    with pytest.raises(ValidationError, match="max_attempts"):
        CapabilityRequest(
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html",),
            max_attempts=2,
        )


def test_url_result_exposes_extraction_verdict_without_independent_field() -> None:
    result = UrlResult(
        run_id=7,
        requested_url="https://shop.test/p/1",
        final_url="https://shop.test/p/1",
        surface="ecommerce_detail",
        acquisition_outcome="success",
        extraction_verdict="partial",
        record_ids=(11,),
    )
    assert result.verdict == "partial"
    assert "verdict" not in result.model_fields_set


def test_manifest_requires_sha256_artifact_references() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        ArtifactManifest(
            run_id=7,
            url_result_id=9,
            bundle_id="bundle-1",
            attempts=(
                AttemptArtifactSet(
                    attempt_id="http-1",
                    artifacts=(
                        {
                            "name": "page.html",
                            "uri": "runs/7/pages/page.html",
                            "sha256": "bad",
                            "size_bytes": 12,
                        },
                    ),
                ),
            ),
            extraction=ExtractionArtifactSet(),
        )


def test_run_summary_only_aggregates_canonical_url_results() -> None:
    summary = RunSummary.from_results(
        (
            UrlResult(
                run_id=7,
                requested_url="https://shop.test/p/1",
                final_url="https://shop.test/p/1",
                surface="ecommerce_detail",
                acquisition_outcome="success",
                extraction_verdict="success",
                record_ids=(1,),
            ),
            UrlResult(
                run_id=7,
                requested_url="https://shop.test/p/2",
                final_url="https://shop.test/p/2",
                surface="ecommerce_detail",
                acquisition_outcome="blocked",
                extraction_verdict="blocked",
            ),
        )
    )
    assert summary.url_count == 2
    assert summary.record_count == 1
    assert summary.verdict_counts == {"blocked": 1, "success": 1}
