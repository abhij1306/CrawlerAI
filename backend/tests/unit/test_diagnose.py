from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.extraction.contracts import ExtractionResult
from app.extraction.surfaces import Surface
from app.observability.diagnose import build_diagnosis

pytestmark = pytest.mark.unit


def test_diagnose_v3_explains_listing_discovery_without_raw_payloads() -> None:
    acquisition = SimpleNamespace(
        final_url="https://jobs.test/search",
        method="browser",
        status_code=200,
        blocked=False,
        platform_family=None,
        browser_diagnostics={
            "browser_outcome": "usable_content",
            "network_payload_count": 2,
            "readiness_probes": [{}, {}],
            "listing_discovery": {
                "stage": "after_generic_readiness",
                "is_ready": True,
                "ready_empty": False,
                "readiness_terminal_state": "ready",
                "listing_card_diagnostics": {
                    "card_count": 2,
                    "admitted_count": 2,
                    "rejected_count": 3,
                    "rejection_reasons": {"missing_identity": 3},
                    "rejection_samples": [
                        {"reason": "missing_identity", "selector": "article"}
                    ],
                },
            },
        },
        acquisition_diagnostics={
            "escalation": {
                "rung": 2,
                "attempt": 2,
                "max_attempts": 2,
                "capability_requests": [
                    {
                        "rung": 2,
                        "attempt": 2,
                        "max_attempts": 2,
                        "reason": "network_floor_missing",
                        "required_artifacts": ["network_payloads"],
                        "capture_network": "all_small_json",
                    }
                ],
            }
        },
        network_payloads=[
            {
                "url": "https://jobs.test/api/jobs?token=secret",
                "body": {"email": "private@example.test", "jobs": [1]},
                "endpoint_type": "job_api",
                "status": 200,
                "content_type": "application/json",
            },
            {"body": [1, 2], "endpoint_type": "graphql", "status": 200},
        ],
    )
    extraction = ExtractionResult(
        surface=Surface.JOB_LISTING,
        bundle_id="bundle",
        records=(),
        verdict="success",
    )

    diagnosis = build_diagnosis(
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=2,
    )

    assert diagnosis["schema_version"] == "diagnose.v3"
    discovery = diagnosis["discovery"]
    assert discovery["listing_verdict"] == "success"
    assert discovery["record_count"] == discovery["card_count"] == 2
    assert discovery["admitted_count"] == 2
    assert discovery["rejected_count"] == 3
    assert discovery["readiness"]["terminal_state"] == "ready"
    assert discovery["escalation"]["rung"] == 2
    assert discovery["network"]["capture_count"] == 2
    assert discovery["network"]["payload_count"] == 2
    serialized = str(discovery)
    assert "private@example.test" not in serialized
    assert "token=secret" not in serialized
