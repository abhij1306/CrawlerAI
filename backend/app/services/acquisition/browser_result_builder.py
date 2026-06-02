from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import inspect
import logging
import time
from typing import Any, cast

import httpx
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition.browser_capture import is_response_closed_error
from app.services.acquisition.browser_page_helpers import (
    capture_listing_visual_elements as _capture_listing_visual_elements,
    location_interstitial_detected,
    object_int as _object_int,
)
from app.services.acquisition.browser_readiness import HtmlAnalysis
from app.services.acquisition.browser_recovery import capture_rendered_listing_fragments
from app.services.acquisition.runtime import BlockPageClassification, copy_headers
from app.services.config.design_system import (
    DESIGN_SYSTEM_BROWSER_SNAPSHOT_SCRIPT,
    DESIGN_SYSTEM_SURFACE,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class BrowserFinalizeInput:
    page: Any
    url: str
    surface: str | None
    browser_reason: str | None
    on_event: Any
    response: Any
    navigation_strategy: str
    readiness_probes: list[dict[str, object]]
    networkidle_timed_out: bool
    networkidle_skip_reason: str | None
    readiness_policy: dict[str, object]
    readiness_diagnostics: dict[str, object]
    expansion_diagnostics: dict[str, object]
    listing_recovery_diagnostics: dict[str, object]
    payload_capture: Any
    html: str
    traversal_result: Any
    rendered_html: str
    phase_timings_ms: dict[str, int]
    started_at: float
    interstitial_diagnostics: dict[str, object] | None = None
    capture_screenshot: bool = False
    html_analysis: HtmlAnalysis | None = None

class BrowserAcquisitionResultBuilder:
    def __init__(
        self,
        payload: BrowserFinalizeInput,
        *,
        blocked_html_checker,
        classify_blocked_page_async,
        classify_low_content_reason,
        classify_browser_outcome,
        capture_browser_screenshot,
        emit_browser_event,
        elapsed_ms,
        build_browser_diagnostics_impl,
        build_browser_artifacts_impl,
        capture_rendered_listing_fragments_impl,
        capture_listing_visual_elements_impl,
        ready_probe_supports_fast_finalize_impl,
        logger_impl,
    ) -> None:
        self.payload = payload
        self.blocked_html_checker = blocked_html_checker
        self.classify_blocked_page_async = classify_blocked_page_async
        self.classify_low_content_reason = classify_low_content_reason
        self.classify_browser_outcome = classify_browser_outcome
        self.capture_browser_screenshot = capture_browser_screenshot
        self.emit_browser_event = emit_browser_event
        self.elapsed_ms = elapsed_ms
        self.build_browser_diagnostics = build_browser_diagnostics_impl
        self.build_browser_artifacts = build_browser_artifacts_impl
        self.capture_rendered_listing_fragments = capture_rendered_listing_fragments_impl
        self.capture_listing_visual_elements = capture_listing_visual_elements_impl
        self.ready_probe_supports_fast_finalize = ready_probe_supports_fast_finalize_impl
        self.logger = logger_impl

    async def build(self) -> dict[str, object]:
        payload = self.payload
        response_missing = payload.response is None
        status_code = (
            int(
                getattr(
                    payload.response,
                    "browser_recovered_status",
                    getattr(payload.response, "status", 0),
                )
                or 0
            )
            if payload.response is not None
            else 0
        )
        payload_capture_started_at = time.perf_counter()
        capture_summary = await payload.payload_capture.close(payload.page)
        payload.phase_timings_ms["payload_capture"] = self.elapsed_ms(
            payload_capture_started_at
        )
        html_bytes = len(payload.html.encode("utf-8"))
        fast_finalize = self.ready_probe_supports_fast_finalize(
            payload.readiness_probes,
            surface=payload.surface,
            status_code=status_code,
            expansion_diagnostics=payload.expansion_diagnostics,
        )
        if fast_finalize:
            blocked_classification = BlockPageClassification(
                blocked=False,
                outcome="ok",
            )
            blocked = False
            challenge_evidence: list[str] = []
            low_content_reason = None
            location_interstitial_present = False
        else:
            blocked_classification = await self.classify_blocked_page_async(
                payload.html, status_code
            )
            blocked_result = self.blocked_html_checker(payload.html, status_code)
            if inspect.isawaitable(blocked_result):
                blocked_result = await blocked_result
            blocked = bool(blocked_classification.blocked) or bool(blocked_result)
            if blocked and not blocked_classification.blocked:
                blocked_classification = BlockPageClassification(
                    blocked=True,
                    outcome="challenge_page",
                    evidence=["blocked_html_checker"],
                )
            challenge_evidence = list(blocked_classification.evidence or [])
            low_content_reason = self.classify_low_content_reason(
                payload.html,
                html_bytes=html_bytes,
            )
            location_interstitial_present = location_interstitial_detected(
                payload.html, analysis=payload.html_analysis
            )
        browser_outcome = self.classify_browser_outcome(
            html=payload.html,
            html_bytes=html_bytes,
            blocked=blocked,
            block_classification=blocked_classification,
            traversal_result=payload.traversal_result,
        )
        if location_interstitial_present:
            blocked = True
            browser_outcome = "location_required"
            low_content_reason = "location_required"
            blocked_classification = replace(
                blocked_classification,
                blocked=True,
                outcome="location_required",
                evidence=list(
                    dict.fromkeys([*challenge_evidence, "location_interstitial"])
                ),
            )
            challenge_evidence = list(blocked_classification.evidence)
        await self._emit_events(browser_outcome=browser_outcome, blocked=blocked)
        screenshot_path = await self._capture_screenshot(
            browser_outcome=browser_outcome
        )
        (
            rendered_listing_fragments,
            listing_visual_elements,
            listing_artifact_diagnostics,
        ) = await self._capture_listing_artifacts()
        design_system_snapshot = await self._capture_design_system_snapshot()
        payload.phase_timings_ms["total"] = self.elapsed_ms(payload.started_at)
        listing_evidence_counts = {
            "rendered_listing_fragments": len(rendered_listing_fragments),
            "listing_visual_elements": len(listing_visual_elements),
        }
        diagnostics = self.build_browser_diagnostics(
            browser_reason=payload.browser_reason,
            browser_outcome=browser_outcome,
            navigation_strategy=payload.navigation_strategy,
            response_missing=response_missing,
            networkidle_timed_out=payload.networkidle_timed_out,
            networkidle_skip_reason=payload.networkidle_skip_reason,
            readiness_policy=payload.readiness_policy,
            phase_timings_ms=payload.phase_timings_ms,
            html_bytes=html_bytes,
            challenge_evidence=challenge_evidence,
            blocked_classification=blocked_classification,
            low_content_reason=low_content_reason,
            readiness_probes=payload.readiness_probes,
            capture_summary=capture_summary,
            readiness_diagnostics=payload.readiness_diagnostics,
            expansion_diagnostics=payload.expansion_diagnostics,
            listing_recovery_diagnostics=payload.listing_recovery_diagnostics,
            listing_artifact_diagnostics=listing_artifact_diagnostics,
            interstitial_diagnostics={
                **dict(payload.interstitial_diagnostics or {}),
                "location_required": location_interstitial_present,
            },
            traversal_result=payload.traversal_result,
        )
        diagnostics["rendered_listing_fragment_count"] = listing_evidence_counts[
            "rendered_listing_fragments"
        ]
        diagnostics["listing_visual_element_count"] = listing_evidence_counts[
            "listing_visual_elements"
        ]
        diagnostics["extractable_listing_evidence"] = listing_evidence_counts
        artifacts = self.build_browser_artifacts(
            screenshot_path=screenshot_path,
            traversal_result=payload.traversal_result,
            html=payload.html,
            rendered_html=payload.rendered_html,
            rendered_listing_fragments=(
                rendered_listing_fragments
                if _capture_status_ok(
                    listing_artifact_diagnostics,
                    "rendered_listing_fragment_capture",
                )
                else None
            ),
            listing_visual_elements=(
                listing_visual_elements
                if _capture_status_ok(
                    listing_artifact_diagnostics,
                    "listing_visual_capture",
                )
                else None
            ),
        )
        if design_system_snapshot:
            artifacts["design_system_snapshot"] = design_system_snapshot
        return {
            "response_missing": response_missing,
            "status_code": status_code,
            "blocked": blocked,
            "diagnostics": diagnostics,
            "artifacts": artifacts,
            "network_payloads": capture_summary.payloads,
            "page_headers": (
                copy_headers(payload.response.headers)
                if payload.response is not None
                else httpx.Headers()
            ),
            "content_type": (
                payload.response.headers.get("content-type", "text/html")
                if payload.response is not None
                else "text/html"
            ),
            "platform_family": resolve_platform_runtime_policy(
                payload.page.url,
                payload.html,
                surface=payload.surface,
            ).get("family"),
        }

    async def _emit_events(self, *, browser_outcome: str, blocked: bool) -> None:
        payload = self.payload
        if payload.traversal_result is not None and payload.traversal_result.activated:
            await self.emit_browser_event(
                payload.on_event,
                "info",
                (
                    "Traversal complete - "
                    f"mode={payload.traversal_result.selected_mode or payload.traversal_result.requested_mode}, "
                    f"last_page_cards={int(payload.traversal_result.card_count or 0)}, "
                    f"fragments={len(payload.traversal_result.html_fragments)}, "
                    f"progress_events={int(payload.traversal_result.progress_events or 0)}, "
                    f"stop_reason={payload.traversal_result.stop_reason}"
                ),
            )
        if blocked:
            await self.emit_browser_event(
                payload.on_event,
                "warning",
                f"Acquisition detected rate limiting or bot protection for {payload.url}",
            )
        if browser_outcome == "usable_content":
            payload.phase_timings_ms["screenshot_capture"] = 0

    async def _capture_screenshot(self, *, browser_outcome: str) -> str:
        payload = self.payload
        if browser_outcome == "usable_content":
            return ""
        if not payload.capture_screenshot:
            payload.phase_timings_ms["screenshot_capture"] = 0
            return ""
        probes_summary = [
            {
                "stage": probe.get("stage"),
                "is_ready": probe.get("is_ready"),
                "visible_text": probe.get("visible_text_length"),
                "cards": probe.get("listing_card_count"),
            }
            for probe in payload.readiness_probes
        ]
        html_bytes = len(payload.html.encode("utf-8"))
        low_content_reason = self.classify_low_content_reason(
            payload.html,
            html_bytes=html_bytes,
        )
        self.logger.warning(
            "Browser acquisition outcome=%s url=%s html_bytes=%s low_content_reason=%s probes=%s",
            browser_outcome,
            payload.url,
            html_bytes,
            low_content_reason,
            probes_summary,
        )
        screenshot_started_at = time.perf_counter()
        try:
            return await self.capture_browser_screenshot(payload.page)
        finally:
            payload.phase_timings_ms["screenshot_capture"] = self.elapsed_ms(
                screenshot_started_at
            )

    async def _capture_listing_artifacts(
        self,
    ) -> tuple[
        list[str],
        list[dict[str, object]],
        dict[str, object],
    ]:
        payload = self.payload
        is_listing = "listing" in str(payload.surface or "").lower()
        if is_listing:
            (
                rendered_listing_fragments,
                rendered_listing_fragment_capture,
            ) = await self._capture_timed_listing_artifact(
                self.capture_rendered_listing_fragments(
                    payload.page,
                    surface=payload.surface,
                    limit=int(crawler_runtime_settings.rendered_listing_card_capture_limit),
                ),
                stage="rendered_listing_fragment_capture",
                item_kind="text",
            )
        else:
            payload.phase_timings_ms["rendered_listing_fragment_capture"] = 0
            rendered_listing_fragments, rendered_listing_fragment_capture = [], {
                "status": "skipped",
                "reason": "non_listing_surface",
            }
        if is_listing:
            (
                listing_visual_elements,
                listing_visual_capture,
            ) = await self._capture_timed_listing_artifact(
                self.capture_listing_visual_elements(
                    payload.page,
                    surface=payload.surface,
                ),
                stage="listing_visual_capture",
                item_kind="mapping",
            )
        else:
            payload.phase_timings_ms["listing_visual_capture"] = 0
            listing_visual_elements, listing_visual_capture = [], {
                "status": "skipped",
                "reason": "non_listing_surface",
            }
        return (
            cast(list[str], rendered_listing_fragments),
            cast(list[dict[str, object]], listing_visual_elements),
            {
                "rendered_listing_fragment_capture": rendered_listing_fragment_capture,
                "listing_visual_capture": listing_visual_capture,
            },
        )

    async def _capture_design_system_snapshot(self) -> dict[str, object]:
        payload = self.payload
        if str(payload.surface or "").strip().lower() != DESIGN_SYSTEM_SURFACE:
            return {}
        try:
            result = await payload.page.evaluate(DESIGN_SYSTEM_BROWSER_SNAPSHOT_SCRIPT)
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError):
            logger.debug("Design system browser snapshot failed", exc_info=True)
            return {}
        return dict(result) if isinstance(result, dict) else {}

    async def _capture_timed_listing_artifact(
        self,
        operation,
        *,
        stage: str,
        item_kind: str,
    ) -> tuple[list[object], dict[str, object]]:
        payload = self.payload
        started_at = time.perf_counter()
        artifacts, capture_diagnostics = await _capture_listing_artifact_with_timeout(
            operation,
            stage=stage,
            url=payload.url,
            item_kind=item_kind,
            logger_impl=self.logger,
        )
        payload.phase_timings_ms[stage] = self.elapsed_ms(started_at)
        return artifacts, capture_diagnostics

