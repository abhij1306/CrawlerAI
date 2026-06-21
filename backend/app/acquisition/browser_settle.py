from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.acquisition.browser_page_helpers import (
    detail_expansion_can_skip,
    detail_expansion_extractability,
)
from app.acquisition.browser_readiness import analyze_html
from app.acquisition.dom_runtime import get_page_html
from app.core.config.selectors import CARD_SELECTORS
from app.extraction.documents import HtmlAnalysis
from app.extraction.ids import content_sha256


@dataclass(slots=True)
class _ReadinessSnapshotCache:
    page: Any
    url: str
    surface: str
    listing_override: dict[str, object] | None
    get_page_html_impl: Any
    probe_browser_readiness: Any
    html: str | None = None
    analysis: HtmlAnalysis | None = None
    analyses: dict[str, HtmlAnalysis] = field(default_factory=dict)

    async def probe(self, *, refresh_html: bool = False) -> dict[str, object]:
        if refresh_html or self.html is None:
            refreshed_html = await self.get_page_html_impl(self.page)
            snapshot_hash = content_sha256(refreshed_html or "")
            analysis = self.analyses.get(snapshot_hash)
            if analysis is None or not analysis.matches_html(refreshed_html or ""):
                analysis = await asyncio.to_thread(analyze_html, refreshed_html or "")
            if analysis is None:
                raise RuntimeError("browser readiness analysis was not produced")
            self.analyses[snapshot_hash] = analysis
            self.html = refreshed_html
            self.analysis = analysis
        elif self.analysis is None:
            self.analysis = await asyncio.to_thread(analyze_html, self.html or "")
        if self.analysis is None:
            raise RuntimeError("browser readiness analysis was not produced")
        return await self.probe_browser_readiness(
            self.page,
            url=self.url,
            surface=self.surface,
            listing_override=self.listing_override,
            html=self.html,
            analysis=self.analysis,
        )


@dataclass(slots=True)
class _SettleContext:
    page: Any
    url: str
    surface: str
    requested_fields: list[str] | None
    timeout_seconds: float
    readiness_override: dict[str, object] | None
    readiness_policy: dict[str, object]
    phase_timings_ms: dict[str, int]
    settings: Any
    wait_for_listing_readiness: Any
    expand_detail_content_if_needed: Any
    append_readiness_probe: Any
    elapsed_ms: Any
    cache: _ReadinessSnapshotCache
    readiness_probes: list[dict[str, object]] = field(default_factory=list)
    current_probe: dict[str, object] = field(default_factory=dict)

    @property
    def is_listing(self) -> bool:
        return "listing" in self.surface.lower()

    @property
    def is_detail(self) -> bool:
        return "detail" in self.surface.lower()

    async def refresh_probe(self, stage: str) -> dict[str, object]:
        self.current_probe = await self.cache.probe(refresh_html=True)
        self.append_readiness_probe(
            self.readiness_probes,
            stage=stage,
            probe=self.current_probe,
        )
        return self.current_probe


def _generic_card_selectors_for_surface(surface: str | None) -> list[str]:
    if not isinstance(CARD_SELECTORS, dict):
        return []
    normalized = str(surface or "").strip().lower()
    groups = ("jobs",) if normalized == "jobs" or normalized.startswith("job_") else ("ecommerce",)
    selectors: list[str] = []
    for group in groups:
        for selector in CARD_SELECTORS.get(group) or []:
            value = str(selector or "").strip()
            if value and value not in selectors:
                selectors.append(value)
    return selectors


async def _run_optimistic_wait(context: _SettleContext) -> None:
    wait_ms = min(
        int(context.timeout_seconds * 1000),
        int(context.settings.browser_navigation_optimistic_wait_ms),
    )
    if wait_ms <= 0 or context.current_probe["is_ready"]:
        context.phase_timings_ms["optimistic_wait"] = 0
        return
    started_at = time.perf_counter()
    try:
        await context.page.wait_for_function(
            "({visibleTextMin}) => String((document.body && (document.body.innerText || document.body.textContent)) || '').trim().length >= Number(visibleTextMin || 0)",
            arg={
                "visibleTextMin": int(
                    context.settings.browser_readiness_visible_text_min
                )
            },
            timeout=wait_ms,
        )
    except PlaywrightTimeoutError:
        pass
    context.phase_timings_ms["optimistic_wait"] = context.elapsed_ms(started_at)
    await context.refresh_probe("after_optimistic_wait")


