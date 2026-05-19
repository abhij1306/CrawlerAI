from __future__ import annotations

from . import stage as _stage

apply_detail_rejection_guard = _stage._apply_detail_rejection_guard
build_acquisition_request = _stage._build_acquisition_request
log_extraction_outcome = _stage._log_extraction_outcome
remaining_url_budget_seconds = _stage._remaining_url_budget_seconds
retry_detail_challenge_shell_with_real_chrome = (
    _stage._retry_detail_challenge_shell_with_real_chrome
)
retry_patchright_detail_shell_with_real_chrome = (
    _stage._retry_patchright_detail_shell_with_real_chrome
)

__all__ = [
    "apply_detail_rejection_guard",
    "build_acquisition_request",
    "log_extraction_outcome",
    "remaining_url_budget_seconds",
    "retry_detail_challenge_shell_with_real_chrome",
    "retry_patchright_detail_shell_with_real_chrome",
]
