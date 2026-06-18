from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.services.acquisition.dom_runtime import (
    get_page_html,
    wait_for_dom_mutation_settle as _dom_wait_for_dom_mutation_settle,
)
from app.services.acquisition.playwright_compat import (
    PlaywrightError,
    PlaywrightTimeoutError,
)
from app.services.acquisition.runtime import classify_blocked_page_async
from app.services.config.extraction_rules import (
    TRAVERSAL_STRUCTURED_SCRIPT_IDS,
    TRAVERSAL_STRUCTURED_SCRIPT_TEXT_MARKERS,
    TRAVERSAL_STRUCTURED_SCRIPT_TYPES,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.listing_card_fragments import (
    base_listing_fragment_score,
    collect_listing_fragment_html,
)
from app.services.platform_policy import (
    path_tenant_boundary_family,
    requires_path_tenant_boundary,
    url_host_matches_platform_family,
)
from selectolax.lexbor import LexborHTMLParser

logger = logging.getLogger(__name__)
_RECOVERABLE_ERRORS = (PlaywrightError, PlaywrightTimeoutError)

if TYPE_CHECKING:
    from app.services.acquisition.traversal_types import TraversalResult


async def _wait_for_dom_mutation_settle(page, **kwargs):
    # skipcq: PYL-E1125 - wrapper forwards caller-provided keyword-only timeout values.
    await _dom_wait_for_dom_mutation_settle(page, **kwargs)

async def _append_html_fragment(
    page,
    result: TraversalResult,
    *,
    surface: str,
) -> None:
    html = await get_page_html(page, flatten_shadow=False)
    if not html:
        return
    fragment = _bounded_traversal_fragment_html(
        html,
        surface=surface,
        seen_cards=result._seen_card_fragments,
        seen_structured=result._seen_structured_fragments,
    )
    is_fallback = not fragment
    value = html if is_fallback else fragment
    # Dedup: compare against the last fragment of the same type
    for prev_value, prev_is_fallback in reversed(result.html_fragments):
        if prev_is_fallback == is_fallback:
            if prev_value == value:
                return
            break
    result.html_fragments.append((value, is_fallback))

async def looks_like_paginate_control(locator) -> bool:
    try:
        inspection = await locator.evaluate(
            """
            (node) => {
              if (!(node instanceof Element)) {
                return {};
              }
              const rawHref = String(node.getAttribute('href') || '').trim().toLowerCase();
              const label = [
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.textContent,
              ]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const container = node.closest(
                "[aria-label*='pagination' i], [data-testid*='pagination' i], [class*='pagination' i], nav, [role='navigation']"
              );
              const containerText = String(container?.textContent || '')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const datasetKeys = Object.keys(node.dataset || {});
              const currentPage = container?.querySelector?.(
                "[aria-current='page'], [aria-current='true'], [class*='current' i], [class*='active' i]"
              );
              const pageNodes = container
                ? Array.from(container.querySelectorAll('a, button, [role=\"button\"]'))
                : [];
              const currentIndex = currentPage
                ? pageNodes.findIndex(
                    (candidate) => candidate === currentPage || candidate.contains(currentPage)
                  )
                : -1;
              const nodeIndex = pageNodes.findIndex((candidate) => candidate === node);
              return {
                raw_href: rawHref,
                has_click_handler:
                  typeof node.onclick === 'function' ||
                  node.hasAttribute('onclick') ||
                  datasetKeys.some((key) => /(page|paginate|next|cursor)/i.test(key)),
                pagination_container: Boolean(container),
                pagination_text:
                  /\\b(next|previous|prev|page|older|newer)\\b/.test(label) ||
                  /\\b(next|previous|prev|page|older|newer)\\b/.test(containerText),
                sibling_page_numbers: /(?:^|\\s)\\d+(?:\\s|$)/.test(containerText),
                follows_current_page:
                  currentIndex >= 0 && nodeIndex === currentIndex + 1,
                arrow_only: /^(>|›|»)$/.test(label),
                is_button_like:
                  String(node.tagName || '').toLowerCase() === 'button' ||
                  String(node.getAttribute('role') || '').trim().toLowerCase() === 'button',
              };
            }
            """
        )
    except _RECOVERABLE_ERRORS:
        logger.debug("Traversal next_page control inspection failed", exc_info=True)
        return False
    if not isinstance(inspection, dict):
        return False
    if bool(inspection.get("pagination_container")) and (
        bool(inspection.get("has_click_handler"))
        or bool(inspection.get("is_button_like"))
    ):
        return True
    if bool(inspection.get("pagination_container")) and bool(
        inspection.get("follows_current_page")
    ) and (
        bool(inspection.get("arrow_only"))
        or bool(inspection.get("raw_href"))
        or bool(inspection.get("is_button_like"))
        or bool(inspection.get("has_click_handler"))
    ):
        return True
    if bool(inspection.get("pagination_container")) and bool(
        inspection.get("sibling_page_numbers")
    ) and bool(inspection.get("arrow_only")):
        return True
    if bool(inspection.get("pagination_text")) and (
        bool(inspection.get("has_click_handler"))
        or bool(inspection.get("sibling_page_numbers"))
        or bool(inspection.get("is_button_like"))
    ):
        return True
    return False

async def _looks_like_next_page_control(locator) -> bool:
    try:
        inspection = await locator.evaluate(
            """
            (node) => {
              if (!(node instanceof Element)) {
                return {};
              }
              const text = [
                node.textContent,
                node.getAttribute('aria-label'),
                node.getAttribute('title'),
                node.getAttribute('rel'),
                node.className,
              ]
                .filter(Boolean)
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();
              const disabled =
                node.hasAttribute('disabled') ||
                node.getAttribute('aria-disabled') === 'true' ||
                /disabled/.test(String(node.className || '').toLowerCase());
              return { text, disabled };
            }
            """
        )
    except _RECOVERABLE_ERRORS:
        return False
    if not isinstance(inspection, dict):
        return False
    if bool(inspection.get("disabled")):
        return False
    text = str(inspection.get("text") or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in ("next", "older", "more", ">", "›", "»"))

async def _page_matches_block_challenge(page) -> bool:
    html = await get_page_html(page, flatten_shadow=False)
    if not html:
        return False
    classification = await classify_blocked_page_async(html, 200)
    return bool(classification.blocked)

def _bounded_traversal_fragment_html(
    html: str,
    *,
    surface: str,
    seen_cards: set[str],
    seen_structured: set[str],
) -> str:
    parser = LexborHTMLParser(html)
    max_bytes = max(8_192, int(crawler_runtime_settings.traversal_fragment_max_bytes))
    script_budget = max_bytes // 3
    structured_fragments = _collect_structured_script_fragments(
        parser,
        seen=seen_structured,
        byte_budget=script_budget,
    )
    card_budget = max_bytes - _fragments_bytes(structured_fragments)
    card_fragments = _collect_listing_card_fragments(
        parser,
        surface=surface,
        seen=seen_cards,
        byte_budget=card_budget,
    )
    if not card_fragments and not structured_fragments:
        return ""
    parts: list[str] = []
    if structured_fragments:
        parts.append('<div data-traversal-structured="true">')
        parts.extend(structured_fragments)
        parts.append("</div>")
    if card_fragments:
        parts.append('<div data-traversal-cards="true">')
        parts.extend(card_fragments)
        parts.append("</div>")
    return "\n".join(parts)

def _collect_structured_script_fragments(
    parser: LexborHTMLParser,
    *,
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    if byte_budget <= 0:
        return []
    fragments: list[str] = []
    used_bytes = 0
    for node in parser.css("script"):
        attrs = getattr(node, "attributes", {}) or {}
        script_id = str(attrs.get("id") or "").strip().lower()
        script_type = str(attrs.get("type") or "").strip().lower()
        text = str(node.text(strip=True) or "")
        if not text:
            continue
        if not (
            script_type in TRAVERSAL_STRUCTURED_SCRIPT_TYPES
            or script_id in TRAVERSAL_STRUCTURED_SCRIPT_IDS
            or any(
                marker in text.lower()
                for marker in TRAVERSAL_STRUCTURED_SCRIPT_TEXT_MARKERS
            )
        ):
            continue
        fragment = str(node.html or "").strip()
        if not fragment or fragment in seen:
            continue
        fragment_bytes = len(fragment.encode("utf-8"))
        if used_bytes + fragment_bytes > byte_budget:
            continue
        seen.add(fragment)
        fragments.append(fragment)
        used_bytes += fragment_bytes
    return fragments

def _collect_listing_card_fragments(
    parser: LexborHTMLParser,
    *,
    surface: str,
    seen: set[str],
    byte_budget: int,
) -> list[str]:
    return collect_listing_fragment_html(
        parser,
        surface=surface,
        seen=seen,
        byte_budget=byte_budget,
        score_node=base_listing_fragment_score,
        limit=max(1, int(crawler_runtime_settings.listing_fallback_fragment_limit)),
    )

def _fragments_bytes(fragments: list[str]) -> int:
    return sum(len(fragment.encode("utf-8")) for fragment in fragments if fragment)

async def _settle_after_action(
    page,
    *,
    deadline_at: float | None,
    timeout_ms: int | None = None,
) -> None:
    wait_ms = _remaining_timeout_ms(
        deadline_at,
        int(timeout_ms or crawler_runtime_settings.traversal_min_settle_wait_ms),
    )
    if wait_ms <= 0:
        return
    try:
        await page.wait_for_load_state("networkidle", timeout=min(1500, wait_ms * 2))
    except _RECOVERABLE_ERRORS:
        logger.debug(
            "Traversal networkidle settle wait failed url=%s",
            page.url,
            exc_info=True,
        )
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=min(1500, wait_ms * 2))
    except _RECOVERABLE_ERRORS:
        logger.debug(
            "Traversal domcontentloaded settle wait failed url=%s",
            page.url,
            exc_info=True,
        )
    await _wait_for_dom_mutation_settle(
        page,
        quiet_window_ms=min(500, max(100, wait_ms // 4)),
        timeout_ms=wait_ms,
    )

async def _wait_for_transition(
    page,
    *,
    previous_url: str,
    navigation_expected: bool = False,
    deadline_at: float | None = None,
    timeout_ms: int | None = None,
) -> None:
    await _wait_for_navigation_if_changed(
        page,
        previous_url=previous_url,
        navigation_expected=navigation_expected,
        deadline_at=deadline_at,
    )
    await _settle_after_action(page, deadline_at=deadline_at, timeout_ms=timeout_ms)

async def _wait_for_navigation_if_changed(
    page,
    *,
    previous_url: str,
    navigation_expected: bool,
    deadline_at: float | None,
) -> None:
    if navigation_expected or page.url != previous_url:
        await _wait_for_domcontentloaded(page, deadline_at=deadline_at)
        return
    poll_ms = max(1, int(crawler_runtime_settings.pagination_post_click_poll_ms))
    timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.pagination_post_click_timeout_ms),
    )
    if timeout_ms <= 0:
        return
    waited_ms = 0
    while waited_ms < timeout_ms:
        step_ms = min(poll_ms, max(1, timeout_ms - waited_ms))
        await page.wait_for_timeout(step_ms)
        waited_ms += step_ms
        if page.url != previous_url:
            await _wait_for_domcontentloaded(page, deadline_at=deadline_at)
            return

async def _wait_for_domcontentloaded(page, *, deadline_at: float | None) -> None:
    timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.pagination_post_click_domcontentloaded_timeout_ms),
    )
    if timeout_ms <= 0:
        return
    try:
        await page.wait_for_load_state(
            "domcontentloaded",
            timeout=timeout_ms,
        )
    except _RECOVERABLE_ERRORS:
        logger.debug("Traversal domcontentloaded wait failed", exc_info=True)
        return

