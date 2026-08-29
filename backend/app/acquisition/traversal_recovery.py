from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from app.acquisition.dom_runtime import (
    wait_for_dom_mutation_settle as _wait_for_dom_mutation_settle,
)
from app.acquisition.browser_capture import is_recoverable_playwright_error
from app.acquisition.events import AcquisitionEvent, emit_acquisition_event
from app.acquisition.traversal_helpers import (
    RECOVERABLE_ERRORS as _RECOVERABLE_ERRORS,
)
from app.acquisition.traversal_helpers import (
    looks_like_next_page_control as _looks_like_next_page_control,
    looks_like_paginate_control,
    remaining_timeout_ms as _remaining_timeout_ms,
)
from app.core.config.extraction_rules import TRAVERSAL_LISTING_RECOVERY_ACTIONS
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.config.selectors import COOKIE_CONSENT_SELECTORS, PAGINATION_SELECTORS

logger = logging.getLogger(__name__)
_POTENTIALLY_RECOVERABLE_ERRORS = (*_RECOVERABLE_ERRORS, RuntimeError, OSError)
_CENTER_SCROLL_SCRIPT = """(node) => {
    if (node instanceof Element) {
        node.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
}"""
_MUTE_INTERCEPTING_OVERLAYS_SCRIPT = """(target) => {
    if (!(target instanceof Element)) return 0;
    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return 0;
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    const cx = clamp(rect.left + (rect.width / 2), 1, Math.max(1, window.innerWidth - 1));
    const cy = clamp(rect.top + Math.min(rect.height / 2, 24), 1, Math.max(1, window.innerHeight - 1));
    const hints = ['cookie', 'consent', 'modal', 'overlay', 'dialog', 'popup', 'banner', 'interstitial', 'backdrop'];
    let muted = 0;
    for (const node of document.elementsFromPoint(cx, cy)) {
        if (!(node instanceof Element)) continue;
        if (node === target || node.contains(target)) break;
        const style = window.getComputedStyle(node);
        const nodeRect = node.getBoundingClientRect();
        const zIndex = Number.parseInt(style.zIndex || '0', 10);
        const signature = [
            node.id || '', node.className || '', node.getAttribute('role') || '',
            node.getAttribute('aria-label') || '', node.getAttribute('aria-modal') || '',
        ].join(' ').toLowerCase();
        const overlayLike = node.getAttribute('aria-modal') === 'true'
            || style.position === 'fixed' || style.position === 'sticky'
            || zIndex >= 100 || hints.some((hint) => signature.includes(hint));
        const coversPoint = nodeRect.width > 0 && nodeRect.height > 0
            && cx >= nodeRect.left && cx <= nodeRect.right
            && cy >= nodeRect.top && cy <= nodeRect.bottom;
        if (!overlayLike || !coversPoint) continue;
        node.setAttribute('data-crawlwise-orig-pointer-events', node.style.pointerEvents || '');
        node.setAttribute('data-crawlwise-orig-z-index', node.style.zIndex || '');
        node.style.setProperty('pointer-events', 'none', 'important');
        node.style.setProperty('z-index', '-1', 'important');
        muted += 1;
    }
    return muted;
}"""

if TYPE_CHECKING:
    from app.acquisition.traversal_types import TraversalResult


async def find_actionable_locator(page, selector_group: str):
    selectors = (
        PAGINATION_SELECTORS.get(selector_group)
        if isinstance(PAGINATION_SELECTORS, dict)
        else []
    )
    for selector in selectors or []:
        locator = page.locator(str(selector)).first
        try:
            if await locator.count() == 0:
                continue
            if not await locator.is_visible(
                timeout=int(
                    crawler_runtime_settings.traversal_locator_visible_timeout_ms
                )
            ):
                continue
            if await locator.is_disabled():
                continue
            return locator
        except _RECOVERABLE_ERRORS:
            logger.debug(
                "Traversal locator check failed for selector_group=%s selector=%s",
                selector_group,
                selector,
                exc_info=True,
            )
            continue
    if selector_group == "next_page":
        generic_locator = await _find_generic_next_page_locator(page)
        if generic_locator is not None:
            return generic_locator
        return await _find_aom_actionable_locator(
            page,
            selector_group=selector_group,
            name_pattern=r"(next|older|›|»|>)",
        )
    if selector_group == "load_more":
        return await _find_aom_actionable_locator(
            page,
            selector_group=selector_group,
            name_pattern=r"(load more|show more|see more|view more)",
        )
    return None


