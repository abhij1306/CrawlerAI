"""Progress patch shape: per-URL patches must stay small and fixed-size."""

from __future__ import annotations

import pytest

from app.crawl.pipeline.run_progress import BatchRunProgressState


def _state_with_results(total: int) -> BatchRunProgressState:
    state = BatchRunProgressState(total_urls=total, url_domain="example.com")
    for idx in range(total):
        state.record_url_result(
            idx=idx,
            records_count=1,
            verdict="success",
            url_metrics={"record_count": 1, "method": "http"},
        )
    return state


@pytest.mark.unit
def test_build_progress_patch_excludes_growing_per_url_payloads() -> None:
    state = _state_with_results(3)
    patch = state.build_progress_patch(
        current_url="https://example.com/c", current_url_index=3
    )
    assert "url_verdicts" not in patch
    assert "resolved_url_list" not in patch
    assert patch["completed_urls"] == 3
    assert patch["processed_urls"] == 3
    assert patch["record_count"] == 3
    assert patch["verdict_counts"] == {"success": 3}


@pytest.mark.unit
def test_build_progress_patch_size_does_not_grow_with_url_count() -> None:
    small = _state_with_results(2).build_progress_patch(
        current_url="https://example.com/b", current_url_index=2
    )
    large = _state_with_results(200).build_progress_patch(
        current_url="https://example.com/z", current_url_index=200
    )
    assert set(small) == set(large)


@pytest.mark.unit
def test_build_final_patch_keeps_verdicts_for_terminal_payload() -> None:
    state = _state_with_results(2)
    patch = state.build_final_patch("success")
    assert patch["url_verdicts"] == ["success", "success"]
    assert patch["extraction_verdict"] == "success"
    assert patch["completed_urls"] == 2