async def _run_detail_payload_settle(
    context: _SettleContext,
    *,
    skip_reason: str,
) -> None:
    settle_ms = max(
        0,
        int(context.settings.browser_detail_payload_settle_timeout_ms or 0),
    )
    if not context.is_detail or settle_ms <= 0 or skip_reason == "fast_path_ready":
        return
    started_at = time.perf_counter()
    try:
        await context.page.wait_for_load_state(
            "networkidle",
            timeout=min(int(context.timeout_seconds * 1000), settle_ms),
        )
    except PlaywrightTimeoutError:
        pass
    context.phase_timings_ms["detail_payload_settle"] = context.elapsed_ms(started_at)


async def _run_networkidle_wait(
    context: _SettleContext,
) -> tuple[bool, str | None]:
    explicit = bool(context.readiness_policy.get("require_networkidle"))
    implicit = bool(
        not context.current_probe["is_ready"]
        and not explicit
        and (
            context.is_listing
            or not context.current_probe.get("structured_data_present")
        )
    )
    if not context.current_probe["is_ready"] and (explicit or implicit):
        started_at = time.perf_counter()
        timeout_cap = (
            int(context.settings.browser_navigation_networkidle_timeout_ms)
            if explicit
            else int(context.settings.browser_spa_implicit_networkidle_timeout_ms)
        )
        timed_out = False
        try:
            await context.page.wait_for_load_state(
                "networkidle",
                timeout=min(int(context.timeout_seconds * 1000), timeout_cap),
            )
        except PlaywrightTimeoutError:
            timed_out = True
        context.phase_timings_ms["networkidle_wait"] = context.elapsed_ms(started_at)
        await context.refresh_probe("after_networkidle")
        return timed_out, None
    context.phase_timings_ms["networkidle_wait"] = 0
    if context.current_probe["is_ready"]:
        skip_reason = "fast_path_ready"
    elif context.current_probe.get("structured_data_present"):
        skip_reason = "structured_data_present"
    else:
        skip_reason = "not_required"
    await _run_detail_payload_settle(context, skip_reason=skip_reason)
    return False, skip_reason


async def _run_platform_readiness(context: _SettleContext) -> dict[str, object]:
    started_at = time.perf_counter()
    diagnostics = await context.wait_for_listing_readiness(
        context.page,
        context.url,
        override=context.readiness_override,
    )
    context.phase_timings_ms["readiness_wait"] = context.elapsed_ms(started_at)
    await context.refresh_probe("after_platform_readiness")
    return diagnostics


async def _run_generic_listing_readiness(context: _SettleContext) -> dict[str, object]:
    selectors = _generic_card_selectors_for_surface(context.surface)
    if not selectors:
        context.phase_timings_ms["readiness_wait"] = 0
        return {"status": "skipped", "reason": "no_card_selectors"}
    override = {
        "platform": "generic",
        "selectors": selectors,
        "max_wait_ms": int(context.settings.listing_readiness_max_wait_ms or 0),
    }
    started_at = time.perf_counter()
    diagnostics = await context.wait_for_listing_readiness(
        context.page,
        context.url,
        override=override,
    )
    context.phase_timings_ms["readiness_wait"] = context.elapsed_ms(started_at)
    await context.refresh_probe("after_generic_readiness")
    return diagnostics


async def _run_generic_detail_readiness(context: _SettleContext) -> dict[str, object]:
    started_at = time.perf_counter()
    max_wait_ms = max(0, int(context.settings.surface_readiness_max_wait_ms or 0))
    if max_wait_ms > 0:
        try:
            await context.page.wait_for_function(
                """() => Boolean(
                    document.querySelector('h1')
                    || document.querySelector('[itemtype*="Product" i]')
                    || document.querySelector('[data-testid*="product" i]')
                    || document.querySelector('[class*="product" i]')
                    || document.querySelector('script[type="application/ld+json"]')
                )""",
                timeout=min(int(context.timeout_seconds * 1000), max_wait_ms),
            )
        except PlaywrightTimeoutError:
            pass
    context.phase_timings_ms["readiness_wait"] = context.elapsed_ms(started_at)
    await context.refresh_probe("after_generic_detail_readiness")
    return {
        "status": "ready" if context.current_probe["is_ready"] else "timeout",
        "reason": "generic_detail_readiness",
    }