async def _find_generic_next_page_locator(page):
    for selector in (
        "a[rel='next']",
        "link[rel='next']",
        ".pagination-next a",
        ".pagination-next",
        ".pagination-container a[rel='next']",
        ".pagination-container a[href*='?p=']",
        ".pagination-container a[href*='&p=']",
        "[aria-label*='pagination' i] a",
        "[aria-label*='pagination' i] button",
        "[class*='pagination' i] a",
        "[class*='pagination' i] button",
        "[aria-current='page'] + a",
        "[aria-current='page'] + button",
    ):
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            if selector == "link[rel='next']":
                continue
            if not await locator.is_visible(
                timeout=int(
                    crawler_runtime_settings.traversal_locator_visible_timeout_ms
                )
            ):
                continue
            if await locator.is_disabled():
                continue
            if not (
                await looks_like_paginate_control(locator)
                or await _looks_like_next_page_control(locator)
            ):
                continue
            logger.info(
                "Traversal generic next-page selector=%s url=%s", selector, page.url
            )
            return locator
        except _RECOVERABLE_ERRORS:
            logger.debug(
                "Traversal generic next-page lookup failed selector=%s url=%s",
                selector,
                page.url,
                exc_info=True,
            )
            continue
    return None


async def recover_listing_page_content(
    page,
    *,
    on_event=None,
) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "status": "attempted",
        "limit": int(crawler_runtime_settings.listing_recovery_max_actions),
    }
    clicked_count = 0
    actions_taken: list[str] = []
    max_actions = max(0, int(crawler_runtime_settings.listing_recovery_max_actions))
    if max_actions == 0:
        diagnostics["clicked_count"] = clicked_count
        diagnostics["actions_taken"] = actions_taken
        diagnostics["status"] = "disabled"
        return diagnostics

    from app.acquisition.traversal_types import TraversalResult

    helper_result = TraversalResult(requested_mode="recovery")
    wait_ms = max(0, int(crawler_runtime_settings.listing_recovery_post_action_wait_ms))
    for action_name, pattern, _message in TRAVERSAL_LISTING_RECOVERY_ACTIONS:
        if clicked_count >= max_actions:
            diagnostics["status"] = "interaction_limit_reached"
            break
        locator = (
            await find_actionable_locator(page, "next_page")
            if action_name == "next_page"
            else await _find_aom_actionable_locator(
                page,
                selector_group=action_name,
                name_pattern=pattern,
            )
        )
        if locator is None:
            continue
        await emit_acquisition_event(
            on_event,
            AcquisitionEvent.traversal_recovery_started(action=action_name),
        )
        if not await click_with_retry(page, locator, result=helper_result):
            continue
        clicked_count += 1
        actions_taken.append(action_name)
        if wait_ms > 0:
            await page.wait_for_timeout(wait_ms)
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=int(
                    crawler_runtime_settings.traversal_settle_networkidle_timeout_ms
                ),
            )
        except _RECOVERABLE_ERRORS:
            logger.debug(
                "Listing recovery networkidle wait timed out for action=%s url=%s",
                action_name,
                getattr(page, "url", ""),
                exc_info=True,
            )
    if diagnostics["status"] == "attempted":
        diagnostics["status"] = (
            "recovered" if clicked_count > 0 else "no_actionable_elements"
        )
    diagnostics["clicked_count"] = clicked_count
    diagnostics["actions_taken"] = actions_taken
    diagnostics["click_retries"] = helper_result.click_retries
    return diagnostics


