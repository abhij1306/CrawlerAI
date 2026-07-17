from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.config.selectors import CLOUDFLARE_TURNSTILE_SELECTORS
from app.acquisition.listing_cards import (
    card_fragments_from_html,
    selectors_for_surface,
)

logger = logging.getLogger(__name__)

# Re-click the Turnstile checkbox at most once every N polls while the
# challenge remains unsolved. Managed challenges sometimes re-render the
# widget; a single click can land before the iframe is interactive, so we
# retry on a cooldown rather than spamming a click every poll.
_TURNSTILE_RECLICK_COOLDOWN_POLLS = 3


@dataclass(slots=True)
class _ChallengeRecoveryContext:
    page: Any
    url: str
    response: Any
    status_code: int
    phase_timings_ms: dict[str, int]
    elapsed_ms: Callable[[float], int]
    classify_blocked_page: Any
    get_page_html: Any
    looks_like_low_content_shell: Any
    clicked_turnstile: bool = False
    polls_since_turnstile_click: int = 0


async def _run_before_deadline(
    awaitable_factory: Callable[[], Any],
    *,
    deadline: float,
) -> Any | None:
    remaining_seconds = deadline - time.perf_counter()
    if remaining_seconds <= 0:
        return None
    task = asyncio.create_task(awaitable_factory())
    try:
        return await asyncio.wait_for(task, timeout=remaining_seconds)
    except asyncio.CancelledError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise
    except asyncio.TimeoutError:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return None


async def _check_challenge_state(
    context: _ChallengeRecoveryContext,
) -> tuple[Any | None, bool]:
    recovered_status = _recovered_html_status_code(context.status_code)
    html = await context.get_page_html(context.page)
    classification = await context.classify_blocked_page(html, recovered_status)
    if _challenge_has_cleared(
        html,
        status_code=recovered_status,
        classification=classification,
        looks_like_low_content_shell=context.looks_like_low_content_shell,
    ):
        return _response_for_recovered_page(
            context.response,
            context.status_code,
        ), False
    return None, _is_terminal_hard_block(classification)


async def _poll_challenge(
    context: _ChallengeRecoveryContext,
    *,
    max_wait_seconds: float,
    poll_ms: int,
) -> tuple[Any | None, bool, float]:
    started_at = time.perf_counter()
    deadline = started_at + max_wait_seconds
    terminal_hard_block = False
    recovered = None
    while time.perf_counter() < deadline:
        state = await _run_before_deadline(
            lambda: _check_challenge_state(context),
            deadline=deadline,
        )
        if state is not None:
            recovered, terminal_hard_block = state
            if recovered is not None or terminal_hard_block:
                break
        await _run_before_deadline(
            lambda: _maybe_click_turnstile(context),
            deadline=deadline,
        )
        await _run_before_deadline(
            lambda: _emit_challenge_activity(context.page),
            deadline=deadline,
        )
        state = await _run_before_deadline(
            lambda: _check_challenge_state(context),
            deadline=deadline,
        )
        if state is not None:
            recovered, terminal_hard_block = state
            if recovered is not None or terminal_hard_block:
                break
        remaining_ms = max(0, int((deadline - time.perf_counter()) * 1000))
        if remaining_ms <= 0:
            break
        await context.page.wait_for_timeout(min(poll_ms, remaining_ms))
    context.phase_timings_ms["challenge_wait"] = context.elapsed_ms(started_at)
    return recovered, terminal_hard_block, deadline


async def _retry_challenge_navigation(
    context: _ChallengeRecoveryContext,
    *,
    deadline: float,
    navigation_timeout_ms: int,
) -> Any:
    started_at = time.perf_counter()
    remaining_budget_ms = max(500, int((deadline - started_at) * 1000))
    try:
        retried_response = await context.page.goto(
            context.url,
            wait_until="domcontentloaded",
            timeout=min(remaining_budget_ms, int(navigation_timeout_ms)),
        )
    except Exception:
        context.phase_timings_ms["challenge_retry"] = context.elapsed_ms(started_at)
        return context.response
    context.phase_timings_ms["challenge_retry"] = context.elapsed_ms(started_at)
    retry_status = int(
        getattr(retried_response, "status", context.status_code) or context.status_code
    )
    try:
        html = await context.get_page_html(context.page)
        classification = await context.classify_blocked_page(
            html,
            _recovered_html_status_code(retry_status),
        )
    except Exception:
        return context.response
    if not _challenge_has_cleared(
        html,
        status_code=_recovered_html_status_code(retry_status),
        classification=classification,
        looks_like_low_content_shell=context.looks_like_low_content_shell,
    ):
        return context.response
    return _response_for_recovered_page(
        retried_response if retried_response is not None else context.response,
        retry_status,
        navigation_strategy="domcontentloaded",
    )


