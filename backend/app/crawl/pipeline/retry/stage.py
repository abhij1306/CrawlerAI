from __future__ import annotations

import asyncio
from dataclasses import replace
import time

from app.models.crawl_settings import CrawlRunSettings
from app.core.config.domain_profiles import CAPTURE_NETWORK_ALL_SMALL_JSON
from app.acquisition.acquirer import (
    AcquisitionRequest,
    PageEvidence,
    acquire as _acquire,
)
from app.acquisition.contracts import EscalationAttemptDiagnostics
from app.acquisition.browser_runtime import build_failed_browser_diagnostics
from app.acquisition.policy import AcquisitionPolicy
from app.crawl.profile import (
    apply_acquisition_contract_to_profile,
    resolve_url_acquisition_recipe,
)
from app.extraction.contracts import ExtractionResult
from app.crawl.pipeline.record_extraction_stage import (
    extract_records_for_acquisition as _extract_records_for_acquisition,
)
from app.crawl.pipeline.runtime_helpers import (
    log_pipeline_event as _log_pipeline_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.persistence.publish import build_acquisition_profile, build_url_metrics
from app.crawl.pipeline.url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

acquire = _acquire


async def retry_extraction_request_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    result: ExtractionResult,
) -> ExtractionResult:
    """Climb the bounded browser escalation ladder.

    Each rung acquires with the browser and re-extracts. The rung count is
    bounded by ``retry_request.max_attempts`` — which the contract clamps to
    ``CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP`` — so the ladder is finite and
    config-owned, never unbounded. Climbing stops when the verdict no longer
    requests a retry, the acquisition cannot escalate further, or the rung
    budget is spent, then exits honestly with the last extraction result.
    """
    retry_request = result.retry_request
    while retry_request is not None and retry_request.required:
        browser_result = await _acquire_browser_retry_result(
            context,
            fetched,
            retry_reason=retry_request.reason,
            required_artifacts=retry_request.required_artifacts,
            max_attempts=retry_request.max_attempts,
        )
        if browser_result is None:
            return result
        fetched.acquisition_result = browser_result
        result, _selector_rules = await _extract_records_for_acquisition(
            context,
            fetched,
        )
        retry_request = result.retry_request
    return result


async def build_acquisition_request(
    context: _URLProcessingContext,
) -> AcquisitionRequest:
    settings_view = context.run.settings_view
    recipe = await resolve_url_acquisition_recipe(
        context.session,
        url=context.url,
        surface=context.surface,
        explicit_settings=settings_view.as_dict(),
    )
    resolved = CrawlRunSettings.from_value(recipe)
    plan = resolved.acquisition_plan(
        surface=context.surface,
        max_records=context.config.max_records,
    )
    plan = _apply_context_plan_overrides(plan, context, settings_view)
    profile = apply_acquisition_contract_to_profile(
        build_acquisition_profile(resolved),
        resolved.acquisition_contract(),
    )
    policy = AcquisitionPolicy.from_profile(profile)
    return AcquisitionRequest(
        run_id=context.run.id,
        url=context.url,
        plan=plan,
        requested_fields=list(context.requested_fields),
        requested_field_selectors={},
        acquisition_profile=policy.to_profile(),
        policy=policy,
        on_event=_pipeline_acquisition_event_logger(context),
    )


def _apply_context_plan_overrides(plan, context, settings_view):
    if context.config.proxy_list != settings_view.proxy_list():
        plan = plan.with_updates(proxy_list=tuple(context.config.proxy_list))
    if context.config.traversal_mode != settings_view.traversal_mode():
        plan = plan.with_updates(traversal_mode=context.config.traversal_mode)
    if context.config.max_pages != settings_view.max_pages():
        plan = plan.with_updates(max_pages=context.config.max_pages)
    if context.config.max_scrolls != settings_view.max_scrolls():
        plan = plan.with_updates(max_scrolls=context.config.max_scrolls)
    if context.config.sleep_ms != settings_view.sleep_ms():
        plan = plan.with_updates(sleep_ms=context.config.sleep_ms)
    return plan


def _pipeline_acquisition_event_logger(context: _URLProcessingContext):
    async def _log(level: str, message: str) -> None:
        await _log_pipeline_event(context, level, message)

    return _log


