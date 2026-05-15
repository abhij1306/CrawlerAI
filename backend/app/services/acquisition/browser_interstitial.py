"""Location-interstitial detection and safe dismissal.

Owns the cohesive concern of probing pages for location-picker interstitials
(and similar blocking modal prompts) and dismissing them by selector or text
token. `browser_page_flow.py` imports these to wrap a page in a dismiss-pass
before fetching for real. Kept separate so page-flow stays focused on
navigation and capture orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.acquisition.browser_readiness import HtmlAnalysis, analyze_html
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import (
    LOCATION_INTERSTITIAL_CONTAINER_SELECTORS,
    LOCATION_INTERSTITIAL_DISMISS_SELECTORS,
    LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS,
    LOCATION_INTERSTITIAL_TEXT_TOKENS,
)

try:
    from patchright.async_api import Error as PlaywrightError
    from patchright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover
    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass

    class PlaywrightTimeoutError(PlaywrightError):  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)


def _string_config_list(value: object) -> list[str]:
    if isinstance(value, (str, bytes)):
        return [str(value).strip()] if str(value).strip() else []
    if isinstance(value, dict):
        items: list[object] = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def location_interstitial_detected(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    analysis = analysis or analyze_html(str(html or ""))
    soup = analysis.soup
    text = analysis.normalized_text.lower()
    tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    matched_tokens = [
        token.lower() for token in tokens if token and token.lower() in text
    ]
    if not text or not matched_tokens:
        return False
    selectors = _string_config_list(LOCATION_INTERSTITIAL_CONTAINER_SELECTORS)
    for selector in selectors:
        try:
            if soup.select_one(selector) is not None:
                return True
        except Exception:
            logger.debug(
                "Invalid location interstitial selector=%s", selector, exc_info=True
            )
    for node in soup.select(
        "[aria-modal='true'], [role='dialog'], .modal, .popup, .overlay"
    ):
        node_text = " ".join(node.get_text(" ", strip=True).lower().split())
        if any(token in node_text for token in matched_tokens):
            return True
    return len(matched_tokens) >= 2


async def page_might_have_location_interstitial(page: Any) -> bool:
    selectors = _string_config_list(LOCATION_INTERSTITIAL_CONTAINER_SELECTORS)
    tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    if not tokens:
        return False
    try:
        result = await page.evaluate(
            """
            ({selectors, tokens}) => {
              const normalizedSelectors = Array.isArray(selectors) ? selectors : [];
              const normalizedTokens = (Array.isArray(tokens) ? tokens : [])
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              if (!normalizedTokens.length) {
                return false;
              }
              const hasToken = (text) => {
                const normalized = String(text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                return normalized && normalizedTokens.some((token) => normalized.includes(token));
              };
              if (normalizedSelectors.length) {
                for (const selector of normalizedSelectors) {
                  try {
                    const node = document.querySelector(selector);
                    if (node && hasToken(node.innerText || node.textContent || '')) {
                      return true;
                    }
                  } catch {}
                }
              }
              return hasToken(document.body ? document.body.innerText : '');
            }
            """,
            {"selectors": selectors, "tokens": tokens},
        )
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        logger.debug(
            "Location interstitial precheck failed url=%s",
            getattr(page, "url", ""),
            exc_info=True,
        )
        return True
    return bool(result)


async def dismiss_safe_location_interstitial(page: Any) -> dict[str, object]:
    if not await page_might_have_location_interstitial(page):
        return {"status": "not_found", "reason": "no_location_signal"}
    selectors = _string_config_list(LOCATION_INTERSTITIAL_DISMISS_SELECTORS)
    still_present_result: dict[str, object] | None = None
    visible_timeout_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_visible_timeout_ms
        if crawler_runtime_settings.traversal_location_interstitial_visible_timeout_ms
        is not None
        else crawler_runtime_settings.traversal_cookie_consent_visible_timeout_ms
    )
    click_timeout_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_click_timeout_ms
        if crawler_runtime_settings.traversal_location_interstitial_click_timeout_ms
        is not None
        else crawler_runtime_settings.traversal_cookie_consent_click_timeout_ms
    )
    postclick_wait_ms = int(
        crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
        if crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
        is not None
        else crawler_runtime_settings.cookie_consent_postclick_wait_ms
    )
    for selector in selectors:
        try:
            matches = page.locator(selector)
            if await matches.count() == 0:
                continue
            locator = matches.first
            await locator.wait_for(
                state="visible",
                timeout=visible_timeout_ms,
            )
            await locator.click(
                timeout=click_timeout_ms,
                force=True,
            )
            await page.wait_for_timeout(postclick_wait_ms)
            if not await page_might_have_location_interstitial(page):
                return {"status": "dismissed", "selector": selector}
            still_present_result = {"status": "still_present", "selector": selector}
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
            logger.debug(
                "Location interstitial dismissal probe failed selector=%s url=%s",
                selector,
                getattr(page, "url", ""),
                exc_info=True,
            )
    text_result = await _dismiss_location_interstitial_by_text(page)
    if text_result.get("status") == "dismissed":
        return text_result
    if text_result.get("status") == "still_present":
        return text_result
    if still_present_result is not None:
        return still_present_result
    return {"status": "not_found"}


async def _dismiss_location_interstitial_by_text(page: Any) -> dict[str, object]:
    tokens = _string_config_list(LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS)
    location_tokens = _string_config_list(LOCATION_INTERSTITIAL_TEXT_TOKENS)
    if not tokens:
        return {"status": "skipped", "reason": "no_text_tokens"}
    try:
        result = await page.evaluate(
            """
            ({tokens, locationTokens}) => {
              const normalizedTokens = tokens
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              const normalizedLocationTokens = locationTokens
                .map((value) => String(value || '').trim().toLowerCase())
                .filter(Boolean);
              const hasLocationText = (node) => {
                const root = node.closest('[aria-modal="true"],[role="dialog"],.modal,.popup,.overlay')
                  || node.parentElement;
                const text = String((root && (root.innerText || root.textContent)) || document.body.textContent || '')
                  .replace(/\\s+/g, ' ')
                  .trim()
                  .toLowerCase();
                return normalizedLocationTokens.some((token) => text.includes(token));
              };
              const elements = Array.from(document.querySelectorAll(
                'button,[role="button"],a,input[type="button"],input[type="submit"]'
              ));
              const visible = (node) => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden'
                  && style.display !== 'none'
                  && rect.width > 0
                  && rect.height > 0;
              };
              for (const node of elements) {
                if (!visible(node)) continue;
                if (!hasLocationText(node)) continue;
                const rawText = node.innerText || node.textContent || node.value
                  || node.getAttribute('aria-label') || '';
                const text = String(rawText).replace(/\\s+/g, ' ').trim();
                const lowered = text.toLowerCase();
                if (!lowered) continue;
                const matched = normalizedTokens.find(
                  (token) => lowered === token || lowered.includes(token)
                );
                if (!matched) continue;
                node.click();
                return {status: 'dismissed', text, selector: 'text:' + matched};
              }
              return {status: 'not_found'};
            }
            """,
            {"tokens": tokens, "locationTokens": location_tokens},
        )
        if isinstance(result, dict) and result.get("status") == "dismissed":
            # Use the same fallback chain as dismiss_safe_location_interstitial so
            # text-path and selector-path post-click waits stay consistent.
            postclick_wait_ms = int(
                crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
                if crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms
                is not None
                else crawler_runtime_settings.cookie_consent_postclick_wait_ms
            )
            await page.wait_for_timeout(postclick_wait_ms)
            if not await page_might_have_location_interstitial(page):
                return dict(result)
            return {
                **dict(result),
                "status": "still_present",
            }
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, PlaywrightTimeoutError, PlaywrightError):
        logger.debug(
            "Location interstitial text dismissal failed url=%s",
            getattr(page, "url", ""),
            exc_info=True,
        )
    return {"status": "not_found"}


__all__ = [
    "dismiss_safe_location_interstitial",
    "location_interstitial_detected",
    "page_might_have_location_interstitial",
]
