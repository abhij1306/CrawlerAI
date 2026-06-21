from __future__ import annotations

import asyncio
import time
from typing import Any

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.core.config.extraction_rules import (
    DETAIL_AOM_EXPAND_ROLES,
    DETAIL_BLOCKED_TOKENS,
    DETAIL_EXPANSION_STATUS_ATTEMPTED,
    DETAIL_EXPANSION_STATUS_EXPANDED,
    DETAIL_EXPANSION_STATUS_INTERACTION_FAILED,
    DETAIL_EXPANSION_STATUS_NO_MATCHES,
    DETAIL_EXPANSION_STATUS_SKIPPED,
    DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED,
)
from app.core.config.runtime_settings import crawler_runtime_settings


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _snapshot_timeout_seconds() -> float:
    try:
        value = float(crawler_runtime_settings.browser_accessibility_snapshot_timeout_seconds)
    except (TypeError, ValueError):
        value = float(
            crawler_runtime_settings.__class__.model_fields[
                "browser_accessibility_snapshot_timeout_seconds"
            ].default
        )
    return max(0.0, value)


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    keywords: tuple[str, ...],
) -> list[tuple[str, str]]:
    if not snapshot:
        return []
    allowed_roles = set(DETAIL_AOM_EXPAND_ROLES)
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def walk(node: dict[str, object]) -> None:
        role = str(node.get("role") or "").strip().lower()
        name = " ".join(str(node.get("name") or "").split()).strip().lower()
        candidate = (role, name)
        admitted = (
            role in allowed_roles
            and bool(name)
            and not any(token in name for token in DETAIL_BLOCKED_TOKENS)
            and (not keywords or any(keyword in name for keyword in keywords))
        )
        if admitted and candidate not in seen:
            seen.add(candidate)
            results.append(candidate)
        children = node.get("children")
        for child in children if isinstance(children, list) else []:
            if isinstance(child, dict):
                walk(child)

    walk(snapshot)
    return results


async def _read_accessibility_snapshot(
    page: Any,
    diagnostics: dict[str, object],
) -> dict[str, object] | None:
    accessibility = getattr(page, "accessibility", None)
    snapshot_fn = getattr(accessibility, "snapshot", None)
    if snapshot_fn is None:
        diagnostics.update(status=DETAIL_EXPANSION_STATUS_SKIPPED, reason="accessibility_unavailable")
        return None
    diagnostics["attempted"] = True
    try:
        async with asyncio.timeout(_snapshot_timeout_seconds()):
            snapshot = await snapshot_fn()
    except (asyncio.TimeoutError, PlaywrightTimeoutError):
        diagnostics["status"] = "snapshot_timeout"
        return None
    except Exception as exc:
        diagnostics["status"] = "snapshot_failed"
        diagnostics["interaction_failures"] = [f"snapshot_failed:{exc}"]
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _prioritize_candidates(
    candidates: list[tuple[str, str]],
    *,
    keywords: tuple[str, ...],
    limit: int,
    diagnostics: dict[str, object],
) -> list[tuple[str, str]]:
    if len(candidates) <= limit:
        return candidates
    if keywords:
        matching = [item for item in candidates if any(word in item[1] for word in keywords)]
        matching_set = set(matching)
        candidates = matching + [item for item in candidates if item not in matching_set]
    diagnostics["skipped_count"] = len(candidates) - limit
    return candidates[:limit]


async def _locator_is_detail_scoped(locator: Any) -> bool:
    evaluate = getattr(locator, "evaluate", None)
    if not callable(evaluate):
        return True
    try:
        result = await evaluate(
            """(node) => {
                if (!(node instanceof Element) || !node.isConnected) return false;
                const inMain = Boolean(node.closest('main, [role="main"]'));
                const inChrome = Boolean(node.closest('header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"]'));
                return inMain || !inChrome;
            }"""
        )
    except Exception:
        return False
    return bool(result)


