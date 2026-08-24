from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.acquisition.contracts import (
    AcquisitionPlan,
    AcquisitionResult,
    AttemptResult,
    AttemptSpec,
)
from app.crawl.contracts import RunSummary, UrlResult
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.extraction.contracts import CapabilityRequest, FailureTaxonomy
from app.persistence.contracts import ArtifactReference

pytestmark = pytest.mark.unit
_VALIDATION_CONFIG = Path(__file__).resolve().parents[3] / "scripts" / "validation.json"


def _attempt(attempt_id: str = "http-1") -> AttemptSpec:
    return AttemptSpec(
        attempt_id=attempt_id,
        transport="curl",
        timeout_seconds=3,
        reason="initial_http",
    )


def test_validation_tooling_changes_use_targeted_contract_tests() -> None:
    config = json.loads(_VALIDATION_CONFIG.read_text(encoding="utf-8"))
    tooling_paths = {"scripts/check.ps1", "scripts/validation.json"}
    assert tooling_paths.isdisjoint(config["globalTriggers"])
    tooling_rule = next(
        rule for rule in config["rules"] if set(rule["sources"]) == tooling_paths
    )
    assert tooling_rule["backendTests"] == [
        "tests/unit/test_final_architecture_contracts.py"
    ]
    assert tooling_rule["frontendTests"] == ["lib/check-crawl-architecture.test.ts"]


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


def test_capability_request_is_bounded_to_configured_cap() -> None:
    # A multi-rung ladder is allowed up to the configured cap (default 2:
    # one initial attempt plus one escalation), but no further.
    accepted = CapabilityRequest(
        reason="explicit_variants_missing",
        required_artifacts=("rendered_html",),
        max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP,
    )
    assert accepted.max_attempts == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    with pytest.raises(ValidationError, match="max_attempts"):
        CapabilityRequest(
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html",),
            max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP + 1,
        )


def test_failure_taxonomy_has_no_unemitted_template_or_recipe_drift_codes() -> None:
    assert "template_mismatch" not in FailureTaxonomy.__args__
    assert "recipe_drift" not in FailureTaxonomy.__args__


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


def test_artifact_reference_requires_sha256() -> None:
    with pytest.raises(ValidationError, match="sha256"):
        ArtifactReference(
            name="page.html",
            uri="runs/7/results/9/page.html",
            sha256="bad",
            size_bytes=12,
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