async def _run_readiness_wait(context: _SettleContext) -> dict[str, object]:
    if context.current_probe["is_ready"]:
        context.phase_timings_ms["readiness_wait"] = 0
        return {"status": "skipped", "reason": "fast_path_ready"}
    if context.readiness_override is not None:
        return await _run_platform_readiness(context)
    if context.is_listing:
        return await _run_generic_listing_readiness(context)
    if context.is_detail:
        return await _run_generic_detail_readiness(context)
    context.phase_timings_ms["readiness_wait"] = 0
    return {"status": "skipped", "reason": "no_platform_override"}


def _skipped_expansion(reason: str) -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": reason,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "dom": {},
        "aom": {},
    }


async def _run_detail_expansion(context: _SettleContext) -> dict[str, object]:
    if not context.is_detail:
        context.phase_timings_ms["expansion"] = 0
        return _skipped_expansion("non_detail_surface")
    analysis = context.cache.analysis
    extractability = detail_expansion_extractability(
        document=analysis.document if analysis is not None else None,
        surface=context.surface,
        requested_fields=context.requested_fields,
    )
    can_skip, reason = detail_expansion_can_skip(
        extractability,
        surface=context.surface,
        requested_fields=context.requested_fields,
        readiness_probe=context.current_probe,
    )
    if can_skip:
        context.phase_timings_ms["expansion"] = 0
        diagnostics = _skipped_expansion(reason or "not_needed")
        diagnostics["extractability"] = extractability
        return diagnostics
    started_at = time.perf_counter()
    diagnostics = await context.expand_detail_content_if_needed(
        context.page,
        surface=context.surface,
        readiness_probe=context.current_probe,
        requested_fields=context.requested_fields,
    )
    context.phase_timings_ms["expansion"] = context.elapsed_ms(started_at)
    if diagnostics.get("clicked_count", 0):
        await context.refresh_probe("after_detail_expansion")
        analysis = context.cache.analysis
        diagnostics["extractability"] = detail_expansion_extractability(
            document=analysis.document if analysis is not None else None,
            surface=context.surface,
            requested_fields=context.requested_fields,
        )
    return diagnostics


async def settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    requested_fields: list[str] | None,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
    crawler_runtime_settings,
    get_page_html_impl=get_page_html,
    probe_browser_readiness,
    wait_for_listing_readiness,
    expand_detail_content_if_needed,
    append_readiness_probe,
    elapsed_ms,
):
    cache = _ReadinessSnapshotCache(
        page=page,
        url=url,
        surface=surface,
        listing_override=readiness_override,
        get_page_html_impl=get_page_html_impl,
        probe_browser_readiness=probe_browser_readiness,
    )
    context = _SettleContext(
        page=page,
        url=url,
        surface=surface,
        requested_fields=requested_fields,
        timeout_seconds=timeout_seconds,
        readiness_override=readiness_override,
        readiness_policy=readiness_policy,
        phase_timings_ms=phase_timings_ms,
        settings=crawler_runtime_settings,
        wait_for_listing_readiness=wait_for_listing_readiness,
        expand_detail_content_if_needed=expand_detail_content_if_needed,
        append_readiness_probe=append_readiness_probe,
        elapsed_ms=elapsed_ms,
        cache=cache,
    )
    await context.refresh_probe("after_navigation")
    await _run_optimistic_wait(context)
    networkidle_timed_out, networkidle_skip_reason = await _run_networkidle_wait(
        context
    )
    readiness_diagnostics = await _run_readiness_wait(context)
    expansion_diagnostics = await _run_detail_expansion(context)
    return (
        context.current_probe,
        context.readiness_probes,
        networkidle_timed_out,
        networkidle_skip_reason,
        readiness_diagnostics,
        expansion_diagnostics,
        cache.html or "",
        cache.analysis,
    )


__all__ = ["settle_browser_page"]
