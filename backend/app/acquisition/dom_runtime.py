from __future__ import annotations

import asyncio
import logging

from app.core.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

_SHADOW_DOM_FLATTENER_SCRIPT = """
({ maxHosts, markerAttr, rootAttr, version }) => {
  const result = {
    shadow_roots_detected: 0,
    shadow_roots_flattened: 0,
    closed_shadow_roots_detected: 0,
    hidden_panel_dom_present: Boolean(document.querySelector('[hidden], [aria-hidden="true"], details:not([open])')),
    serialization_method_version: version,
    max_hosts: maxHosts,
    errors: []
  };
  const hosts = [];
  for (const el of document.querySelectorAll('*')) {
    if (!(el instanceof Element) || !el.shadowRoot) {
      continue;
    }
    hosts.push(el);
  }
  result.shadow_roots_detected = hosts.length;
  for (const el of hosts.slice(0, Math.max(0, maxHosts))) {
    try {
      if (el.hasAttribute(markerAttr)) {
        continue;
      }
      const container = document.createElement('crawlerai-shadow-root');
      container.setAttribute(rootAttr, 'open');
      container.setAttribute('data-crawlerai-shadow-version', version);
      for (const node of el.shadowRoot.childNodes) {
        container.appendChild(node.cloneNode(true));
      }
      el.setAttribute(markerAttr, version);
      el.appendChild(container);
      result.shadow_roots_flattened += 1;
    } catch (error) {
      result.errors.push(String(error && error.message ? error.message : error));
    }
  }
  if (hosts.length > maxHosts) {
    result.errors.push('shadow_host_limit_reached');
  }
  return result;
}
"""

_MUTATION_SETTLE_SCRIPT = """
({ quietWindowMs, timeoutMs }) => new Promise((resolve) => {
  const root = document.body || document.documentElement;
  if (!root) {
    resolve({ observed: false });
    return;
  }
  let settled = false;
  let quietTimer = null;
  let timeoutTimer = null;
  const finish = (observed) => {
    if (settled) {
      return;
    }
    settled = true;
    if (quietTimer !== null) {
      clearTimeout(quietTimer);
    }
    if (timeoutTimer !== null) {
      clearTimeout(timeoutTimer);
    }
    observer.disconnect();
    resolve({ observed });
  };
  const observer = new MutationObserver(() => {
    if (quietTimer !== null) {
      clearTimeout(quietTimer);
    }
    quietTimer = setTimeout(() => finish(true), quietWindowMs);
  });
  observer.observe(root, {
    attributes: true,
    characterData: true,
    childList: true,
    subtree: true,
  });
  quietTimer = setTimeout(() => finish(false), quietWindowMs);
  timeoutTimer = setTimeout(() => finish(false), timeoutMs);
});
"""


async def get_page_html(page, *, flatten_shadow: bool = True) -> str:
    if flatten_shadow:
        completeness = await flatten_shadow_dom(page)
        setattr(page, "_crawlerai_capture_completeness", completeness)
        if completeness.get("shadow_roots_flattened"):
            await wait_for_dom_mutation_settle(
                page,
                quiet_window_ms=100,
                timeout_ms=500,
            )
    retry_budget = max(
        0, int(crawler_runtime_settings.browser_error_retry_attempts or 0)
    )
    delay_ms = max(0, int(crawler_runtime_settings.browser_error_retry_delay_ms or 0))
    last_exc: Exception | None = None
    for attempt in range(retry_budget + 1):
        try:
            return await page.content()
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_page_content_error(exc):
                raise
            if attempt >= retry_budget:
                fallback_html = await _outer_html_fallback(page)
                if fallback_html.strip():
                    logger.warning(
                        "Recovered page HTML via DOM outerHTML fallback after Page.content failed: %s",
                        exc,
                    )
                    return fallback_html
                raise
            logger.warning(
                "Retrying Page.content after transient browser serialization failure (%s/%s): %s",
                attempt + 1,
                retry_budget + 1,
                exc,
            )
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
    # Defensive: retry loop above always returns recovered HTML or raises last_exc.
    if last_exc is not None:
        raise last_exc
    return ""


async def flatten_shadow_dom(page) -> dict[str, object]:
    max_hosts = int(
        getattr(crawler_runtime_settings, "shadow_dom_flatten_max_hosts", 100) or 0
    )
    version = "shadow-flatten.v2"
    result: dict[str, object] = {
        "max_hosts": max_hosts,
        "errors": (),
        "shadow_roots_detected": 0,
        "shadow_roots_flattened": 0,
        "closed_shadow_roots_detected": 0,
        "hidden_panel_dom_present": False,
        "serialization_method_version": version,
    }
    if max_hosts <= 0:
        return result
    try:
        raw = await page.evaluate(
            _SHADOW_DOM_FLATTENER_SCRIPT,
            {
                "maxHosts": max_hosts,
                "markerAttr": "data-crawlerai-shadow-host",
                "rootAttr": "data-crawlerai-shadow-root",
                "version": version,
            },
        )
    except Exception:
        logger.debug("Shadow DOM flattening failed", exc_info=True)
        return {**result, "errors": ("shadow_flatten_failed",)}
    if not isinstance(raw, dict):
        return result
    return {
        **result,
        "shadow_roots_detected": int(raw.get("shadow_roots_detected") or 0),
        "shadow_roots_flattened": int(raw.get("shadow_roots_flattened") or 0),
        "closed_shadow_roots_detected": int(
            raw.get("closed_shadow_roots_detected") or 0
        ),
        "hidden_panel_dom_present": bool(raw.get("hidden_panel_dom_present")),
        "max_hosts": int(raw.get("max_hosts") or max_hosts),
        "errors": tuple(str(item) for item in raw.get("errors") or ()),
        "serialization_method_version": str(
            raw.get("serialization_method_version") or version
        ),
    }


async def _outer_html_fallback(page) -> str:
    try:
        return str(
            await page.evaluate(
                """() => {
                  const root = document.documentElement;
                  const doctype = document.doctype
                    ? '<!DOCTYPE ' + document.doctype.name + '>'
                    : '';
                  if (root && root.outerHTML) {
                    return doctype + root.outerHTML;
                  }
                  const body = document.body;
                  if (!body || !body.outerHTML) {
                    return "";
                  }
                  return doctype + '<html><head></head>' + body.outerHTML + '</html>';
                }"""
            )
            or ""
        )
    except Exception:
        logger.debug("Page outerHTML fallback failed", exc_info=True)
        return ""


def _is_retryable_page_content_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    class_name = type(exc).__name__.lower()
    return (
        any(
            marker in message
            for marker in (
                "connection closed while reading from the driver",
                "unable to retrieve content because the page is navigating",
                "page is navigating and changing the content",
                "target closed",
                "page closed",
                "browser has been closed",
            )
        )
        or "targetclosed" in class_name
    )


async def wait_for_dom_mutation_settle(
    page,
    *,
    quiet_window_ms: int,
    timeout_ms: int,
) -> None:
    if quiet_window_ms <= 0 or timeout_ms <= 0:
        return
    try:
        await page.evaluate(
            _MUTATION_SETTLE_SCRIPT,
            {
                "quietWindowMs": int(quiet_window_ms),
                "timeoutMs": int(timeout_ms),
            },
        )
    except Exception:
        logger.debug("DOM mutation settle failed", exc_info=True)
