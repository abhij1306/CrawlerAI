"""Static HTML extractability and shell signals for browser acquisition."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import logging
import re
from typing import Any

from app.core.config.extraction_rules import (
    ACTION_BUY_NOW,
    BROWSER_DETAIL_READINESS_HINTS,
    CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH,
    CONTENT_SURFACE_FORUM_BODY_SELECTORS,
    CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS,
    DETAIL_SHELL_FRAMEWORK_TOKENS,
    DETAIL_SHELL_PRODUCT_DATA_TOKENS,
    DETAIL_SHELL_STATE_TOKENS,
    JS_REQUIRED_PLACEHOLDER_PHRASES,
    LISTING_CLIENT_RENDERED_SHELL_HINTS,
    LISTING_DETAIL_URL_MARKERS,
    LISTING_SHELL_FRAMEWORK_TOKENS,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.shared.field_coerce import clean_text
from app.extraction.documents import HtmlAnalysis, HtmlDocument

logger = logging.getLogger(__name__)

STRUCTURED_SHELL_TOKENS = (
    "application/ld+json",
    "__next_data__",
    "__nuxt__",
    "shopifyanalytics.meta",
)
_DETAIL_READINESS_HINTS: dict[str, tuple[str, ...]] = {
    str(key): tuple(map(str, value or ()))
    for key, value in (BROWSER_DETAIL_READINESS_HINTS or {}).items()
}


@dataclass(frozen=True, slots=True)
class ExtractableContentSignals:
    detail: bool
    listing: bool
    meaningful_detail: bool
    js_shell: bool
    listing_shell: bool


def analyze_html(html: str) -> HtmlAnalysis:
    return HtmlAnalysis.from_html(html)


def analyze_extractable_content(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
    url: str = "",
    status_code: int = 0,
) -> ExtractableContentSignals:
    parsed = analysis or analyze_html(html)
    placeholder = _is_js_required_placeholder(parsed)
    structured_detail, structured_listing, typed_count, state_content = (
        _structured_content_signals(parsed.document)
    )
    meaningful_detail = _has_meaningful_detail_dom(parsed)
    detail = _detail_content_present(
        parsed,
        placeholder=placeholder,
        structured_detail=structured_detail,
        state_content=state_content,
        dom_detail=_has_detail_dom_signals(parsed),
        meaningful_detail=meaningful_detail,
    )
    listing = _listing_content_present(
        parsed,
        placeholder=placeholder,
        structured_listing=structured_listing,
        typed_count=typed_count,
    )
    js_shell, listing_shell = _shell_content_signals(
        parsed, placeholder=placeholder, url=url, status_code=status_code
    )
    return ExtractableContentSignals(
        detail=detail,
        listing=listing,
        meaningful_detail=meaningful_detail,
        js_shell=js_shell,
        listing_shell=listing_shell,
    )


def _detail_content_present(
    analysis: HtmlAnalysis,
    *,
    placeholder: bool,
    structured_detail: bool,
    state_content: bool,
    dom_detail: bool,
    meaningful_detail: bool,
) -> bool:
    text = analysis.normalized_text.lower()
    token_detail = any(
        (
            _contains_any(analysis.lowered_html, DETAIL_SHELL_STATE_TOKENS),
            all(
                (
                    _contains_any(analysis.lowered_html, DETAIL_SHELL_FRAMEWORK_TOKENS),
                    _contains_any(
                        analysis.lowered_html, DETAIL_SHELL_PRODUCT_DATA_TOKENS
                    ),
                )
            ),
        )
    )
    evidence = any(
        (
            structured_detail,
            state_content,
            dom_detail,
            meaningful_detail,
            all(
                (
                    token_detail,
                    not _contains_any(text, ("load in the app", "loads in the app")),
                )
            ),
        )
    )
    return all((bool(analysis.html), not placeholder, evidence))


def _listing_content_present(
    analysis: HtmlAnalysis,
    *,
    placeholder: bool,
    structured_listing: bool,
    typed_count: int,
) -> bool:
    enough_typed = typed_count >= max(
        2, int(crawler_runtime_settings.listing_min_items)
    )
    evidence = any(
        (
            structured_listing,
            enough_typed,
            _detail_like_anchor_count(analysis.document) >= 3,
        )
    )
    return all((bool(analysis.html), not placeholder, evidence))


def _shell_content_signals(
    analysis: HtmlAnalysis, *, placeholder: bool, url: str, status_code: int
) -> tuple[bool, bool]:
    root_present = any(
        re.search(r"root|app|__next", node.attribute("id") or "", re.I)
        for node in analysis.document.safe_css("[id]")
    )
    script_count = len(analysis.document.safe_css("script"))
    js_shell = any(
        (
            placeholder,
            all((len(analysis.visible_text) <= 120, root_present, script_count >= 3)),
        )
    )
    listing_shell = any(
        (
            placeholder,
            "#/" in str(url or "").strip().lower(),
            int(status_code or 0) == 202,
        )
    )
    tokens: Iterable[str] = ()
    if len(analysis.visible_text) > 400:
        tokens = LISTING_CLIENT_RENDERED_SHELL_HINTS
    elif root_present or script_count >= 3:
        tokens = LISTING_SHELL_FRAMEWORK_TOKENS
    if not listing_shell:
        listing_shell = _contains_any(analysis.lowered_html, tokens)
    return js_shell, listing_shell


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    return any(token in text for token in tokens)


def _structured_content_signals(
    document: HtmlDocument,
) -> tuple[bool, bool, int, bool]:
    detail = listing = state_content = False
    typed_count = 0
    for script in document.safe_css('script[type*="ld+json"]'):
        payload = script.json()
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_type = row.get("@type")
            normalized = (
                " ".join(map(str, raw_type))
                if isinstance(raw_type, list)
                else str(raw_type or "")
            ).lower()
            detail |= any(
                token in normalized
                for token in ("product", "productgroup", "jobposting")
            )
            listing |= any(token in normalized for token in ("itemlist", "listitem"))
            typed_count += int(
                any(token in normalized for token in ("product", "jobposting"))
            )
    for script in document.safe_css(
        'script[type="application/json"], script#__NEXT_DATA__',
    ):
        state_content |= _state_payload_has_content(script.json())
    return detail, listing, typed_count, state_content


def _state_payload_has_content(payload: Any) -> bool:
    if isinstance(payload, dict):
        meaningful = any(
            value not in (None, "", [], {})
            and str(key or "").strip().lower() not in {"config", "env", "locale"}
            for key, value in payload.items()
        )
        return meaningful or any(
            _state_payload_has_content(value) for value in payload.values()
        )
    if isinstance(payload, list):
        return any(_state_payload_has_content(item) for item in payload[:10])
    return payload not in (None, "")


def _has_detail_dom_signals(analysis: HtmlAnalysis) -> bool:
    if not analysis.h1_present:
        return False
    lowered_text = analysis.normalized_text.lower()
    hint_count = detail_readiness_hint_count("ecommerce_detail", lowered_text)
    hint_count += int(ACTION_BUY_NOW.strip().lower() in lowered_text)
    product_anchor = any(
        all(
            (
                re.search(r"og:type", node.attribute("property") or "", re.I),
                re.search(r"\bproduct\b", node.attribute("content") or "", re.I),
            )
        )
        for node in analysis.document.safe_css("[property][content]")
    )
    price_pattern = re.compile(
        r"(?:[$€£₹]\s*)?\d{1,3}(?:,\d{3})*(?:[.,]\d{1,2})?"
        r"|(?:[$€£₹]\s*)?\d+(?:[.,]\d{1,2})?",
        re.I,
    )
    price_anchor = bool(
        any(
            all(
                (
                    re.search(
                        r"(?:product:)?price",
                        node.attribute("property") or "",
                        re.I,
                    ),
                    price_pattern.search(node.attribute("content") or ""),
                )
            )
            for node in analysis.document.safe_css("[property][content]")
        )
        or any(
            re.search(r"price", node.attribute("itemprop") or "", re.I)
            for node in analysis.document.safe_css("[itemprop]")
        )
        or re.search(
            r"(?:[$€£₹]\s*)\d+(?:[.,]\d{2})?",
            analysis.normalized_text,
        )
    )
    app_only = any(
        phrase in lowered_text for phrase in ("load in the app", "loads in the app")
    )
    if all((app_only, not any((product_anchor, price_anchor)))):
        return False
    if hint_count >= int(crawler_runtime_settings.detail_field_signal_min_count):
        return bool(
            any(
                (
                    analysis.document.css_first(
                        "main h1, article h1, [role='main'] h1"
                    ),
                    product_anchor,
                    price_anchor,
                )
            )
        )
    return all((hint_count > 0, product_anchor))


def _has_meaningful_detail_dom(analysis: HtmlAnalysis) -> bool:
    heading = analysis.document.css_first("main h1, article h1, [role='main'] h1, h1")
    heading_text = clean_text(heading.text()) if heading else ""
    if not heading_text:
        return False
    selectors = (
        *CONTENT_SURFACE_FORUM_BODY_SELECTORS,
        *CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS,
    )
    for selector in selectors:
        try:
            nodes = analysis.document.css(selector)
        except Exception:
            logger.debug(
                "Protected-descendant probe failed for selector %r; skipping it",
                selector,
                exc_info=True,
            )
            nodes = ()
        for node in nodes:
            body = clean_text(
                re.sub(
                    re.escape(heading_text),
                    " ",
                    clean_text(node.text()),
                    flags=re.I,
                )
            )
            if not body or any(
                phrase in body.lower()
                for phrase in ("load in the app", "loads in the app")
            ):
                continue
            descendants = node.css_first("p, div, li, article, section, span")
            if (
                descendants is not None
                or len(body) >= CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH
            ):
                return True
    return False


def _is_js_required_placeholder(analysis: HtmlAnalysis) -> bool:
    combined = clean_text(f"{analysis.title_text} {analysis.visible_text}").lower()
    return bool(
        combined
        and any(phrase in combined for phrase in JS_REQUIRED_PLACEHOLDER_PHRASES)
        and (
            analysis.document.css_first("noscript") is not None
            or len(analysis.visible_text) <= 400
        )
    )


def _detail_like_anchor_count(document: HtmlDocument) -> int:
    return sum(
        any(
            marker in (anchor.attribute("href") or "").lower()
            for marker in LISTING_DETAIL_URL_MARKERS
        )
        for anchor in document.safe_css("a[href]")
    )


def detail_readiness_hint_count(surface: str, visible_text: str) -> int:
    lowered_surface = str(surface or "").strip().lower()
    if "ecommerce" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS.get("ecommerce", ())
    elif "job" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS.get("job", ())
    else:
        hints = ()
    return sum(1 for hint in hints if hint in visible_text)


__all__ = [
    "STRUCTURED_SHELL_TOKENS",
    "ExtractableContentSignals",
    "analyze_extractable_content",
    "analyze_html",
    "detail_readiness_hint_count",
]