async def _find_aom_actionable_locator(
    page,
    *,
    selector_group: str,
    name_pattern: str,
):
    compiled = re.compile(name_pattern, re.IGNORECASE)
    for role in ("button", "link"):
        locator = page.get_by_role(role, name=compiled)
        try:
            count = min(await locator.count(), 10)
        except _RECOVERABLE_ERRORS:
            logger.debug(
                "Traversal AOM locator count failed selector_group=%s role=%s url=%s",
                selector_group,
                role,
                page.url,
                exc_info=True,
            )
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not await candidate.is_visible(
                    timeout=int(
                        crawler_runtime_settings.traversal_locator_visible_timeout_ms
                    )
                ):
                    continue
                if await candidate.is_disabled():
                    continue
                logger.info(
                    "Traversal AOM fallback selector_group=%s role=%s index=%s url=%s",
                    selector_group,
                    role,
                    index,
                    page.url,
                )
                return candidate
            except _RECOVERABLE_ERRORS:
                logger.debug(
                    "Traversal AOM candidate probe failed selector_group=%s role=%s index=%s url=%s",
                    selector_group,
                    role,
                    index,
                    page.url,
                    exc_info=True,
                )
                continue
    return None


async def _prepare_click_target(page, locator) -> bool:
    try:
        await locator.scroll_into_view_if_needed(
            timeout=int(crawler_runtime_settings.traversal_scroll_into_view_timeout_ms)
        )
    except _POTENTIALLY_RECOVERABLE_ERRORS as exc:
        if not is_recoverable_playwright_error(exc):
            raise
        logger.debug("Traversal scroll_into_view failed", exc_info=True)
        if not await locator_still_resolves(locator):
            return False
    try:
        await locator.evaluate(_CENTER_SCROLL_SCRIPT)
    except _POTENTIALLY_RECOVERABLE_ERRORS as exc:
        if not is_recoverable_playwright_error(exc):
            raise
        logger.debug(
            "Traversal center-scroll evaluate failed url=%s",
            page.url,
            exc_info=True,
        )
        return await locator_still_resolves(locator)
    return True


async def _try_locator_click(locator, *, timeout_ms: int, force: bool = False):
    try:
        if force:
            await locator.click(timeout=timeout_ms, force=True)
        else:
            await locator.click(timeout=timeout_ms)
        return True, None
    except _POTENTIALLY_RECOVERABLE_ERRORS as exc:
        if not is_recoverable_playwright_error(exc):
            raise
        return False, exc


async def _try_javascript_click(page, locator, *, timeout_ms: int):
    try:
        await locator.evaluate("(node) => node instanceof HTMLElement && node.click()")
        await _wait_for_dom_mutation_settle(
            page,
            quiet_window_ms=min(500, max(100, timeout_ms // 5)),
            timeout_ms=min(2000, timeout_ms),
        )
        return True, None
    except _POTENTIALLY_RECOVERABLE_ERRORS as exc:
        if not is_recoverable_playwright_error(exc):
            raise
        return False, exc


async def click_with_retry(
    page,
    locator,
    *,
    result: TraversalResult,
    deadline_at: float | None = None,
) -> bool:
    click_timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.traversal_click_timeout_ms),
    )
    if click_timeout_ms <= 0 or not await _prepare_click_target(page, locator):
        return False
    clicked, first_exc = await _try_locator_click(locator, timeout_ms=click_timeout_ms)
    if clicked:
        return True
    if not await locator_still_resolves(locator):
        return False
    result.click_retries += 1
    await dismiss_overlays_if_needed(page, locator=locator, result=result)
    try:
        clicked, force_exc = await _try_locator_click(
            locator,
            timeout_ms=click_timeout_ms,
            force=True,
        )
    finally:
        await _restore_overlays(page)
    if clicked:
        return True
    if not await locator_still_resolves(locator):
        return False
    result.click_retries += 1
    clicked, js_exc = await _try_javascript_click(
        page,
        locator,
        timeout_ms=click_timeout_ms,
    )
    if clicked:
        return True
    logger.warning(
        "Traversal all click strategies failed: normal=%s force=%s js=%s",
        type(first_exc).__name__,
        type(force_exc).__name__,
        type(js_exc).__name__,
    )
    return False


