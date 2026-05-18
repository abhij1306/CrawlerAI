from __future__ import annotations

import time

from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult, PageEvidence
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition.browser_runtime import (
    build_failed_browser_diagnostics,
    real_chrome_browser_available,
)
from app.services.acquisition.host_protection_memory import note_host_hard_block
from app.services.acquisition.policy import AcquisitionPolicy
from app.services.config.runtime_settings import crawler_runtime_settings
from app.models.crawl_settings import CrawlRunSettings
from app.services.crawl.profile import (
    apply_acquisition_contract_to_profile,
    resolve_url_acquisition_recipe,
)
from app.services.db_utils import mapping_or_empty
from app.services.extract.detail.assembly.record_assembly import (
    detail_record_rejection_reason,
    infer_detail_failure_reason,
)
from app.services.pipeline.extraction_retry_decision import (
    empty_extraction_browser_retry_decision as _empty_extraction_browser_retry_decision,
    low_quality_extraction_browser_retry_decision as _low_quality_extraction_browser_retry_decision,
)
from app.services.pipeline.listing_escalation_decision import (
    listing_integrity_escalation_decision as _listing_integrity_escalation_decision,
)
from app.services.pipeline.record_extraction_stage import (
    extract_records_for_acquisition as _extract_records_for_acquisition,
)
from app.services.pipeline.runtime_helpers import (
    effective_blocked as _effective_blocked,
    log_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.services.publish import build_acquisition_profile, build_url_metrics

from .url_processing_context import (
    ExtractedURLStage as _ExtractedURLStage,
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

acquire = _acquire


async def _log_pipeline_event(
    context: _URLProcessingContext,
    level: str,
    message: str,
    *,
    commit: bool = True,
) -> None:
    if not context.config.persist_logs:
        return
    await log_event(context.session, context.run.id, level, message)
    if commit:
        await context.session.commit()


def _pipeline_acquisition_event_logger(context: _URLProcessingContext):
    async def _log(level: str, message: str) -> None:
        await _log_pipeline_event(context, level, message)

    return _log


async def _apply_extraction_post_processing(*args, **kwargs):
    from app.services.pipeline import extraction_loop

    return await extraction_loop._apply_extraction_post_processing(*args, **kwargs)

async def _build_acquisition_request(
    context: _URLProcessingContext,
) -> AcquisitionRequest:
    current_settings_view = context.run.settings_view
    resolved_recipe = await resolve_url_acquisition_recipe(
        context.session,
        url=context.url,
        surface=context.surface,
        explicit_settings=current_settings_view.as_dict(),
    )
    resolved_settings_view = CrawlRunSettings.from_value(resolved_recipe)
    plan = resolved_settings_view.acquisition_plan(
        surface=context.surface,
        max_records=context.config.max_records,
        adapter_recovery_enabled=context.config.resolved_acquisition_plan(
            surface=context.surface
        ).adapter_recovery_enabled,
    )
    if context.config.proxy_list != current_settings_view.proxy_list():
        plan = plan.with_updates(proxy_list=tuple(context.config.proxy_list))
    if context.config.traversal_mode != current_settings_view.traversal_mode():
        plan = plan.with_updates(traversal_mode=context.config.traversal_mode)
    if context.config.max_pages != current_settings_view.max_pages():
        plan = plan.with_updates(max_pages=context.config.max_pages)
    if context.config.max_scrolls != current_settings_view.max_scrolls():
        plan = plan.with_updates(max_scrolls=context.config.max_scrolls)
    if context.config.sleep_ms != current_settings_view.sleep_ms():
        plan = plan.with_updates(sleep_ms=context.config.sleep_ms)
    acquisition_profile = apply_acquisition_contract_to_profile(
        build_acquisition_profile(resolved_settings_view),
        resolved_settings_view.acquisition_contract(),
    )
    acquisition_policy = AcquisitionPolicy.from_profile(acquisition_profile)
    return AcquisitionRequest(
        run_id=context.run.id,
        url=context.url,
        plan=plan,
        requested_fields=list(context.requested_fields),
        requested_field_selectors={},
        acquisition_profile=acquisition_policy.to_profile(),
        policy=acquisition_policy,
        on_event=_pipeline_acquisition_event_logger(context),
    )

async def _retry_detail_challenge_shell_with_real_chrome(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    rejection_reason: str | None,
) -> _ExtractedURLStage | None:
    if rejection_reason != "challenge_shell":
        return None
    if str(context.surface or "").strip().lower() != "ecommerce_detail":
        return None
    acquisition_result = fetched.acquisition_result
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    browser_engine = str(diagnostics.get("browser_engine") or "").strip().lower()
    if (
        getattr(acquisition_result, "method", "") != "browser"
        or browser_engine != "patchright"
    ):
        return None
    from app.services.pipeline import extraction_loop

    real_chrome_available = getattr(
        extraction_loop,
        "real_chrome_browser_available",
        real_chrome_browser_available,
    )
    if not real_chrome_available():
        return None

    remaining_budget_seconds = _remaining_url_budget_seconds(context)
    min_remaining_seconds = _post_extraction_browser_retry_min_remaining_seconds()
    if remaining_budget_seconds < min_remaining_seconds:
        await _log_pipeline_event(
            context,
            "info",
            "Skipping challenge_shell Chrome retry for "
            f"{context.url}: remaining URL budget {remaining_budget_seconds:.1f}s"
            f" < required {min_remaining_seconds:.1f}s",
        )
        return None

    from app.services.pipeline import extraction_loop

    note_hard_block = getattr(
        extraction_loop,
        "note_host_hard_block",
        note_host_hard_block,
    )
    await note_hard_block(
        acquisition_result.final_url or context.url,
        method="browser:patchright",
        vendor=None,
        status_code=getattr(acquisition_result, "status_code", None),
        proxy_used=False,
    )
    await _log_pipeline_event(
        context,
        "info",
        f"Patchright detail rejected as challenge_shell; retrying real Chrome for {context.url}",
    )

    retry_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="post_extraction_challenge_shell",
        forced_browser_engine="real_chrome",
    )
    _merge_browser_diagnostics(
        retry_result,
        {"retry_reason": "post_extraction_challenge_shell"},
    )
    fetched.acquisition_result = retry_result
    retry_records, retry_selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )
    retry_records, retry_selector_rules = await _apply_extraction_post_processing(
        context,
        acquisition_result=retry_result,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    retry_records, retry_rejection_reason = _apply_detail_rejection_guard(
        context,
        fetched,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    if retry_rejection_reason:
        await _log_pipeline_event(
            context,
            "warning",
            f"Rejected detail extraction for {context.url}: {retry_rejection_reason}",
        )
    else:
        await _log_extraction_outcome(context, retry_result, retry_records)
    return _ExtractedURLStage(fetched=fetched, records=retry_records)

async def _retry_patchright_detail_shell_with_real_chrome(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    rejection_reason: str | None,
) -> _ExtractedURLStage | None:
    if rejection_reason not in {"detail_shell", "detail_identity_mismatch"}:
        return None
    if str(context.surface or "").strip().lower() != "ecommerce_detail":
        return None
    if (
        rejection_reason == "detail_shell"
        and not bool(
            crawler_runtime_settings.post_extraction_detail_shell_real_chrome_retry_enabled
        )
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Skipping detail_shell Chrome retry for {context.url}: disabled by runtime setting",
        )
        return None
    acquisition_result = fetched.acquisition_result
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    browser_engine = str(diagnostics.get("browser_engine") or "").strip().lower()
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    if (
        getattr(acquisition_result, "method", "") != "browser"
        or browser_engine != "patchright"
        or browser_outcome != "usable_content"
    ):
        return None
    from app.services.pipeline import extraction_loop

    real_chrome_available = getattr(
        extraction_loop,
        "real_chrome_browser_available",
        real_chrome_browser_available,
    )
    if not real_chrome_available():
        return None

    remaining_budget_seconds = _remaining_url_budget_seconds(context)
    min_remaining_seconds = _post_extraction_browser_retry_min_remaining_seconds()
    if remaining_budget_seconds < min_remaining_seconds:
        await _log_pipeline_event(
            context,
            "info",
            "Skipping detail_shell Chrome retry for "
            f"{context.url}: remaining URL budget {remaining_budget_seconds:.1f}s"
            f" < required {min_remaining_seconds:.1f}s",
        )
        return None
    await _log_pipeline_event(
        context,
        "info",
        f"Patchright detail rejected as {rejection_reason}; retrying real Chrome for {context.url}",
    )

    retry_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason=f"post_extraction_{rejection_reason}",
        forced_browser_engine="real_chrome",
    )
    _merge_browser_diagnostics(
        retry_result,
        {"retry_reason": f"post_extraction_{rejection_reason}"},
    )
    fetched.acquisition_result = retry_result
    retry_records, retry_selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )
    retry_records, retry_selector_rules = await _apply_extraction_post_processing(
        context,
        acquisition_result=retry_result,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    retry_records, retry_rejection_reason = _apply_detail_rejection_guard(
        context,
        fetched,
        records=retry_records,
        selector_rules=retry_selector_rules,
    )
    if retry_rejection_reason:
        await _log_pipeline_event(
            context,
            "warning",
            f"Rejected detail extraction for {context.url}: {retry_rejection_reason}",
        )
    else:
        await _log_extraction_outcome(context, retry_result, retry_records)
    return _ExtractedURLStage(fetched=fetched, records=retry_records)

def _challenge_shell_reason(acquisition_result: AcquisitionResult) -> str | None:
    return PageEvidence.from_acquisition_result(
        acquisition_result
    ).challenge_shell_reason

def _apply_detail_rejection_guard(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str | None]:
    if "detail" not in context.surface:
        return records, None
    acquisition_result = fetched.acquisition_result
    rejection_reason = _challenge_shell_reason(acquisition_result)
    if rejection_reason is None:
        for record in records:
            if not isinstance(record, dict):
                continue
            from app.services.pipeline import extraction_loop

            rejection_checker = getattr(
                extraction_loop,
                "detail_record_rejection_reason",
                detail_record_rejection_reason,
            )
            rejection_reason = rejection_checker(
                dict(record),
                page_url=acquisition_result.final_url,
                requested_page_url=context.url,
            )
            if rejection_reason:
                break
    if rejection_reason is None and not records:
        from app.services.pipeline import extraction_loop

        failure_inferer = getattr(
            extraction_loop,
            "infer_detail_failure_reason",
            infer_detail_failure_reason,
        )
        rejection_reason = failure_inferer(
            acquisition_result.html,
            acquisition_result.final_url,
            context.surface,
            list(context.requested_fields),
            requested_page_url=context.url,
            adapter_records=acquisition_result.adapter_records,
            network_payloads=acquisition_result.network_payloads,
            selector_rules=selector_rules,
            extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        )
    if not rejection_reason:
        return records, None
    _merge_browser_diagnostics(
        acquisition_result,
        {"failure_reason": rejection_reason},
    )
    if rejection_reason == "challenge_shell":
        acquisition_result.blocked = True
        fetched.url_metrics = build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        )
        fetched.url_metrics["blocked"] = True
    fetched.url_metrics["failure_reason"] = rejection_reason
    return [], rejection_reason

