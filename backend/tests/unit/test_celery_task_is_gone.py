"""celery_task_is_gone: PENDING (queued) tasks get the longer pending window.

PENDING covers both lost/expired task records and tasks legitimately waiting
in the broker queue. A queued job that is merely stale past the normal orphan
window (worker backlog) must not be failed; only staleness past the longer
pending window may recover it.
"""

from __future__ import annotations

import pytest

from app.core.celery_app import celery_task_is_gone
from app.core.config.runtime_settings import CELERY_TASK_ID_KEY

TASK_ID = "task-123"
SUMMARY = {CELERY_TASK_ID_KEY: TASK_ID}


def _state(value: str | None):
    return lambda _task_id: value


@pytest.mark.unit
def test_pending_queued_task_survives_normal_orphan_window() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=True,
            pending_stale=False,
            task_state=_state("PENDING"),
        )
        is False
    )


@pytest.mark.unit
def test_pending_task_beyond_pending_window_is_gone() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=True,
            pending_stale=True,
            task_state=_state("PENDING"),
        )
        is True
    )


@pytest.mark.unit
def test_pending_without_pending_window_falls_back_to_stale() -> None:
    # Back-compat for callers that do not pass pending_stale.
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=True,
            task_state=_state("PENDING"),
        )
        is True
    )
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=False,
            pending_stale=True,
            task_state=_state("PENDING"),
        )
        is True
    )


@pytest.mark.unit
def test_started_task_is_never_gone() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=True,
            pending_stale=True,
            task_state=_state("STARTED"),
        )
        is False
    )


@pytest.mark.unit
def test_finished_task_is_gone_regardless_of_staleness() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=False,
            pending_stale=False,
            task_state=_state("SUCCESS"),
        )
        is True
    )


@pytest.mark.unit
def test_unavailable_backend_stays_conservative() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=None,
            stale=True,
            pending_stale=True,
            task_state=_state(None),
        )
        is False
    )


@pytest.mark.unit
def test_missing_task_id_uses_normal_staleness() -> None:
    assert celery_task_is_gone({}, exclude_task_id=None, stale=True) is True
    assert celery_task_is_gone({}, exclude_task_id=None, stale=False) is False


@pytest.mark.unit
def test_excluded_task_id_is_never_gone() -> None:
    assert (
        celery_task_is_gone(
            SUMMARY,
            exclude_task_id=TASK_ID,
            stale=True,
            pending_stale=True,
            task_state=_state("SUCCESS"),
        )
        is False
    )