def _deadline_reached(deadline_at: float | None) -> bool:
    return deadline_at is not None and time.monotonic() >= deadline_at

def _remaining_timeout_ms(deadline_at: float | None, default_ms: int, *, min_ms: int = 500) -> int:
    if deadline_at is None:
        return max(min_ms, int(default_ms))
    remaining_ms = int((deadline_at - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        return 0
    return max(min_ms, min(int(default_ms), remaining_ms))

async def _emit_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("Traversal event callback failed", exc_info=True)

def is_same_origin(current_url: str, next_url: str) -> bool:
    current = urlsplit(str(current_url or ""))
    next_value = urlsplit(str(next_url or ""))
    if (
        str(current.scheme or "").lower(),
        str(current.netloc or "").lower(),
    ) != (
        str(next_value.scheme or "").lower(),
        str(next_value.netloc or "").lower(),
    ):
        return False
    current_host = _host_without_port(current.netloc)
    next_host = _host_without_port(next_value.netloc)
    if current_host != next_host:
        return False
    # Also compare the first path segment to prevent cross-tenant bleed
    # on path-based multi-tenant architectures (e.g. myworkdayjobs.com/TenantA).
    if _requires_path_tenant_boundary(current_url, next_url):
        current_first = (str(current.path or "").strip("/").split("/") + [""])[0].lower()
        next_first = (str(next_value.path or "").strip("/").split("/") + [""])[0].lower()
        if current_first and next_first and current_first != next_first:
            return False
    return True

def _host_without_port(netloc: str) -> str:
    return str(netloc or "").split(":", 1)[0].lower()

def _requires_path_tenant_boundary(current_url: str, next_url: str) -> bool:
    current_family = path_tenant_boundary_family(current_url)
    next_family = path_tenant_boundary_family(next_url)
    if not current_family or current_family != next_family:
        return False
    return (
        requires_path_tenant_boundary(current_url)
        and requires_path_tenant_boundary(next_url)
        and url_host_matches_platform_family(current_url, current_family)
        and url_host_matches_platform_family(next_url, next_family)
    )


append_html_fragment = _append_html_fragment
deadline_reached = _deadline_reached
emit_event = _emit_event
looks_like_next_page_control = _looks_like_next_page_control
page_matches_block_challenge = _page_matches_block_challenge
remaining_timeout_ms = _remaining_timeout_ms
settle_after_action = _settle_after_action
wait_for_traversal_dom_mutation_settle = _wait_for_dom_mutation_settle
wait_for_transition = _wait_for_transition