async def locator_still_resolves(locator) -> bool:
    counter = getattr(locator, "count", None)
    if not callable(counter):
        return True
    for attempt in range(2):
        try:
            if bool(await counter()):
                return True
        except _POTENTIALLY_RECOVERABLE_ERRORS as exc:
            if not is_recoverable_playwright_error(exc):
                raise
            logger.debug(
                "Traversal locator resolution probe failed",
                exc_info=True,
            )
        if attempt == 0:
            await asyncio.sleep(0)
    return False


async def _mute_intercepting_overlays(locator) -> bool:
    try:
        muted_count = await locator.evaluate(_MUTE_INTERCEPTING_OVERLAYS_SCRIPT)
    except _RECOVERABLE_ERRORS:
        logger.debug("Traversal overlay dismissal JS failed", exc_info=True)
        return False
    return int(muted_count or 0) > 0


async def _dismiss_cookie_consent(page) -> bool:
    selectors = (
        list(COOKIE_CONSENT_SELECTORS)
        if isinstance(COOKIE_CONSENT_SELECTORS, (list, tuple))
        else []
    )
    for selector in selectors[:5]:
        try:
            button = page.locator(str(selector)).first
            if await button.count() == 0 or not await button.is_visible(
                timeout=int(
                    crawler_runtime_settings.traversal_cookie_consent_visible_timeout_ms
                )
            ):
                continue
            await button.click(
                timeout=int(
                    crawler_runtime_settings.traversal_cookie_consent_click_timeout_ms
                ),
                force=True,
            )
            await _wait_for_dom_mutation_settle(
                page,
                quiet_window_ms=150,
                timeout_ms=750,
            )
            logger.info("Traversal dismissed cookie consent via %s", selector)
            return True
        except _RECOVERABLE_ERRORS:
            logger.debug(
                "Traversal cookie consent dismissal probe failed selector=%s url=%s",
                selector,
                page.url,
                exc_info=True,
            )
    return False


async def dismiss_overlays_if_needed(
    page,
    *,
    locator,
    result: TraversalResult,
) -> None:
    muted = await _mute_intercepting_overlays(locator)
    consent_dismissed = await _dismiss_cookie_consent(page)
    if muted or consent_dismissed:
        result.overlays_dismissed = True


async def _restore_overlays(page) -> None:
    """Restore overlay elements to their original inline styles after a click."""
    try:
        await page.evaluate(
            """
            () => {
                const all = document.querySelectorAll('[data-crawlwise-orig-pointer-events], [data-crawlwise-orig-z-index]');
                for (const node of all) {
                    try {
                        const origPE = node.getAttribute('data-crawlwise-orig-pointer-events');
                        const origZI = node.getAttribute('data-crawlwise-orig-z-index');
                        if (origPE !== null) {
                            if (origPE === '') {
                                node.style.removeProperty('pointer-events');
                            } else {
                                node.style.pointerEvents = origPE;
                            }
                            node.removeAttribute('data-crawlwise-orig-pointer-events');
                        }
                        if (origZI !== null) {
                            if (origZI === '') {
                                node.style.removeProperty('z-index');
                            } else {
                                node.style.zIndex = origZI;
                            }
                            node.removeAttribute('data-crawlwise-orig-z-index');
                        }
                    } catch (e) {
                        continue;
                    }
                }
            }
            """
        )
    except _RECOVERABLE_ERRORS:
        logger.debug("Traversal overlay restore JS failed", exc_info=True)