async def _capture_listing_artifact_with_timeout(
    operation,
    *,
    stage: str,
    url: str,
    item_kind: str = "mapping",
    logger_impl=logger,
) -> tuple[list[object], dict[str, object]]:
    timeout_seconds = max(
        0.1,
        float(crawler_runtime_settings.browser_artifact_capture_timeout_ms) / 1000,
    )
    try:
        result = await asyncio.wait_for(operation, timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger_impl.warning(
            "Timed out during %s for %s after %.1fs",
            stage,
            url,
            timeout_seconds,
        )
        return [], {"status": "timeout"}
    except PlaywrightTimeoutError:
        logger_impl.warning("Playwright timed out during %s for %s", stage, url)
        return [], {"status": "playwright_timeout"}
    except PlaywrightError as exc:
        status = "closed" if is_response_closed_error(exc) else "playwright_error"
        logger_impl.debug(
            "Listing artifact capture Playwright error stage=%s url=%s status=%s",
            stage,
            url,
            status,
            exc_info=True,
        )
        return [], {"status": status}
    except Exception:
        logger_impl.exception(
            "Listing artifact capture unexpected error stage=%s url=%s",
            stage,
            url,
        )
        return [], {"status": "unexpected_error"}
    if not isinstance(result, list):
        return [], {"status": "invalid_result"}
    rows: list[object] = []
    for item in result:
        if item_kind == "mapping" and isinstance(item, dict):
            rows.append(dict(item))
            continue
        if item_kind == "text" and isinstance(item, str):
            text = item.strip()
            if text:
                rows.append(text)
    return (rows, {"status": "ok"})

def _capture_status_ok(
    diagnostics: dict[str, object],
    key: str,
) -> bool:
    capture = diagnostics.get(key)
    if not isinstance(capture, dict):
        return False
    return str(capture.get("status") or "").strip().lower() == "ok"

def build_browser_diagnostics(
    *,
    browser_reason: str | None,
    browser_outcome: str,
    navigation_strategy: str,
    response_missing: bool,
    networkidle_timed_out: bool,
    networkidle_skip_reason: str | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
    html_bytes: int,
    challenge_evidence: list[str],
    blocked_classification,
    low_content_reason: str | None,
    readiness_probes: list[dict[str, object]],
    capture_summary,
    readiness_diagnostics: dict[str, object],
    expansion_diagnostics: dict[str, object],
    listing_recovery_diagnostics: dict[str, object],
    listing_artifact_diagnostics: dict[str, object],
    interstitial_diagnostics: dict[str, object],
    traversal_result,
) -> dict[str, object]:
    diagnostics = {
        "browser_attempted": True,
        "browser_reason": str(browser_reason or "").strip().lower() or None,
        "browser_outcome": browser_outcome,
        "navigation_strategy": navigation_strategy,
        "response_missing": response_missing,
        "networkidle_timed_out": networkidle_timed_out,
        "networkidle_wait_reason": readiness_policy.get("networkidle_reason"),
        "networkidle_skip_reason": networkidle_skip_reason,
        "html_bytes": html_bytes,
        "phase_timings_ms": phase_timings_ms,
        "challenge_evidence": challenge_evidence,
        "challenge_provider_hits": list(blocked_classification.provider_hits or []),
        "challenge_element_hits": list(
            blocked_classification.challenge_element_hits or []
        ),
        "low_content_reason": low_content_reason,
        "readiness_probes": readiness_probes,
        "network_payload_count": capture_summary.network_payload_count,
        "malformed_network_payloads": capture_summary.malformed_network_payloads,
        "network_payload_read_failures": capture_summary.network_payload_read_failures,
        "network_payload_read_timeouts": capture_summary.network_payload_read_timeouts,
        "closed_network_payloads": capture_summary.closed_network_payloads,
        "skipped_oversized_network_payloads": capture_summary.skipped_oversized_network_payloads,
        "dropped_network_payload_events": capture_summary.dropped_payload_events,
        "listing_readiness": readiness_diagnostics,
        "listing_recovery": listing_recovery_diagnostics,
        "listing_artifact_capture": listing_artifact_diagnostics,
        "interstitial": interstitial_diagnostics,
        "failure_reason": "location_required"
        if browser_outcome == "location_required"
        else None,
        "detail_expansion": expansion_diagnostics,
    }
    if traversal_result is not None:
        diagnostics.update(traversal_result.diagnostics())
    return diagnostics

def build_browser_artifacts(
    *,
    screenshot_path: str,
    traversal_result,
    html: str,
    rendered_html: str,
    rendered_listing_fragments: list[str] | None = None,
    listing_visual_elements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    if screenshot_path:
        artifacts["browser_screenshot_path"] = screenshot_path
    if rendered_listing_fragments is not None:
        artifacts["rendered_listing_fragments"] = rendered_listing_fragments
    if listing_visual_elements is not None:
        artifacts["listing_visual_elements"] = listing_visual_elements
    if traversal_result is not None and traversal_result.activated:
        artifacts["traversal_composed_html"] = traversal_result.compose_html()
        artifacts["full_rendered_html"] = rendered_html
    return artifacts

def _ready_probe_supports_fast_finalize(
    readiness_probes: list[dict[str, object]],
    *,
    surface: str | None,
    status_code: int,
    expansion_diagnostics: dict[str, object] | None = None,
) -> bool:
    if int(status_code or 0) in {401, 403, 429}:
        return False
    normalized_surface = str(surface or "").strip().lower()
    min_visible_text = int(crawler_runtime_settings.browser_readiness_visible_text_min)
    min_detail_hints = int(crawler_runtime_settings.detail_field_signal_min_count)
    min_listing_items = int(crawler_runtime_settings.listing_min_items)
    extractability = (
        cast(dict[str, object], expansion_diagnostics.get("extractability"))
        if isinstance(expansion_diagnostics, dict)
        and isinstance(expansion_diagnostics.get("extractability"), dict)
        else {}
    )
    matched_requested_fields = extractability.get("matched_requested_fields")
    extractable_fields = extractability.get("extractable_fields")
    if bool(extractability.get("verified")) and (
        bool(matched_requested_fields) or bool(extractable_fields)
    ):
        return True
    for probe in readiness_probes:
        if not isinstance(probe, dict) or not bool(probe.get("is_ready")):
            continue
        visible_text_length = _object_int(probe.get("visible_text_length"))
        if visible_text_length < min_visible_text:
            continue
        if "detail" in normalized_surface:
            if bool(probe.get("structured_data_present")):
                return True
            if _object_int(probe.get("detail_hint_count")) >= min_detail_hints:
                return True
            continue
        if "listing" in normalized_surface:
            if _object_int(probe.get("listing_card_count")) >= min_listing_items:
                return True
            if _object_int(probe.get("matched_listing_selectors")) > 0:
                return True
            continue
        return True
    return False


async def finalize_browser_fetch(
    payload: BrowserFinalizeInput,
    *,
    blocked_html_checker,
    classify_blocked_page_async,
    classify_low_content_reason,
    classify_browser_outcome,
    capture_browser_screenshot,
    emit_browser_event,
    elapsed_ms,
    build_browser_diagnostics_impl=build_browser_diagnostics,
    build_browser_artifacts_impl=build_browser_artifacts,
    capture_rendered_listing_fragments_impl=capture_rendered_listing_fragments,
    capture_listing_visual_elements_impl=_capture_listing_visual_elements,
    ready_probe_supports_fast_finalize_impl=_ready_probe_supports_fast_finalize,
    logger_impl=logger,
) -> dict[str, object]:
    builder = BrowserAcquisitionResultBuilder(
        payload,
        blocked_html_checker=blocked_html_checker,
        classify_blocked_page_async=classify_blocked_page_async,
        classify_low_content_reason=classify_low_content_reason,
        classify_browser_outcome=classify_browser_outcome,
        capture_browser_screenshot=capture_browser_screenshot,
        emit_browser_event=emit_browser_event,
        elapsed_ms=elapsed_ms,
        build_browser_diagnostics_impl=build_browser_diagnostics_impl,
        build_browser_artifacts_impl=build_browser_artifacts_impl,
        capture_rendered_listing_fragments_impl=capture_rendered_listing_fragments_impl,
        capture_listing_visual_elements_impl=capture_listing_visual_elements_impl,
        ready_probe_supports_fast_finalize_impl=ready_probe_supports_fast_finalize_impl,
        logger_impl=logger_impl,
    )
    return await builder.build()
