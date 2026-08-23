from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

from app.acquisition.browser_accessibility import (
    accessibility_expand_candidates as _accessibility_expand_candidates,
    expand_interactive_elements_via_accessibility as _expand_via_accessibility,
)
from app.acquisition.browser_detail_candidates import candidate_is_admitted
from app.core.config.extraction_rules import (
    BROWSER_DETAIL_EXPAND_KEYWORDS,
    BROWSER_REQUESTED_DETAIL_SELECTOR_PRIORITY,
    DETAIL_EXPANSION_STATUS_ATTEMPTED,
    DETAIL_EXPANSION_STATUS_EXPANDED,
    DETAIL_EXPANSION_STATUS_INTERACTION_FAILED,
    DETAIL_EXPANSION_STATUS_INTERACTION_LIMIT_REACHED,
    DETAIL_EXPANSION_STATUS_NO_MATCHES,
    DETAIL_EXPANSION_STATUS_SKIPPED,
    DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED,
    DETAIL_EXPAND_KEYWORD_EXTENSIONS,
    DETAIL_EXPAND_SELECTORS,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.records.field_policy import (
    NORMALIZED_REQUESTED_FIELD_ALIASES,
    exact_requested_field_key,
    normalize_requested_field,
)
from app.core.shared.coerce_primitives import string_list
from app.core.shared.field_coerce import coerce_int as _coerce_int

logger = logging.getLogger(__name__)

_DETAIL_EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    str(key): tuple(str(item) for item in value or [])
    for key, value in dict(BROWSER_DETAIL_EXPAND_KEYWORDS or {}).items()
}


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def detail_expansion_skip(reason: str) -> dict[str, object]:
    return {
        "status": DETAIL_EXPANSION_STATUS_SKIPPED,
        "reason": reason,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "dom": {},
        "aom": {},
    }