async def recover_browser_challenge(
    page: Any,
    *,
    url: str,
    response: Any,
    browser_engine: str | None = None,
    _browser_engine: str | None = None,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    challenge_wait_max_seconds: float,
    challenge_poll_interval_ms: int,
    navigation_timeout_ms: int,
    elapsed_ms: Callable[[float], int],
    classify_blocked_page,
    get_page_html,
    looks_like_low_content_shell=None,
):
    del browser_engine, _browser_engine, timeout_seconds
    phase_timings_ms.setdefault("challenge_wait", 0)
    phase_timings_ms.setdefault("challenge_retry", 0)
    max_wait_seconds = max(0.0, float(challenge_wait_max_seconds or 0))
    if max_wait_seconds <= 0:
        return response
    status_code = int(getattr(response, "status", 0) or 0)
    context = _ChallengeRecoveryContext(
        page=page,
        url=url,
        response=response,
        status_code=status_code,
        phase_timings_ms=phase_timings_ms,
        elapsed_ms=elapsed_ms,
        classify_blocked_page=classify_blocked_page,
        get_page_html=get_page_html,
        looks_like_low_content_shell=looks_like_low_content_shell,
    )
    initial_html = await get_page_html(page)
    initial_classification = await classify_blocked_page(initial_html, status_code)
    if _challenge_has_cleared(
        initial_html,
        status_code=status_code,
        classification=initial_classification,
        looks_like_low_content_shell=looks_like_low_content_shell,
    ):
        return response
    recovered, terminal_block, deadline = await _poll_challenge(
        context,
        max_wait_seconds=max_wait_seconds,
        poll_ms=max(100, int(challenge_poll_interval_ms)),
    )
    if recovered is not None:
        return recovered
    if terminal_block:
        return response
    return await _retry_challenge_navigation(
        context,
        deadline=deadline,
        navigation_timeout_ms=navigation_timeout_ms,
    )


def _challenge_has_cleared(
    html: str,
    *,
    status_code: int,
    classification: Any,
    looks_like_low_content_shell,
) -> bool:
    _ = status_code
    if bool(getattr(classification, "blocked", False)):
        return False
    if looks_like_low_content_shell is None:
        return True
    providers = list(getattr(classification, "provider_hits", []) or [])
    if not providers:
        return True
    try:
        low_content = bool(
            looks_like_low_content_shell(
                html,
                html_bytes=len(str(html or "").encode("utf-8", errors="ignore")),
            )
        )
    except Exception:
        low_content = False
    if not low_content:
        return True
    return False


# Interstitial copy that marks an interactive (solvable) "wait while we check
# you" challenge — Cloudflare's "Just a moment..." / "Checking your browser..."
# managed challenge. These phrases are unique to interactive interstitials;
# terminal denials say "Access Denied" / "you have been blocked" instead. The
# Turnstile widget renders a beat after this shell paints, so on the first poll
# the only signal present is this copy — without recognizing it as solvable the
# recovery loop mistakes the page for a terminal hard block and bails before the
# widget can be clicked.
_INTERACTIVE_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "checking if the site connection",
)