async def _locator_is_actionable(locator: Any, *, visibility_timeout_ms: int) -> bool:
    if hasattr(locator, "count") and await locator.count() == 0:
        return False
    wait_for = getattr(locator, "wait_for", None)
    if callable(wait_for):
        try:
            await wait_for(state="visible", timeout=visibility_timeout_ms)
        except Exception:
            return False
    elif hasattr(locator, "is_visible") and not await locator.is_visible():
        return False
    if hasattr(locator, "is_disabled") and await locator.is_disabled():
        return False
    return await _locator_is_detail_scoped(locator)


async def _click_accessibility_candidate(
    page: Any,
    *,
    role: str,
    name: str,
    click_timeout_ms: int,
    visibility_timeout_ms: int,
) -> bool:
    locator_factory = getattr(page, "get_by_role", None)
    if locator_factory is None:
        raise RuntimeError("get_by_role_unavailable")
    locator = locator_factory(role, name=name, exact=True)
    locator = getattr(locator, "first", locator)
    if not await _locator_is_actionable(locator, visibility_timeout_ms=visibility_timeout_ms):
        return False
    await locator.click(timeout=click_timeout_ms)
    wait_ms = int(crawler_runtime_settings.accordion_expand_wait_ms)
    if wait_ms > 0:
        await page.wait_for_timeout(wait_ms)
    return True


def _finish_diagnostics(
    diagnostics: dict[str, object],
    *,
    clicked: list[str],
    failures: list[str],
    started_at: float,
) -> dict[str, object]:
    if diagnostics.get("status") == DETAIL_EXPANSION_STATUS_ATTEMPTED:
        diagnostics["status"] = (
            DETAIL_EXPANSION_STATUS_EXPANDED
            if clicked
            else DETAIL_EXPANSION_STATUS_INTERACTION_FAILED
            if failures
            else DETAIL_EXPANSION_STATUS_NO_MATCHES
        )
    diagnostics["clicked_count"] = len(clicked)
    diagnostics["expanded_elements"] = clicked
    diagnostics["interaction_failures"] = failures
    diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
    return diagnostics


async def expand_interactive_elements_via_accessibility(
    page: Any,
    *,
    keywords: tuple[str, ...],
    max_elapsed_ms: int | None = None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    limit = max(0, int(crawler_runtime_settings.detail_aom_expand_max_interactions))
    diagnostics: dict[str, object] = {
        "status": DETAIL_EXPANSION_STATUS_ATTEMPTED,
        "attempted": False,
        "limit": limit,
        "max_elapsed_ms": max_elapsed_ms,
        "buttons_found": 0,
        "clicked_count": 0,
        "expanded_elements": [],
        "interaction_failures": [],
    }
    snapshot = await _read_accessibility_snapshot(page, diagnostics)
    if snapshot is None:
        diagnostics["elapsed_ms"] = _elapsed_ms(started_at)
        return diagnostics
    candidates = accessibility_expand_candidates(snapshot, keywords=keywords)
    diagnostics["buttons_found"] = len(candidates)
    candidates = _prioritize_candidates(
        candidates,
        keywords=keywords,
        limit=limit,
        diagnostics=diagnostics,
    )
    clicked: list[str] = []
    failures: list[str] = []
    for role, name in candidates:
        if max_elapsed_ms is not None and _elapsed_ms(started_at) >= int(max_elapsed_ms):
            diagnostics["status"] = DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED
            break
        try:
            if await _click_accessibility_candidate(
                page,
                role=role,
                name=name,
                click_timeout_ms=int(crawler_runtime_settings.detail_expand_click_timeout_ms),
                visibility_timeout_ms=int(crawler_runtime_settings.detail_expand_visibility_timeout_ms),
            ):
                clicked.append(name)
        except Exception as exc:
            failures.append(str(exc))
    return _finish_diagnostics(
        diagnostics,
        clicked=clicked,
        failures=failures,
        started_at=started_at,
    )


__all__ = [
    "accessibility_expand_candidates",
    "expand_interactive_elements_via_accessibility",
]