def requested_field_tokens(requested_fields: list[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for field_name in requested_fields or []:
        exact_key = exact_requested_field_key(str(field_name or ""))
        aliases = [exact_key]
        normalized = normalize_requested_field(str(field_name or ""))
        if normalized:
            aliases.extend(
                NORMALIZED_REQUESTED_FIELD_ALIASES.get(normalized, [normalized])
            )
        for alias in aliases:
            for token in re.split(r"[_\W]+", str(alias or "")):
                cleaned = token.strip().lower()
                if len(cleaned) >= 3 and cleaned not in seen:
                    seen.add(cleaned)
                    tokens.append(cleaned)
    return tuple(tokens)


def detail_expansion_keywords(
    surface: str,
    *,
    requested_fields: list[str] | None = None,
) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    family = (
        "ecommerce" if "ecommerce" in lowered else "job" if "job" in lowered else ""
    )
    keywords = list(_DETAIL_EXPAND_KEYWORDS.get(family, ()))
    keywords.extend(DETAIL_EXPAND_KEYWORD_EXTENSIONS.get(family, ()))
    keywords.extend(requested_field_tokens(requested_fields))
    return tuple(dict.fromkeys(keywords))


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> list[tuple[str, str]]:
    return _accessibility_expand_candidates(
        snapshot,
        keywords=detail_expansion_keywords(surface, requested_fields=requested_fields),
    )


async def expand_interactive_elements_via_accessibility(
    page: Any,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    return await _expand_via_accessibility(
        page,
        keywords=detail_expansion_keywords(surface, requested_fields=requested_fields),
        max_elapsed_ms=max_elapsed_ms,
    )


def _ordered_detail_expand_selectors(
    selectors: list[str],
    *,
    requested_keywords: tuple[str, ...],
) -> list[str]:
    if not requested_keywords:
        return selectors
    priority: dict[str, int] = {}
    for keyword in requested_keywords:
        for selector in selectors:
            if keyword in selector.lower():
                priority.setdefault(selector, len(priority))
    for selector in BROWSER_REQUESTED_DETAIL_SELECTOR_PRIORITY:
        priority.setdefault(selector, len(priority))
    return sorted(selectors, key=lambda selector: priority.get(selector, len(priority)))


def _requested_match_priority(
    snapshot: dict[str, object],
    *,
    requested_keywords: tuple[str, ...],
) -> tuple[int, str]:
    label = str(snapshot.get("label") or "").strip().lower()
    probe = " ".join(
        str(snapshot.get(key) or "").strip().lower()
        for key in ("label", "aria_controls", "data_qa_action", "href")
    )
    return (
        0
        if requested_keywords and any(word in probe for word in requested_keywords)
        else 1,
        label,
    )


def _new_dom_diagnostics(max_elapsed_ms: int | None) -> dict[str, object]:
    return {
        "status": DETAIL_EXPANSION_STATUS_ATTEMPTED,
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
        "limit": int(crawler_runtime_settings.detail_expand_max_interactions),
        "max_elapsed_ms": max_elapsed_ms,
    }


def _finish_expansion_diagnostics(
    diagnostics: dict[str, object],
    *,
    clicked_count: int,
    expanded_elements: list[str],
    interaction_failures: list[str],
    started_at: float,
    elapsed_ms: Callable[[float], int] = _elapsed_ms,
) -> dict[str, object]:
    if diagnostics.get("status") == DETAIL_EXPANSION_STATUS_ATTEMPTED:
        diagnostics["status"] = (
            DETAIL_EXPANSION_STATUS_EXPANDED
            if clicked_count
            else DETAIL_EXPANSION_STATUS_INTERACTION_FAILED
            if interaction_failures
            else DETAIL_EXPANSION_STATUS_NO_MATCHES
        )
    diagnostics.update(
        clicked_count=clicked_count,
        expanded_elements=expanded_elements,
        interaction_failures=interaction_failures,
        elapsed_ms=elapsed_ms(started_at),
    )
    return diagnostics


def _budget_reached(started_at: float, max_elapsed_ms: int | None) -> bool:
    return max_elapsed_ms is not None and _elapsed_ms(started_at) >= int(max_elapsed_ms)


async def _candidate_rows(
    candidates: list[Any],
    *,
    requested_keywords: tuple[str, ...],
    failures: list[str],
    started_at: float,
    max_elapsed_ms: int | None,
) -> list[tuple[Any, dict[str, object] | None]]:
    if not requested_keywords:
        return [(candidate, None) for candidate in candidates]
    rows: list[tuple[tuple[int, str], Any, dict[str, object]]] = []
    for handle in candidates:
        if _budget_reached(started_at, max_elapsed_ms):
            break
        try:
            snapshot = await interactive_candidate_snapshot(handle)
        except Exception as exc:
            failures.append(str(exc))
            logger.debug(
                "Interactive candidate snapshot failed; skipping candidate: %s",
                type(exc).__name__,
                exc_info=True,
            )
            continue
        rows.append(
            (
                _requested_match_priority(
                    snapshot, requested_keywords=requested_keywords
                ),
                handle,
                snapshot,
            )
        )
    return [
        (handle, snapshot)
        for _, handle, snapshot in sorted(rows, key=lambda row: row[0])
    ]


async def _click_dom_candidate(page: Any, handle: Any) -> None:
    await handle.scroll_into_view_if_needed()
    try:
        await handle.click(
            timeout=int(crawler_runtime_settings.detail_expand_click_timeout_ms)
        )
    except Exception:
        logger.debug(
            "Direct candidate click failed; falling back to DOM click",
            exc_info=True,
        )
        await handle.evaluate("(node) => node instanceof HTMLElement && node.click()")
    wait_ms = int(crawler_runtime_settings.accordion_expand_wait_ms)
    if wait_ms > 0:
        await page.wait_for_timeout(wait_ms)


async def _expand_selector(
    page: Any,
    *,
    selector: str,
    requested_fields: list[str] | None,
    keywords: tuple[str, ...],
    requested_keywords: tuple[str, ...],
    seen: set[tuple[str, str, str]],
    remaining: int,
    started_at: float,
    max_elapsed_ms: int | None,
    diagnostics: dict[str, object],
    failures: list[str],
) -> list[str]:
    try:
        candidates = await page.locator(selector).element_handles()
    except Exception as exc:
        failures.append(f"locator_failed:{selector}:{exc}")
        logger.debug(
            "Element-handle lookup failed for selector %r: %s",
            selector,
            type(exc).__name__,
            exc_info=True,
        )
        return []
    diagnostics["buttons_found"] = _coerce_int(diagnostics["buttons_found"]) + len(
        candidates
    )
    rows = await _candidate_rows(
        candidates,
        requested_keywords=requested_keywords,
        failures=failures,
        started_at=started_at,
        max_elapsed_ms=max_elapsed_ms,
    )
    clicked: list[str] = []
    per_selector = max(1, int(crawler_runtime_settings.detail_expand_max_per_selector))
    for handle, prefetched in rows:
        if len(clicked) >= per_selector or len(clicked) >= remaining:
            break
        if _budget_reached(started_at, max_elapsed_ms):
            diagnostics["status"] = DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED
            break
        try:
            snapshot = prefetched or await interactive_candidate_snapshot(handle)
            admitted, key, label = candidate_is_admitted(
                snapshot,
                selector=selector,
                keywords=keywords,
                requested_keywords=requested_keywords,
                requested_fields=requested_fields,
            )
            if key in seen:
                continue
            seen.add(key)
            if not admitted:
                continue
            await _click_dom_candidate(page, handle)
            clicked.append(label)
        except Exception as exc:
            failures.append(str(exc))
            logger.debug(
                "DOM candidate click failed for %r: %s",
                label,
                type(exc).__name__,
                exc_info=True,
            )
    return clicked


async def expand_all_interactive_elements(
    page: Any,
    *,
    surface: str = "",
    requested_fields: list[str] | None = None,
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    diagnostics = _new_dom_diagnostics(max_elapsed_ms)
    failures: list[str] = []
    expanded: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    requested_keywords = requested_field_tokens(requested_fields)
    keywords = detail_expansion_keywords(surface, requested_fields=requested_fields)
    limit = max(
        0,
        min(
            int(crawler_runtime_settings.detail_expand_max_interactions),
            int(crawler_runtime_settings.accordion_expand_max),
        ),
    )
    selectors = _ordered_detail_expand_selectors(
        [str(item).strip() for item in DETAIL_EXPAND_SELECTORS if str(item).strip()],
        requested_keywords=requested_keywords,
    )
    for selector in selectors:
        if len(expanded) >= limit:
            diagnostics["status"] = DETAIL_EXPANSION_STATUS_INTERACTION_LIMIT_REACHED
            break
        if _budget_reached(started_at, max_elapsed_ms):
            diagnostics["status"] = DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED
            break
        expanded.extend(
            await _expand_selector(
                page,
                selector=selector,
                requested_fields=requested_fields,
                keywords=keywords,
                requested_keywords=requested_keywords,
                seen=seen,
                remaining=limit - len(expanded),
                started_at=started_at,
                max_elapsed_ms=max_elapsed_ms,
                diagnostics=diagnostics,
                failures=failures,
            )
        )
    return _finish_expansion_diagnostics(
        diagnostics,
        clicked_count=len(expanded),
        expanded_elements=expanded,
        interaction_failures=failures,
        started_at=started_at,
    )


async def expand_detail_content_if_needed(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
    requested_fields: list[str] | None = None,
) -> dict[str, object]:
    from app.acquisition.browser_readiness import probe_browser_readiness

    current_probe = dict(readiness_probe or {})
    if "detail" not in str(surface or "").lower():
        return detail_expansion_skip("non_detail_surface")
    if readiness_probe and not current_probe.get("detail_like"):
        return detail_expansion_skip("not_detail_like")
    dom = await expand_all_interactive_elements(
        page,
        surface=surface,
        requested_fields=requested_fields,
        max_elapsed_ms=int(crawler_runtime_settings.detail_expand_max_elapsed_ms),
    )
    if dom.get("clicked_count", 0):
        current_probe = await probe_browser_readiness(
            page,
            url=str(getattr(page, "url", "") or ""),
            surface=surface,
        )
    aom = detail_expansion_skip("not_needed")
    aom.update(
        limit=int(crawler_runtime_settings.detail_aom_expand_max_interactions),
        max_elapsed_ms=int(crawler_runtime_settings.detail_aom_expand_max_elapsed_ms),
        attempted=False,
    )
    if not current_probe.get("is_ready"):
        aom = await expand_interactive_elements_via_accessibility(
            page,
            surface=surface,
            requested_fields=requested_fields,
            max_elapsed_ms=int(
                crawler_runtime_settings.detail_aom_expand_max_elapsed_ms
            ),
        )
    clicked = _coerce_int(dom.get("clicked_count")) + _coerce_int(
        aom.get("clicked_count")
    )
    return {
        "status": DETAIL_EXPANSION_STATUS_EXPANDED
        if clicked
        else DETAIL_EXPANSION_STATUS_ATTEMPTED,
        "reason": "missing_detail_content",
        "clicked_count": clicked,
        "expanded_elements": [
            *string_list(dom.get("expanded_elements"), accept_iterable=True),
            *string_list(aom.get("expanded_elements"), accept_iterable=True),
        ],
        "interaction_failures": [
            *string_list(dom.get("interaction_failures"), accept_iterable=True),
            *string_list(aom.get("interaction_failures"), accept_iterable=True),
        ],
        "dom": dom,
        "aom": aom,
    }


async def interactive_label(handle: Any) -> str:
    value = await handle.evaluate(
        """(node) => {
            const pieces = [node.innerText, node.textContent, node.getAttribute('aria-label'), node.getAttribute('title'), node.getAttribute('data-testid')];
            return pieces.find((item) => item && item.trim()) || '';
        }"""
    )
    return " ".join(str(value or "").split()).strip().lower()


async def is_actionable_interactive_handle(handle: Any) -> bool:
    state = await handle.evaluate(
        """(node) => {
            if (!(node instanceof HTMLElement) || !node.isConnected) return { actionable: false };
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            const disabled = node.hasAttribute('disabled') || node.getAttribute('aria-disabled') === 'true' || node.inert;
            const hidden = node.hidden || node.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none';
            return { actionable: !(disabled || hidden || rect.width <= 0 || rect.height <= 0) };
        }"""
    )
    return isinstance(state, dict) and bool(state.get("actionable"))


async def _interactive_handle_attr(handle: Any, attr_name: str) -> str:
    getter = getattr(handle, "get_attribute", None)
    if getter is None:
        return ""
    try:
        value = await getter(attr_name)
    except Exception:
        logger.debug(
            "Attribute read %r failed on interactive handle; using empty value",
            attr_name,
            exc_info=True,
        )
        return ""
    return " ".join(str(value or "").split()).strip().lower()


async def _interactive_handle_tag_name(handle: Any) -> str:
    try:
        value = await handle.evaluate(
            "(node) => node instanceof Element ? node.tagName.toLowerCase() : ''"
        )
    except Exception:
        logger.debug(
            "Tag-name read failed on interactive handle; using empty value",
            exc_info=True,
        )
        return ""
    return " ".join(str(value or "").split()).strip().lower()


async def _interactive_handle_is_visible(handle: Any) -> bool:
    checker = getattr(handle, "is_visible", None)
    if checker is None:
        return True
    try:
        return bool(await checker())
    except Exception:
        logger.debug(
            "Visibility check failed on interactive handle; treating as hidden",
            exc_info=True,
        )
        return False


async def _interactive_handle_context_flags(handle: Any) -> dict[str, bool]:
    try:
        value = await handle.evaluate(
            """(node) => {
                const flags = {insideMain:false, insideHeader:false, insideNav:false, insideFooter:false, insideAside:false};
                let current = node instanceof Element ? node : null;
                while (current) {
                    const tag = (current.tagName || '').toLowerCase();
                    const role = (current.getAttribute('role') || '').toLowerCase();
                    if (tag === 'main' || role === 'main') flags.insideMain = true;
                    if (tag === 'header' || role === 'banner') flags.insideHeader = true;
                    if (tag === 'nav' || role === 'navigation') flags.insideNav = true;
                    if (tag === 'footer' || role === 'contentinfo') flags.insideFooter = true;
                    if (tag === 'aside' || role === 'complementary') flags.insideAside = true;
                    current = current.parentElement;
                }
                return flags;
            }"""
        )
    except Exception:
        logger.debug(
            "Context-flag read failed on interactive handle; using no flags",
            exc_info=True,
        )
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        "inside_main": bool(value.get("insideMain")),
        "inside_header": bool(value.get("insideHeader")),
        "inside_nav": bool(value.get("insideNav")),
        "inside_footer": bool(value.get("insideFooter")),
        "inside_aside": bool(value.get("insideAside")),
    }


async def interactive_candidate_snapshot(handle: Any) -> dict[str, object]:
    label = await interactive_label(handle)
    aria_label = await _interactive_handle_attr(handle, "aria-label")
    title = await _interactive_handle_attr(handle, "title")
    data_action = await _interactive_handle_attr(handle, "data-qa-action")
    data_testid = await _interactive_handle_attr(handle, "data-testid")
    context_flags = await _interactive_handle_context_flags(handle)
    return {
        "label": label,
        "probe": " ".join(
            part
            for part in (label, aria_label, title, data_action, data_testid)
            if part
        )
        .strip()
        .lower(),
        "aria_label": aria_label,
        "title": title,
        "href": await _interactive_handle_attr(handle, "href"),
        "target": await _interactive_handle_attr(handle, "target"),
        "aria_controls": await _interactive_handle_attr(handle, "aria-controls"),
        "aria_expanded": await _interactive_handle_attr(handle, "aria-expanded"),
        "data_qa_action": data_action,
        "data_testid": data_testid,
        "class_name": await _interactive_handle_attr(handle, "class"),
        "tag_name": await _interactive_handle_tag_name(handle),
        **context_flags,
        "visible": await _interactive_handle_is_visible(handle),
        "actionable": await is_actionable_interactive_handle(handle),
    }


__all__ = [
    "accessibility_expand_candidates",
    "detail_expansion_keywords",
    "expand_all_interactive_elements",
    "expand_detail_content_if_needed",
    "expand_interactive_elements_via_accessibility",
    "interactive_candidate_snapshot",
    "requested_field_tokens",
]