async def _log_extraction_outcome(
    context: _URLProcessingContext,
    acquisition_result,
    records: list[dict[str, object]],
) -> None:
    adapter_name = str(getattr(acquisition_result, "adapter_name", "") or "").strip()
    extraction_label = (
        f"{adapter_name} adapter" if adapter_name else "generic extraction path"
    )
    if records:
        await _log_pipeline_event(
            context,
            "info",
            f"Extracted {len(records)} records using {extraction_label}",
        )
        return
    await _log_pipeline_event(
        context,
        "warning",
        f"Extraction yielded 0 records ({extraction_label})",
    )

async def _retry_empty_extraction_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    retry_decision = _empty_extraction_browser_retry_decision(
        acquisition_result,
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
        selector_rules=selector_rules,
    )
    if not retry_decision["should_retry"]:
        return records, selector_rules
    await _log_pipeline_event(
        context,
        "info",
        f"No records via {acquisition_result.method}; retrying browser render for {context.url}",
    )
    browser_result = await _acquire_browser_retry_result(
        context, fetched, retry_reason="empty_extraction"
    )
    fetched.acquisition_result = browser_result
    retry_records, retry_selector_rules = await _extract_records_for_acquisition(
        context, fetched
    )
    return retry_records, retry_selector_rules

async def _retry_low_quality_extraction_with_browser(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    if "detail" not in context.surface:
        return records, selector_rules
    if getattr(acquisition_result, "method", "") == "browser":
        return records, selector_rules
    if not records or _effective_blocked(acquisition_result):
        return records, selector_rules
    retry_decision = _low_quality_extraction_browser_retry_decision(
        acquisition_result,
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
    )
    if not retry_decision["should_retry"]:
        return records, selector_rules
    raw_missing_fields = retry_decision.get("missing_fields")
    missing_field_values = (
        raw_missing_fields if isinstance(raw_missing_fields, list) else []
    )
    missing_fields = [
        str(field_name)
        for field_name in missing_field_values
        if str(field_name).strip()
    ]
    if not missing_fields:
        return records, selector_rules
    remaining_budget_seconds = _remaining_url_budget_seconds(context)
    min_remaining_seconds = _browser_retry_min_remaining_seconds()
    if remaining_budget_seconds < min_remaining_seconds:
        await _log_pipeline_event(
            context,
            "info",
            "Skipping low-quality browser retry for "
            f"{context.url}: remaining URL budget {remaining_budget_seconds:.1f}s"
            f" < required {min_remaining_seconds:.1f}s",
        )
        return records, selector_rules
    await _log_pipeline_event(
        context,
        "info",
        "Detail record missing high-value fields "
        f"{', '.join(missing_fields)} via {acquisition_result.method}; retrying browser render for {context.url}",
    )
    browser_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="low_quality_extraction",
    )
    fetched.acquisition_result = browser_result
    return await _extract_records_for_acquisition(context, fetched)