def _is_solvable_interactive_challenge(classification: Any) -> bool:
    """An interactive "wait while we verify you" challenge is solvable, not terminal.

    Kept narrow on purpose (the user's "only for particular pages, not all
    blocked pages"): it fires on the Cloudflare interstitial copy, or on a
    Cloudflare-branded challenge whose Turnstile element is already present, so
    genuine terminal denials (Akamai/PerimeterX "Access Denied") still fail fast.
    """
    strong = {
        str(item).strip().lower()
        for item in getattr(classification, "strong_hits", None) or []
    }
    title_blob = " ".join(
        str(item).strip().lower()
        for item in getattr(classification, "title_matches", None) or []
    )
    marker_blob = " ".join(sorted(strong)) + " " + title_blob
    if any(marker in marker_blob for marker in _INTERACTIVE_CHALLENGE_MARKERS):
        return True
    # Fallback: the interstitial copy may not have painted (or may be localized),
    # but a Cloudflare-branded managed challenge whose Turnstile iframe/stage is
    # already in the DOM is still solvable.
    providers = {
        str(item).strip().lower()
        for item in getattr(classification, "provider_hits", None) or []
    } | {
        str(item).strip().lower()
        for item in getattr(classification, "active_provider_hits", None) or []
    }
    is_cloudflare = bool(
        {"cloudflare", "cf-challenge", "cf-browser-verification"} & providers
    )
    has_challenge_element = bool(
        getattr(classification, "challenge_element_hits", None)
    )
    return is_cloudflare and has_challenge_element


def _is_terminal_hard_block(classification: Any) -> bool:
    """A terminal hard block is a final denial page, not a solvable challenge.

    Akamai/PerimeterX render an "Access Denied" page (title/strong blocker text)
    with no active challenge markers. Waiting/polling cannot clear it, so the
    recovery loop should stop early and let engine escalation proceed instead of
    burning the full challenge budget on a page that will never change.
    """
    if not bool(getattr(classification, "blocked", False)):
        return False
    # A Cloudflare interactive challenge looks terminal on the first poll (title
    # marker, no rendered widget yet) but is solvable — keep waiting so the
    # Turnstile renders and gets clicked.
    if _is_solvable_interactive_challenge(classification):
        return False
    has_terminal_evidence = bool(
        getattr(classification, "title_matches", None)
        or getattr(classification, "strong_hits", None)
    )
    has_active_challenge = bool(
        getattr(classification, "active_provider_hits", None)
        or getattr(classification, "challenge_element_hits", None)
    )
    return has_terminal_evidence and not has_active_challenge


def _recovered_html_status_code(status_code: int) -> int:
    return 200 if int(status_code or 0) in {403, 429} else int(status_code or 0)


def _response_for_recovered_page(
    response: Any,
    status_code: int,
    *,
    navigation_strategy: str | None = None,
) -> Any:
    if int(status_code or 0) not in {403, 429}:
        if navigation_strategy is not None:
            with suppress(Exception):
                setattr(response, "browser_navigation_strategy", navigation_strategy)
        return response
    with suppress(Exception):
        setattr(response, "browser_recovered_status", 200)
    if navigation_strategy is not None:
        with suppress(Exception):
            setattr(response, "browser_navigation_strategy", navigation_strategy)
    return response


@dataclass(frozen=True, slots=True)
class _ChallengeActivitySettings:
    steps: int
    edge_padding: int
    jitter_moves: int
    jitter_delta_px: int
    pause_min_ms: int
    pause_jitter_ms: int
    scroll_px: int


def _challenge_activity_settings() -> _ChallengeActivitySettings:
    settings = crawler_runtime_settings
    return _ChallengeActivitySettings(
        steps=max(1, int(settings.challenge_activity_mouse_steps or 1)),
        edge_padding=max(0, int(settings.challenge_activity_edge_padding_px or 0)),
        jitter_moves=max(1, int(settings.challenge_activity_jitter_moves or 1)),
        jitter_delta_px=max(1, int(settings.challenge_activity_jitter_delta_px or 1)),
        pause_min_ms=max(0, int(settings.challenge_activity_pause_min_ms or 0)),
        pause_jitter_ms=max(0, int(settings.challenge_activity_pause_jitter_ms or 0)),
        scroll_px=max(0, int(settings.challenge_activity_scroll_px or 0)),
    )


async def _challenge_viewport(page: Any) -> tuple[int, int] | None:
    try:
        viewport = await page.evaluate(
            """() => ({
                width: Math.max(window.innerWidth || 0, document.documentElement?.clientWidth || 0, document.body?.clientWidth || 0),
                height: Math.max(window.innerHeight || 0, document.documentElement?.clientHeight || 0, document.body?.clientHeight || 0),
            })"""
        )
    except Exception:
        return None
    if not isinstance(viewport, dict):
        return None
    return (
        max(1, int(viewport.get("width") or 0)),
        max(1, int(viewport.get("height") or 0)),
    )