def remaining_url_budget_seconds(context: _URLProcessingContext) -> float:
    return max(
        0.0,
        float(context.url_timeout_seconds)
        - max(0.0, time.monotonic() - float(context.started_at_monotonic)),
    )


async def _acquire_browser_retry_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    retry_reason: str,
    required_artifacts: tuple[str, ...] = (),
    max_attempts: int = 1,
    forced_browser_engine: str | None = None,
):
    acquisition_result = fetched.acquisition_result
    # Budget-first: the ladder may climb up to ``max_attempts`` browser rungs
    # (contract-clamped to CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP). Once the budget
    # is spent, stop honestly.
    if context.browser_escalation_count >= max(1, max_attempts):
        await _log_pipeline_event(
            context,
            "info",
            f"Skipping browser retry for {context.url}: browser retry budget exhausted",
        )
        return None
    browser_attempted = PageEvidence.from_acquisition_result(
        acquisition_result
    ).browser_attempted
    # An initial browser result satisfies rendered HTML, but not a requested
    # network capability unless it actually captured payloads. Avoid repeating
    # an already-satisfied acquisition while still allowing the bounded network
    # rung to repair browser-first runs that started with capture disabled.
    if (
        context.browser_escalation_count == 0
        and browser_attempted
        and _required_retry_artifacts_present(acquisition_result, required_artifacts)
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Skipping browser retry for {context.url}: required artifacts already captured",
        )
        return None
    profile_updates: dict[str, object] = {
        "fetch_mode": "browser_only",
        "prefer_browser": True,
        "retry_reason": retry_reason,
    }
    if (
        (context.browser_escalation_count > 0 or browser_attempted)
        and "network_payloads" in required_artifacts
    ):
        profile_updates["capture_network"] = CAPTURE_NETWORK_ALL_SMALL_JSON
    if forced_browser_engine:
        profile_updates["forced_browser_engine"] = forced_browser_engine
    request = replace(
        (await build_acquisition_request(context)).with_profile_updates(
            **profile_updates
        ),
        attempt_timeout_seconds=remaining_url_budget_seconds(context),
    )
    session = getattr(context, "session", None)
    commit = getattr(session, "commit", None) if session is not None else None
    if callable(commit):
        await commit()
    else:
        await _log_pipeline_event(
            context,
            "warning",
            "Skipping browser retry pre-acquire commit: context.session is missing or has no async commit API",
        )
    try:
        from app.crawl.pipeline import extraction_loop

        acquire_impl = getattr(extraction_loop, "acquire", acquire)
        context.browser_escalation_count += 1
        browser_result = await acquire_impl(request)
        attempt = EscalationAttemptDiagnostics(
            rung=context.browser_escalation_count,
            attempt=context.browser_escalation_count,
            max_attempts=max(1, max_attempts),
            reason=retry_reason,
            required_artifacts=tuple(required_artifacts),
            capture_network=request.policy.capture_network,
        ).model_dump(mode="json")
        attempts = getattr(context, "escalation_attempts", None)
        if not isinstance(attempts, list):
            attempts = []
            setattr(context, "escalation_attempts", attempts)
        attempts.append(attempt)
        diagnostics = dict(browser_result.acquisition_diagnostics or {})
        diagnostics["escalation"] = {
            "rung": context.browser_escalation_count,
            "attempt": context.browser_escalation_count,
            "max_attempts": max(1, max_attempts),
            "capability_requests": list(attempts),
        }
        browser_result.acquisition_diagnostics = diagnostics
        return browser_result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _merge_browser_diagnostics(
            acquisition_result,
            build_failed_browser_diagnostics(
                browser_reason=f"{retry_reason.replace('_', '-')} retry",
                exc=exc,
            ),
        )
        fetched.url_metrics = build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        )
        await _log_pipeline_event(
            context,
            "warning",
            (
                f"Browser retry failed for {context.url}: "
                f"{type(exc).__name__}: {exc}; using the original HTTP payload"
            ),
        )
        return None


def _required_retry_artifacts_present(
    acquisition_result,
    required_artifacts: tuple[str, ...],
) -> bool:
    available = set()
    if (
        PageEvidence.from_acquisition_result(acquisition_result).browser_attempted
        and str(getattr(acquisition_result, "html", "") or "")
    ):
        available.add("rendered_html")
    if list(getattr(acquisition_result, "network_payloads", []) or []):
        available.add("network_payloads")
    return set(required_artifacts).issubset(available)
