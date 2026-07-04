from __future__ import annotations

from app.core.config.extraction_rules import (
    DETAIL_CAPTURE_BLOCKED_OUTCOME,
    DETAIL_CAPTURE_ERROR_OUTCOME,
    DETAIL_CAPTURE_NOT_FOUND_OUTCOME,
    DETAIL_CAPTURE_OK_OUTCOME,
    DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME,
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
)


def normalized_detail_outcome(
    *,
    http_status: int | None,
    blocked: bool = False,
    acquisition_outcome: str | None = None,
    browser_outcome: str | None = None,
    semantic_shell: bool = False,
) -> str:
    if blocked or _outcome(acquisition_outcome) == DETAIL_CAPTURE_BLOCKED_OUTCOME:
        return DETAIL_CAPTURE_BLOCKED_OUTCOME
    if http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES:
        return DETAIL_CAPTURE_NOT_FOUND_OUTCOME
    if semantic_shell or _outcome(browser_outcome) in {
        "challenge_page",
        "low_content_shell",
    }:
        return DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME
    if _outcome(acquisition_outcome) == DETAIL_CAPTURE_ERROR_OUTCOME:
        return DETAIL_CAPTURE_ERROR_OUTCOME
    if isinstance(http_status, int) and http_status >= 500:
        return DETAIL_CAPTURE_ERROR_OUTCOME
    return _outcome(acquisition_outcome) or DETAIL_CAPTURE_OK_OUTCOME


def _outcome(value: str | None) -> str:
    return str(value or "").strip().casefold()
