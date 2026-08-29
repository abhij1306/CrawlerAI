from __future__ import annotations

from datetime import UTC, datetime

from app.models.crawl_domain import (
    ACTIVE_STATUSES,
    CONTROL_REQUEST_KEY,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    TERMINAL_STATUSES,
    normalize_status,
    transition_status,
)

__all__ = [
    "ACTIVE_STATUSES",
    "CONTROL_REQUEST_KEY",
    "CONTROL_REQUEST_KILL",
    "CONTROL_REQUEST_PAUSE",
    "TERMINAL_STATUSES",
    "CrawlStatus",
    "get_control_request",
    "normalize_status",
    "set_control_request",
    "transition_status",
    "update_run_status",
]


def update_run_status(run, target: str | CrawlStatus) -> CrawlStatus:
    """Update run status and set completion time on terminal transitions."""
    previous_status = str(run.status)
    next_status = transition_status(run.status, target)
    run.status = next_status.value
    if next_status in TERMINAL_STATUSES and (
        next_status.value != previous_status or run.completed_at is None
    ):
        run.completed_at = datetime.now(UTC)

    return next_status


def get_control_request(run) -> str | None:
    value = run.get_summary(CONTROL_REQUEST_KEY)
    return str(value).strip().lower() if value else None


def set_control_request(run, request: str | None) -> None:
    if request:
        run.update_summary(**{CONTROL_REQUEST_KEY: request})
    else:
        run.remove_summary_keys(CONTROL_REQUEST_KEY)
