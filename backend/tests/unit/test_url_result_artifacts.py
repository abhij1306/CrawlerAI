from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.extraction.contracts import ExtractionResult
from app.extraction.surfaces import Surface
from app.persistence.url_result_artifacts import publish_url_result_artifacts

pytestmark = pytest.mark.unit


def test_url_result_writes_exactly_three_coordinated_files(tmp_path: Path) -> None:
    acquisition = SimpleNamespace(
        final_url="https://jobs.test/search",
        html="<html><body>No open positions</body></html>",
        method="browser",
        status_code=200,
        blocked=False,
        platform_family=None,
        browser_diagnostics={
            "listing_discovery": {
                "is_ready": True,
                "ready_empty": True,
                "readiness_terminal_state": "ready_empty",
                "listing_card_diagnostics": {"card_count": 0},
            }
        },
        acquisition_diagnostics={},
        network_payloads=[],
    )
    extraction = ExtractionResult(
        surface=Surface.JOB_LISTING,
        bundle_id="bundle",
        records=(),
        verdict="empty",
    )

    published = publish_url_result_artifacts(
        run_id=1,
        url_result_id=2,
        acquisition_result=acquisition,
        extraction_result=extraction,
        record_count=0,
        verdict="listing_detection_failed",
        root_dir=tmp_path,
    )

    root = tmp_path / published.result_root
    assert sorted(path.name for path in root.iterdir()) == [
        "diagnose.json",
        "page.html",
        "record.json",
    ]
    diagnosis = json.loads((root / "diagnose.json").read_text(encoding="utf-8"))
    assert diagnosis["schema_version"] == "diagnose.v3"
    assert diagnosis["discovery"]["readiness"]["terminal_state"] == "ready_empty"
    assert diagnosis["discovery"]["listing_verdict"] == "listing_detection_failed"
    assert diagnosis["discovery"]["record_count"] == 0