async def _retry_listing_integrity_with_stronger_tier(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Retry at a stronger acquisition tier when the Listing_Integrity_Gate
    flags a promo_only_cluster. Applies only to listing surfaces.

    Mirrors the contract shape of _retry_low_quality_extraction_with_browser.
    """
    if "listing" not in context.surface:
        return records, selector_rules

    acquisition_result = fetched.acquisition_result

    # Retrieve the gate decision from artifacts (attached by listing_extractor
    # via _attach_gate_decision_to_artifacts during extract_listing_records).
    artifacts = mapping_or_empty(
        getattr(acquisition_result, "artifacts", {})
    )
    gate_payload = artifacts.get("listing_integrity")
    if not isinstance(gate_payload, dict):
        return records, selector_rules

    # Build a lightweight gate_decision-like object for the escalation decision.
    raw_outcome = gate_payload.get("outcome", "")
    outcome = raw_outcome if isinstance(raw_outcome, str) else ""
    raw_metrics = gate_payload.get("metrics")
    gate_decision = _ListingIntegritySnapshot(
        outcome=outcome,
        reason=str(gate_payload.get("reason", "")),
        metrics=raw_metrics if isinstance(raw_metrics, dict) else {},
    )

    # Build policy snapshot from the current acquisition request profile.
    policy_snapshot = _build_escalation_policy_snapshot(acquisition_result)

    escalation = _listing_integrity_escalation_decision(
        acquisition_result,
        gate_decision=gate_decision,
        surface=context.surface,
        retry_state=context,
        policy_snapshot=policy_snapshot,
    )

    if not escalation.get("should_retry"):
        reason = escalation.get("reason", "unknown")
        # Only log when the escalation was actually considered but skipped
        # for a non-trivial reason. "gate_ok" means the integrity gate passed
        # and no escalation was ever needed — no value in logging that.
        if reason != "gate_ok":
            await _log_pipeline_event(
                context,
                "info",
                f"listing_escalation_skipped: {reason} for {context.url}",
            )
        _merge_browser_diagnostics(
            acquisition_result,
            {
                "listing_escalation_skipped": {
                    "reason": reason,
                    "prior_tier": escalation.get("prior_tier"),
                    "next_tier": escalation.get("next_tier"),
                    "gate_reason": escalation.get("gate_reason", ""),
                    "candidate_summary": escalation.get("candidate_summary", {}),
                },
            },
        )
        # When final gate outcome is promo_only_cluster and records are empty,
        # set failure_reason on the URL result.
        if gate_decision.outcome == "promo_only_cluster" and not records:
            fetched.url_metrics["failure_reason"] = "promo_only_cluster"
            fetched.url_metrics["listing_integrity"] = gate_payload
        return records, selector_rules

    # --- Budget guard (reuse existing pattern) ---
    remaining_budget_seconds = _remaining_url_budget_seconds(context)
    min_remaining_seconds = _browser_retry_min_remaining_seconds()
    if remaining_budget_seconds < min_remaining_seconds:
        await _log_pipeline_event(
            context,
            "info",
            f"listing_escalation_skipped: budget_exhausted for {context.url}"
            f" (remaining {remaining_budget_seconds:.1f}s < required {min_remaining_seconds:.1f}s)",
        )
        _merge_browser_diagnostics(
            acquisition_result,
            {
                "listing_escalation_skipped": {
                    "reason": "budget_exhausted",
                    "prior_tier": escalation.get("prior_tier"),
                    "next_tier": escalation.get("next_tier"),
                    "gate_reason": escalation.get("gate_reason", ""),
                    "candidate_summary": escalation.get("candidate_summary", {}),
                },
            },
        )
        if gate_decision.outcome == "promo_only_cluster" and not records:
            fetched.url_metrics["failure_reason"] = "promo_only_cluster"
            fetched.url_metrics["listing_integrity"] = gate_payload
        return records, selector_rules

    # --- Increment retry count AFTER successful acquisition (at-most-one enforcement) ---

    next_tier = str(escalation.get("next_tier") or "")
    forced_engine = next_tier.replace("browser:", "") if next_tier.startswith("browser:") else None

    await _log_pipeline_event(
        context,
        "info",
        f"listing_escalation_triggered: {escalation.get('prior_tier')} → {next_tier} for {context.url}"
        f" (gate_reason={escalation.get('gate_reason')})",
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "listing_escalation_triggered": {
                "prior_tier": escalation.get("prior_tier"),
                "next_tier": next_tier,
                "gate_reason": escalation.get("gate_reason", ""),
                "candidate_summary": escalation.get("candidate_summary", {}),
            },
        },
    )

    # --- Acquire at the stronger tier ---
    retry_result = await _acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="listing_integrity_promo_cluster",
        forced_browser_engine=forced_engine,
    )
    fetched.acquisition_result = retry_result
    context.listing_integrity_retry_count += 1

    # --- Re-run extraction (Ranker + Gate re-evaluate on new observation) ---
    retry_records, retry_selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )

    # Check the new gate decision after re-extraction.
    retry_artifacts = mapping_or_empty(
        getattr(retry_result, "artifacts", {})
    )
    retry_gate_payload = retry_artifacts.get("listing_integrity")
    if (
        isinstance(retry_gate_payload, dict)
        and retry_gate_payload.get("outcome") == "promo_only_cluster"
        and not retry_records
    ):
        fetched.url_metrics["failure_reason"] = "promo_only_cluster"
        fetched.url_metrics["listing_integrity"] = retry_gate_payload

    return retry_records, retry_selector_rules

class _ListingIntegritySnapshot:
    """Lightweight stand-in for IntegrityDecision used by the escalation decision."""

    __slots__ = ("outcome", "reason", "metrics")

    def __init__(self, outcome: str, reason: str, metrics: dict[str, object]):
        self.outcome = outcome
        self.reason = reason
        self.metrics = metrics

def _build_escalation_policy_snapshot(acquisition_result) -> object:
    """Build a policy snapshot object for the escalation decision.

    Exposes challenge_state, escalation_disabled, and host_hard_block
    derived from the acquisition result and runtime settings.
    """
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    challenge_state = bool(diagnostics.get("challenge_detected"))
    host_hard_block = bool(diagnostics.get("host_hard_block"))
    # escalation_disabled is read from runtime settings inside the decision
    # function itself; expose False here so the policy snapshot doesn't
    # duplicate that check.
    return _EscalationPolicySnapshot(
        challenge_state=challenge_state,
        escalation_disabled=False,
        host_hard_block=host_hard_block,
    )

class _EscalationPolicySnapshot:
    """Minimal policy snapshot for listing_integrity_escalation_decision."""

    __slots__ = ("challenge_state", "escalation_disabled", "host_hard_block")

    def __init__(
        self,
        challenge_state: bool,
        escalation_disabled: bool,
        host_hard_block: bool,
    ):
        self.challenge_state = challenge_state
        self.escalation_disabled = escalation_disabled
        self.host_hard_block = host_hard_block

def _remaining_url_budget_seconds(context: _URLProcessingContext) -> float:
    from app.services.pipeline import extraction_loop

    facade_func = getattr(extraction_loop, "_remaining_url_budget_seconds", None)
    if facade_func is not None and facade_func is not _remaining_url_budget_seconds:
        return float(facade_func(context))
    return max(
        0.0,
        float(context.url_timeout_seconds)
        - max(0.0, time.monotonic() - float(context.started_at_monotonic)),
    )

def _browser_retry_min_remaining_seconds() -> float:
    return max(
        float(crawler_runtime_settings.low_quality_browser_retry_min_remaining_seconds),
        float(crawler_runtime_settings.browser_render_timeout_seconds),
    )


remaining_url_budget_seconds = _remaining_url_budget_seconds

def _post_extraction_browser_retry_min_remaining_seconds() -> float:
    return _browser_retry_min_remaining_seconds()

async def _acquire_browser_retry_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    retry_reason: str,
    forced_browser_engine: str | None = None,
):
    acquisition_result = fetched.acquisition_result
    profile_updates: dict[str, object] = {
        "prefer_browser": True,
        "retry_reason": retry_reason,
    }
    if forced_browser_engine:
        profile_updates["forced_browser_engine"] = forced_browser_engine
    retry_request = (await _build_acquisition_request(context)).with_profile_updates(
        **profile_updates
    )
    try:
        from app.services.pipeline import extraction_loop

        acquire_impl = getattr(extraction_loop, "acquire", acquire)
        return await acquire_impl(retry_request)
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        _merge_browser_diagnostics(
            acquisition_result,
            build_failed_browser_diagnostics(
                browser_reason=f"{retry_reason.replace('_', '-')} retry", exc=exc
            ),
        )
        fetched.url_metrics = build_url_metrics(
            acquisition_result, requested_fields=list(context.requested_fields)
        )
        await _log_pipeline_event(
            context,
            "warning",
            f"Browser retry failed for {context.url}: {type(exc).__name__}: {exc}",
        )
        raise
