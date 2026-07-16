"""Retry-backoff policy for the AI-visibility runner.

Guards the fix for the 429 storm: executions used to exhaust a tiny 3-attempt /
~6s budget while inside Gemini's per-minute quota window. The delay now prefers a
provider ``Retry-After``, caps exponential backoff, and adds deterministic jitter.
"""

from __future__ import annotations

import pytest

from app.ai_visibility import runner
from app.ai_visibility.gemini import AiVisibilityProviderError, safe_quota_detail
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_RATE_LIMIT,
    ai_visibility_settings,
)

pytestmark = pytest.mark.unit


def _rate_limit_error(*, retry_after: float | None) -> AiVisibilityProviderError:
    return AiVisibilityProviderError(
        "429",
        error_code=AI_VISIBILITY_ERROR_RATE_LIMIT,
        retryable=True,
        retry_after_seconds=retry_after,
    )


def test_safe_quota_detail_keeps_identifiers_not_provider_message() -> None:
    detail = safe_quota_detail(
        {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "prompt text must not be retained",
                "details": [
                    {
                        "violations": [
                            {
                                "quotaMetric": "generativelanguage.googleapis.com/requests",
                                "quotaId": "RequestsPerMinute",
                            }
                        ]
                    },
                    {"retryDelay": "12s"},
                ],
            }
        }
    )
    assert detail == (
        "RESOURCE_EXHAUSTED; quota=generativelanguage.googleapis.com/requests; "
        "quota_id=RequestsPerMinute; retry=12s"
    )
    assert "prompt text" not in detail


def test_retry_delay_prefers_retry_after_clamped_to_cap() -> None:
    cap = ai_visibility_settings.retry_max_delay_seconds
    # Provider-advised wait is honored when under the cap...
    assert runner._retry_delay(0, _rate_limit_error(retry_after=12.0)) == 12.0
    # ...and clamped when it exceeds the cap.
    assert runner._retry_delay(0, _rate_limit_error(retry_after=cap + 100)) == cap


def test_retry_delay_exponential_backoff_grows_and_caps() -> None:
    base = ai_visibility_settings.retry_base_delay_seconds
    cap = ai_visibility_settings.retry_max_delay_seconds
    err = _rate_limit_error(retry_after=None)

    # attempt 0 -> base (jitter is zero, since (0 * 0.37) % 1 == 0)
    assert runner._retry_delay(0, err) == base
    # Later attempts grow exponentially and never exceed cap + jitter span.
    for attempt in range(1, 8):
        delay = runner._retry_delay(attempt, err)
        assert delay >= min(base * (2**attempt), cap)
        assert delay <= cap + ai_visibility_settings.retry_jitter_seconds