def _next_mouse_target(
    current_x: int,
    current_y: int,
    *,
    width: int,
    height: int,
    settings: _ChallengeActivitySettings,
) -> tuple[int, int]:
    delta = settings.jitter_delta_px
    return (
        _clamp_mouse_coordinate(
            current_x + secrets.randbelow(delta * 2) - delta,
            width,
            settings.edge_padding,
        ),
        _clamp_mouse_coordinate(
            current_y + secrets.randbelow(delta * 2) - delta,
            height,
            settings.edge_padding,
        ),
    )


async def _move_challenge_mouse(
    page: Any,
    mouse: Any,
    *,
    width: int,
    height: int,
    settings: _ChallengeActivitySettings,
) -> None:
    move = getattr(mouse, "move", None)
    if not callable(move):
        return
    current_x = _clamp_mouse_coordinate(
        (width // 2) + secrets.randbelow(400) - 200,
        width,
        settings.edge_padding,
    )
    current_y = _clamp_mouse_coordinate(
        (height // 2) + secrets.randbelow(300) - 150,
        height,
        settings.edge_padding,
    )
    await move(current_x, current_y)
    _mark_mouse_move(mouse)
    for _ in range(settings.jitter_moves):
        target_x, target_y = _next_mouse_target(
            current_x,
            current_y,
            width=width,
            height=height,
            settings=settings,
        )
        for step_index in range(1, settings.steps + 1):
            progress = step_index / settings.steps
            x = round(
                current_x + (target_x - current_x) * progress + secrets.randbelow(7) - 3
            )
            y = round(
                current_y + (target_y - current_y) * progress + secrets.randbelow(7) - 3
            )
            await move(
                _clamp_mouse_coordinate(x, width, settings.edge_padding),
                _clamp_mouse_coordinate(y, height, settings.edge_padding),
            )
            _mark_mouse_move(mouse)
            await page.wait_for_timeout(secrets.randbelow(15) + 5)
        current_x, current_y = target_x, target_y
        pause_ms = settings.pause_min_ms
        if settings.pause_jitter_ms:
            pause_ms += secrets.randbelow(settings.pause_jitter_ms)
        if pause_ms > 0:
            await page.wait_for_timeout(pause_ms)


async def _emit_challenge_activity(page: Any) -> None:
    mouse = getattr(page, "mouse", None)
    viewport = await _challenge_viewport(page) if mouse is not None else None
    if mouse is None or viewport is None:
        return
    settings = _challenge_activity_settings()
    try:
        await _move_challenge_mouse(
            page,
            mouse,
            width=viewport[0],
            height=viewport[1],
            settings=settings,
        )
        wheel = getattr(mouse, "wheel", None)
        if callable(wheel) and settings.scroll_px:
            await wheel(0, settings.scroll_px)
    except Exception:
        return


async def _find_turnstile_box(page: Any) -> dict[str, float] | None:
    """Return the bounding box of the first visible Cloudflare Turnstile widget.

    Cross-origin Turnstile renders inside a ``challenges.cloudflare.com`` iframe;
    we cannot reach into it, but the element handle's bounding box gives us the
    on-page coordinates so a real mouse click can land on the checkbox.
    """
    query = getattr(page, "query_selector", None)
    if not callable(query):
        return None
    for selector in CLOUDFLARE_TURNSTILE_SELECTORS:
        try:
            handle = await query(selector)
        except Exception:
            continue
        if handle is None:
            continue
        try:
            box = await handle.bounding_box()
        except Exception:
            box = None
        if (
            isinstance(box, dict)
            and float(box.get("width") or 0) > 0
            and float(box.get("height") or 0) > 0
        ):
            return {
                "x": float(box.get("x") or 0),
                "y": float(box.get("y") or 0),
                "width": float(box["width"]),
                "height": float(box["height"]),
            }
    return None


async def _move_mouse_toward(
    page: Any, mouse: Any, target_x: float, target_y: float
) -> None:
    move = getattr(mouse, "move", None)
    if not callable(move):
        return
    settings = _challenge_activity_settings()
    steps = max(2, settings.steps)
    viewport = await _challenge_viewport(page)
    if viewport is not None:
        width, height = viewport
        pad = settings.edge_padding

        def clamp_x(value: float) -> int:
            return _clamp_mouse_coordinate(int(value), width, pad)

        def clamp_y(value: float) -> int:
            return _clamp_mouse_coordinate(int(value), height, pad)
    else:

        def clamp_x(value: float) -> int:
            return max(0, int(value))

        def clamp_y(value: float) -> int:
            return max(0, int(value))

    start_x = clamp_x(target_x - 120 + secrets.randbelow(60))
    start_y = clamp_y(target_y - 90 + secrets.randbelow(60))
    await move(start_x, start_y)
    _mark_mouse_move(mouse)
    for step_index in range(1, steps + 1):
        progress = step_index / steps
        x = clamp_x(
            start_x + (target_x - start_x) * progress + secrets.randbelow(5) - 2
        )
        y = clamp_y(
            start_y + (target_y - start_y) * progress + secrets.randbelow(5) - 2
        )
        await move(x, y)
        _mark_mouse_move(mouse)
        await page.wait_for_timeout(secrets.randbelow(20) + 8)


async def _attempt_turnstile_click(page: Any) -> bool:
    """Best-effort click on the Cloudflare Turnstile checkbox.

    Turnstile renders its checkbox at the left of the widget, vertically
    centered, so we aim just inside the left edge. Fully guarded — any failure
    (no widget, no mouse, navigation mid-click) is swallowed and reported as
    "no click issued" so the polling loop simply continues waiting.
    """
    box = await _find_turnstile_box(page)
    if box is None:
        return False
    mouse = getattr(page, "mouse", None)
    click = getattr(mouse, "click", None)
    if not callable(click):
        return False
    target_x = box["x"] + min(30.0, box["width"] / 2)
    target_y = box["y"] + box["height"] / 2
    try:
        await _move_mouse_toward(page, mouse, target_x, target_y)
        await click(target_x, target_y)
        _mark_mouse_move(mouse)
    except Exception:
        logger.debug("Turnstile click attempt failed", exc_info=True)
        return False
    return True


async def _maybe_click_turnstile(context: _ChallengeRecoveryContext) -> None:
    if context.clicked_turnstile:
        if context.polls_since_turnstile_click < _TURNSTILE_RECLICK_COOLDOWN_POLLS:
            context.polls_since_turnstile_click += 1
            return
        # Cooldown elapsed: attempt one reclick and reset regardless of outcome
        # so a failed reclick waits another full cooldown window instead of
        # spamming attempts every poll.
        await _attempt_turnstile_click(context.page)
        context.polls_since_turnstile_click = 0
        return
    clicked = await _attempt_turnstile_click(context.page)
    if clicked:
        context.clicked_turnstile = True
        context.polls_since_turnstile_click = 0


async def emit_browser_behavior_activity(page: Any) -> dict[str, object]:
    if not bool(crawler_runtime_settings.browser_behavior_realism_enabled):
        return {"enabled": False}
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        return {"enabled": True, "pointer_moves": 0, "scroll_steps": 0}
    pointer_moves = 0
    scroll_steps = 0
    try:
        before = getattr(mouse, "_crawler_move_count", 0)
        await _emit_challenge_activity(page)
        after = getattr(mouse, "_crawler_move_count", before)
        pointer_moves += max(0, int(after or 0) - int(before or 0))
    except Exception:
        # Best-effort humanization metric; pointer move count is non-critical.
        logger.debug("Challenge pointer activity failed", exc_info=True)
    try:
        scroll_steps += await _emit_scroll_physics(page)
    except Exception:
        # Best-effort humanization metric; scroll count is non-critical.
        logger.debug("Challenge scroll activity failed", exc_info=True)
    return {
        "enabled": True,
        "pointer_moves": pointer_moves,
        "scroll_steps": scroll_steps,
    }


async def type_text_like_human(
    page: Any, selector: str, text: str
) -> dict[str, object]:
    target_selector = str(selector or "").strip()
    target_text = str(text or "")
    if not target_selector or not target_text:
        return {"typed_chars": 0}
    locator_factory = getattr(page, "locator", None)
    keyboard = getattr(page, "keyboard", None)
    if not callable(locator_factory) or keyboard is None:
        return {"typed_chars": 0}
    typed_chars = 0
    try:
        locator = locator_factory(target_selector)
        click = getattr(locator, "click", None)
        if callable(click):
            await click(
                timeout=int(crawler_runtime_settings.traversal_click_timeout_ms)
            )
        for character in target_text:
            type_fn = getattr(keyboard, "type", None)
            if not callable(type_fn):
                break
            await type_fn(character)
            typed_chars += 1
            await page.wait_for_timeout(_typing_delay_ms())
    except Exception:
        # Preserve the partial typed_chars count so callers can detect partial
        # input and recover (e.g., clear the field or fall back to direct nav)
        # instead of treating the form as untouched.
        logger.debug("Humanized typing stopped early", exc_info=True)
    return {"typed_chars": typed_chars}


async def _emit_scroll_physics(page: Any) -> int:
    mouse = getattr(page, "mouse", None)
    wheel = getattr(mouse, "wheel", None)
    if not callable(wheel):
        return 0
    steps = max(0, int(crawler_runtime_settings.browser_behavior_scroll_steps or 0))
    min_px = max(0, int(crawler_runtime_settings.browser_behavior_scroll_min_px or 0))
    max_px = max(
        min_px, int(crawler_runtime_settings.browser_behavior_scroll_max_px or 0)
    )
    if steps <= 0 or max_px <= 0:
        return 0
    emitted = 0
    for step_index in range(steps):
        span = max(1, max_px - min_px + 1)
        delta = min_px + secrets.randbelow(span)
        if step_index == steps - 1 and secrets.randbelow(2) == 0:
            delta = -max(1, delta // 2)
        try:
            await wheel(0, delta)
            emitted += 1
            await page.wait_for_timeout(_behavior_pause_ms())
        except Exception:
            break
    return emitted


def _behavior_pause_ms() -> int:
    pause_ms = max(0, int(crawler_runtime_settings.browser_behavior_pause_min_ms or 0))
    jitter_ms = max(
        0, int(crawler_runtime_settings.browser_behavior_pause_jitter_ms or 0)
    )
    if jitter_ms:
        pause_ms += secrets.randbelow(jitter_ms)
    return pause_ms


def _typing_delay_ms() -> int:
    delay_ms = max(
        0, int(crawler_runtime_settings.browser_behavior_typing_min_delay_ms or 0)
    )
    jitter_ms = max(
        0, int(crawler_runtime_settings.browser_behavior_typing_jitter_ms or 0)
    )
    if jitter_ms:
        delay_ms += secrets.randbelow(jitter_ms)
    return delay_ms


def _clamp_mouse_coordinate(value: int, limit: int, padding: int) -> int:
    upper_bound = max(0, int(limit) - 1)
    effective_padding = min(max(0, int(padding)), upper_bound)
    lower_bound = min(upper_bound, effective_padding)
    max_value = max(lower_bound, upper_bound - effective_padding)
    return max(lower_bound, min(int(value), max_value))


def _mark_mouse_move(mouse: Any) -> None:
    with suppress(Exception):
        current = int(getattr(mouse, "_crawler_move_count", 0) or 0)
        setattr(mouse, "_crawler_move_count", current + 1)


async def capture_rendered_listing_fragments(
    page: Any,
    *,
    surface: str | None,
    limit: int,
) -> list[str]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    selectors = _listing_capture_selectors(str(surface or ""))
    try:
        snapshot = await page.evaluate(
            """(args) => {
                const selectors = Array.isArray(args?.selectors) ? args.selectors : [];
                const candidateLimit = Number(args?.candidateLimit || 0);
                const fragments = [];
                for (const selector of selectors) {
                    for (const card of document.querySelectorAll(selector)) {
                        const fragment = String(card.outerHTML || '').trim();
                        if (fragment) fragments.push(fragment);
                        if (candidateLimit > 0 && fragments.length >= candidateLimit) {
                            return fragments;
                        }
                    }
                }
                return fragments;
            }""",
            {
                "selectors": selectors,
                "candidateLimit": max(int(limit), int(limit) * len(selectors)),
            },
        )
    except Exception:
        return []
    if not isinstance(snapshot, list):
        return []
    candidate_html = (
        "<main>"
        + "\n".join(str(item).strip() for item in snapshot if str(item or "").strip())
        + "</main>"
    )
    return list(
        card_fragments_from_html(
            candidate_html,
            page_url=str(getattr(page, "url", "") or ""),
            surface=str(surface or ""),
            limit=limit,
        )
    )


def _listing_capture_selectors(surface: str) -> list[str]:
    return list(selectors_for_surface(surface))
