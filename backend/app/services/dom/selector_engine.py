"""Shared DOM field recovery, DOM text cleanup, and image/section normalization."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
import regex as regex_lib
from typing import cast
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree
from lxml import html as lxml_html
from soupsieve import SelectorSyntaxError

from app.services.config.extraction_rules import (
    CROSS_LINK_CONTAINER_HINTS,
    DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS,
    DETAIL_IMAGE_URL_ATTRS,
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
    DETAIL_TEXT_HIDDEN_STYLE_TOKENS,
    DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS,
    DETAIL_TEXT_SCOPE_PRIORITY_TOKENS,
    DETAIL_TEXT_SCOPE_SELECTORS,
    EXTRACTION_RULES,
    MAX_SELECTOR_MATCHES,
    VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS,
    VARIANT_OPTION_TEXT_FIELDS,
    SCOPE_PRODUCT_CONTEXT_TOKENS,
    SCOPE_SCORE_MAIN_WEIGHT,
    SCOPE_SCORE_PRIORITY_WEIGHT,
    SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.dom.image_extraction import (
    candidate_image_urls_from_node,  # noqa: F401 - public compatibility export
    canonical_image_url,  # noqa: F401 - public compatibility export
    dedupe_image_urls,  # noqa: F401 - public compatibility export
    extract_page_images as extract_page_images_impl,
    image_candidate_score,  # noqa: F401 - public compatibility export
    is_garbage_image_candidate,  # noqa: F401 - public compatibility export
    is_in_product_gallery_context,
    looks_like_image_asset_url,
    srcset_urls,
    upgrade_low_resolution_image_url,  # noqa: F401 - public compatibility export
)
from app.services.dom.section_extraction import (
    extract_feature_rows,  # noqa: F401 - public compatibility export
    extract_heading_sections,
    extract_label_value_pairs,
    section_text_is_meaningful,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.field_mappings import ADDITIONAL_IMAGES_FIELD
from app.services.dom.content_extractability import (
    requested_content_extractability_impl,
)
from app.services.extraction_html_helpers import html_to_text
from app.services.field_policy import (
    normalize_field_key,
    normalize_requested_field,
)
from app.services.extract.field_candidates import add_candidate
from app.services.shared.field_coerce import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    URL_FIELDS,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_urls,
    surface_alias_lookup,
    surface_fields,
)
from app.services.shared.coerce_primitives import safe_int as _safe_int
from app.services.dom.xpath_service import validate_xpath_syntax

logger = logging.getLogger(__name__)


_cross_product_container_tokens = tuple(
    clean_text(token).lower()
    for token in tuple(DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS or ())
    if clean_text(token)
)
_scope_product_context_tokens = tuple(
    clean_text(token).lower()
    for token in tuple(SCOPE_PRODUCT_CONTEXT_TOKENS or ())
    if clean_text(token)
)
_max_selector_matches = _safe_int(MAX_SELECTOR_MATCHES, default=12) or 12
_scope_score_main_weight = _safe_int(SCOPE_SCORE_MAIN_WEIGHT, default=4000) or 4000
_scope_score_priority_weight = (
    _safe_int(SCOPE_SCORE_PRIORITY_WEIGHT, default=2000) or 2000
)
_scope_score_product_context_weight = (
    _safe_int(SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT, default=1000) or 1000
)


def _compile_variant_option_child_drop_patterns() -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in tuple(VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS or ()):
        if not str(pattern).strip():
            continue
        try:
            compiled.append(re.compile(str(pattern), re.I))
        except re.error:
            logger.warning(
                "Skipping invalid variant option child-drop pattern: %r", pattern
            )
    return tuple(compiled)


_VARIANT_OPTION_CHILD_DROP_RE = _compile_variant_option_child_drop_patterns()

_candidate_cleanup_raw = EXTRACTION_RULES.get("candidate_cleanup")
_CANDIDATE_CLEANUP = (
    dict(_candidate_cleanup_raw) if isinstance(_candidate_cleanup_raw, dict) else {}
)
_PAGE_FILE_EXTENSIONS = (".asp", ".aspx", ".htm", ".html", ".jsp", ".php")


def _selector_regex_timeout_seconds() -> float | None:
    try:
        timeout = float(crawler_runtime_settings.selector_regex_timeout_seconds)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid selector_regex_timeout_seconds=%r; disabling selector regex timeout",
            crawler_runtime_settings.selector_regex_timeout_seconds,
        )
        return None
    return timeout if timeout > 0 else None


_detail_text_scope_selectors = tuple(
    selector
    for selector in tuple(DETAIL_TEXT_SCOPE_SELECTORS or ())
    if str(selector).strip()
)
_detail_text_scope_priority_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_SCOPE_PRIORITY_TOKENS or ())
    if str(token).strip()
)
_detail_text_scope_exclude_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS or ())
    if str(token).strip()
)
_detail_text_hidden_style_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_HIDDEN_STYLE_TOKENS or ())
    if str(token).strip()
)


def _node_attr_text(node: Tag, *, max_depth: int = 6) -> str:
    parts: list[str] = []
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < max_depth:
        for attr_name in (
            "id",
            "class",
            "data-component",
            "data-qa",
            "data-section",
            "data-section-id",
            "data-section-type",
            "data-testid",
            "aria-label",
        ):
            value = current.get(attr_name)
            if isinstance(value, list):
                parts.extend(str(item) for item in value if item)
            elif value not in (None, "", [], {}):
                parts.append(str(value))
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1
    return " ".join(parts).lower()


def _field_uses_scoped_text(field_name: str) -> bool:
    return field_name in DETAIL_LONG_TEXT_RANK_FIELDS


def _node_within_scope(node: Tag, scope: Tag) -> bool:
    current: Tag | None = node
    while isinstance(current, Tag):
        if current is scope:
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def _node_style_is_hidden(node: Tag) -> bool:
    style = str(node.get("style") or "").strip().lower()
    return bool(style) and any(
        token in style for token in _detail_text_hidden_style_tokens
    )


def _node_is_hidden_or_auxiliary(node: Tag) -> bool:
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < 8:
        attrs = getattr(current, "attrs", None)
        if not isinstance(attrs, dict):
            parent = current.parent
            current = parent if isinstance(parent, Tag) else None
            depth += 1
            continue
        if "hidden" in attrs:
            return True
        if str(attrs.get("aria-hidden") or "").strip().lower() == "true":
            return True
        if str(attrs.get("aria-modal") or "").strip().lower() == "true":
            return True
        role = str(attrs.get("role") or "").strip().lower()
        if role in {"dialog", "alertdialog"}:
            return True
        if _node_style_is_hidden(current):
            return True
        context = _node_attr_text(current, max_depth=1)
        if any(token in context for token in _detail_text_scope_exclude_tokens):
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
        depth += 1
    return False


def _node_has_cross_product_cluster(node: Tag, *, page_url: str = "") -> bool:
    if not isinstance(getattr(node, "attrs", None), dict):
        return False
    links: list[str] = []
    for link in node.select("a[href]")[:_max_selector_matches]:
        link_text = clean_text(link.get_text(" ", strip=True) or link.get("aria-label"))
        if not link_text:
            continue
        resolved = absolute_url(page_url, str(link.get("href") or ""))
        if resolved:
            links.append(resolved)
    product_links = [
        link
        for link in links
        if any(
            marker in urlparse(link).path.lower()
            for marker in detail_path_hints("ecommerce_detail")
        )
    ]
    if len(set(product_links)) >= 2:
        return True
    context = _node_attr_text(node, max_depth=1)
    return any(token in context for token in _cross_product_container_tokens)


def _candidate_text_scope_nodes(root: BeautifulSoup | Tag) -> list[Tag]:
    candidates: list[Tag] = []
    seen: set[int] = set()
    for selector in _detail_text_scope_selectors:
        for node in safe_select(root, selector):
            if id(node) in seen or _node_is_hidden_or_auxiliary(node):
                continue
            seen.add(id(node))
            candidates.append(node)
    return candidates


def _scope_score(node: Tag) -> tuple[int, int]:
    context = _node_attr_text(node, max_depth=2)
    text_len = len(clean_text(node.get_text(" ", strip=True)))
    score = text_len
    if (
        node.name in {"main", "article"}
        or str(node.get("role") or "").strip().lower() == "main"
    ):
        score += _scope_score_main_weight
    if any(token in context for token in _detail_text_scope_priority_tokens):
        score += _scope_score_priority_weight
    if DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR and (
        node.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) is not None
        or any(token in context for token in _scope_product_context_tokens)
    ):
        score += _scope_score_product_context_weight
    return score, text_len


def _scope_is_product_like(node: Tag) -> bool:
    context = _node_attr_text(node, max_depth=2)
    if any(token in context for token in _scope_product_context_tokens):
        return True
    return bool(
        DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR
        and node.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) is not None
    )


def _best_text_scope(root: BeautifulSoup | Tag) -> Tag | None:
    candidates = _candidate_text_scope_nodes(root)
    if not candidates:
        return None
    best = max(candidates, key=_scope_score)
    return best if _scope_is_product_like(best) else None


def _clone_visible_only(
    node: Tag | NavigableString,
    *,
    remaining_depth: int = 50,
    _soup: BeautifulSoup | None = None,
) -> Tag | NavigableString | None:
    if remaining_depth <= 0:
        return None
    if not isinstance(node, Tag):
        return NavigableString(str(node)) if isinstance(node, NavigableString) else None
    if _node_is_hidden_or_auxiliary(node):
        return None
    _soup = _soup or BeautifulSoup("", "html.parser")
    clone = _soup.new_tag(node.name, attrs=dict(getattr(node, "attrs", {}) or {}))
    for child in node.children:
        if (
            child_clone := _clone_visible_only(
                cast(Tag | NavigableString, child),
                remaining_depth=remaining_depth - 1,
                _soup=_soup,
            )
        ) is not None:
            clone.append(child_clone)
    return clone


def _pruned_text_scope_root(root: BeautifulSoup | Tag) -> BeautifulSoup | Tag:
    scope = _best_text_scope(root)
    if scope is None:
        return root
    cloned_scope = _clone_visible_only(scope)
    return cloned_scope if isinstance(cloned_scope, Tag) else root


def _is_other_detail_link(
    url: str,
    page_url: str,
    *,
    surface: str | None = None,
    link_node: Tag | None = None,
) -> bool:
    candidate = clean_text(url)
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith(
        ("#", "javascript:", "mailto:")
    ) or looks_like_image_asset_url(candidate):
        return False
    page_parts = urlparse(page_url)
    candidate_parts = urlparse(candidate)
    same_host = (page_parts.hostname or "").lower() == (
        candidate_parts.hostname or ""
    ).lower()
    same_path = (page_parts.path.rstrip("/") or "/") == (
        candidate_parts.path.rstrip("/") or "/"
    )
    if same_host and same_path:
        return False
    is_detail_surface = "detail" in str(surface or "").lower()
    if (
        is_detail_surface
        and link_node is not None
        and is_in_product_gallery_context(link_node)
    ):
        return False
    path = (candidate_parts.path or "").lower()
    if any(path.endswith(ext) for ext in _PAGE_FILE_EXTENSIONS):
        return True
    if any(marker in path for marker in detail_path_hints(surface)):
        return True
    if is_detail_surface and same_host and not same_path:
        return True
    if link_node is not None and _is_in_cross_link_container(link_node):
        return True
    return False


def _is_in_cross_link_container(node: Tag, *, max_depth: int = 6) -> bool:
    current: Tag | None = node
    depth = 0
    while isinstance(current, Tag) and depth < max_depth:
        context = _node_attr_text(current)
        if any(hint in context for hint in CROSS_LINK_CONTAINER_HINTS):
            return True
        current = current.parent
        depth += 1
    return False


def safe_select(root: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except SelectorSyntaxError:
        logger.warning("Skipping invalid css selector: %s", selector)
        return []


def extract_node_value(node: Tag, field_name: str, page_url: str) -> object | None:
    if field_name in IMAGE_FIELDS:
        srcset = node.get("srcset")
        image_candidates: object = (
            srcset_urls(srcset)
            if srcset not in (None, "", [], {})
            else (
                node.get("content")
                or next(
                    (
                        node.get(str(attr_name))
                        for attr_name in tuple(DETAIL_IMAGE_URL_ATTRS or ())
                        if node.get(str(attr_name)) not in (None, "", [], {})
                    ),
                    None,
                )
                or node.get("href")
                or ""
            )
        )
        urls = extract_urls(
            image_candidates,
            page_url,
        )
        if (
            node.name not in {"img", "source"}
            and str(node.get("as") or "").lower() != "image"
        ):
            urls = [url for url in urls if looks_like_image_asset_url(url)]
        if field_name == ADDITIONAL_IMAGES_FIELD:
            return urls or None
        return urls[0] if urls else None
    if field_name in URL_FIELDS:
        urls = extract_urls(
            node.get("href") or node.get("content") or node.get("data-apply-url") or "",
            page_url,
        )
        return urls[0] if urls else None
    if node.name == "meta":
        return coerce_field_value(field_name, node.get("content"), page_url)
    for attr_name in (
        "content",
        "value",
        "datetime",
        "data-value",
        "data-price",
        "data-availability",
    ):
        attr_value = node.get(attr_name)
        if attr_value not in (None, "", [], {}):
            return coerce_field_value(field_name, attr_value, page_url)
    raw_text = (
        _variant_option_node_text(node, field_name)
        if _looks_like_variant_option_node(node, field_name)
        else (
            html_to_text(
                str(_clone_visible_only(node) or node), preserve_block_breaks=True
            )
            if _field_uses_scoped_text(field_name)
            else (_clone_visible_only(node) or node).get_text(" ", strip=True)
        )
    )
    text_value = coerce_field_value(field_name, raw_text, page_url)
    if field_name in LONG_TEXT_FIELDS and not section_text_is_meaningful(
        node,
        label=field_name,
        text=str(text_value or ""),
    ):
        return None
    return text_value


def _looks_like_variant_option_node(node: Tag, field_name: str) -> bool:
    if field_name not in VARIANT_OPTION_TEXT_FIELDS:
        return False
    if node.name in {"option", "button"}:
        return True
    role = str(node.get("role") or "").strip().lower()
    if role in {"option", "radio", "button", "tab"}:
        return True
    context = " ".join(
        _attribute_text(value)
        for value in (
            node.get("class"),
            node.get("aria-label"),
            node.get("data-testid"),
            node.get("data-test"),
            node.get("data-qa"),
            node.get("name"),
        )
    ).lower()
    return any(
        token in context for token in ("option", "swatch", "variant", field_name)
    )


def _attribute_text(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item or "") for item in value)
    return str(value or "")


def _variant_option_node_text(node: Tag, _field_name: str) -> str:
    if not node.find(True):
        return node.get_text(" ", strip=True)
    pruned = deepcopy(node)
    for child in list(pruned.find_all(True)):
        text = clean_text(child.get_text(" ", strip=True))
        if text and any(
            pattern.search(text) for pattern in _VARIANT_OPTION_CHILD_DROP_RE
        ):
            child.decompose()
    return pruned.get_text(" ", strip=True)


def extract_selector_values(
    root: BeautifulSoup | Tag,
    selector: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    values: list[object] = []
    scoped_text_root = (
        _best_text_scope(root) if _field_uses_scoped_text(field_name) else None
    )
    for node in safe_select(root, selector)[:_max_selector_matches]:
        if _field_uses_scoped_text(field_name):
            if _node_is_hidden_or_auxiliary(node):
                continue
            if scoped_text_root is not None and not _node_within_scope(
                node, scoped_text_root
            ):
                continue
        value = extract_node_value(node, field_name, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_xpath_values(
    root: BeautifulSoup | Tag,
    xpath: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    valid_xpath, _ = validate_xpath_syntax(xpath)
    if not valid_xpath:
        logger.warning("Skipping invalid xpath selector for %s: %s", field_name, xpath)
        return []
    try:
        tree = lxml_html.fromstring(str(root))
    except (etree.ParserError, ValueError):
        return []
    try:
        matches = tree.xpath(xpath)
    except etree.XPathError:
        logger.warning(
            "Failed to evaluate xpath selector for %s: %s", field_name, xpath
        )
        return []
    values: list[object] = []
    limited_matches: list[object]
    if isinstance(matches, list):
        limited_matches = [*matches[:_max_selector_matches]]
    elif isinstance(matches, (str, bytes, bool, float)):
        limited_matches = [matches]
    else:
        try:
            limited_matches = list(matches)[:_max_selector_matches]
        except TypeError:
            limited_matches = [matches]
    for match in limited_matches:
        if isinstance(match, lxml_html.HtmlElement):
            raw_value = match.text_content()
        elif isinstance(match, etree._Element):
            raw_value = " ".join(str(part) for part in match.itertext())
        else:
            raw_value = str(match)
        value = coerce_field_value(field_name, raw_value, page_url)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


def extract_regex_values(
    root: BeautifulSoup | Tag,
    pattern: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    html_text = str(root)
    values: list[object] = []
    timeout = _selector_regex_timeout_seconds()
    try:
        matches = regex_lib.finditer(
            pattern,
            html_text,
            regex_lib.DOTALL,
            timeout=timeout,
        )
        for match in matches:
            raw_value = next((group for group in match.groups() if group), None)
            if raw_value is None:
                raw_value = match.group(0)
            value = coerce_field_value(field_name, raw_value, page_url)
            if value in (None, "", [], {}):
                continue
            values.append(value)
            if len(values) >= 12:
                break
    except TimeoutError:
        logger.warning("Timed out while evaluating selector regex for %s", field_name)
    except regex_lib.error:
        logger.warning("Failed to evaluate selector regex for %s", field_name)
    return values


def filter_values_by_regex(
    values: list[object],
    pattern: str,
    field_name: str,
    page_url: str,
) -> list[object]:
    filtered: list[object] = []
    timeout = _selector_regex_timeout_seconds()
    try:
        for candidate in values:
            match = regex_lib.search(
                pattern,
                str(candidate),
                regex_lib.DOTALL,
                timeout=timeout,
            )
            if not match:
                continue
            raw_value = next((group for group in match.groups() if group), None)
            if raw_value is None:
                raw_value = match.group(0)
            value = coerce_field_value(field_name, raw_value, page_url)
            if value in (None, "", [], {}):
                continue
            filtered.append(value)
            if len(filtered) >= 12:
                break
    except TimeoutError:
        logger.warning("Timed out while evaluating selector regex for %s", field_name)
    except regex_lib.error:
        logger.warning("Failed to evaluate selector regex for %s", field_name)
    return filtered


def extract_page_images(
    root: BeautifulSoup | Tag,
    page_url: str,
    *,
    exclude_linked_detail_images: bool = False,
    surface: str | None = None,
) -> list[str]:
    return extract_page_images_impl(
        root,
        page_url,
        exclude_linked_detail_images=exclude_linked_detail_images,
        surface=surface,
        other_detail_link_checker=_is_other_detail_link,
    )


def requested_content_extractability(
    root: BeautifulSoup | Tag,
    *,
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None = None,
    probe_fields: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, object]:
    return requested_content_extractability_impl(
        root,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
        probe_fields=probe_fields,
        extract_heading_sections=extract_heading_sections,  # type: ignore[arg-type]
        safe_select=safe_select,
        max_selector_matches=_max_selector_matches,
    )


def apply_selector_fallbacks(
    root: BeautifulSoup | Tag,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    selector_rules: list[dict[str, object]] | None = None,
    *,
    candidate_sources: dict[str, list[str]] | None = None,
    field_sources: dict[str, list[str]] | None = None,
    selector_trace_candidates: dict[str, list[dict[str, object]]] | None = None,
) -> None:
    def _add(field_name: str, value: object, source: str) -> None:
        growth = add_candidate(candidates, field_name, value)
        if growth <= 0:
            return
        if candidate_sources is not None:
            candidate_sources.setdefault(field_name, []).extend([source] * growth)
        if field_sources is not None:
            bucket = field_sources.setdefault(field_name, [])
            public_source = "dom_selector" if source == "selector_rule" else source
            if public_source not in bucket:
                bucket.append(public_source)

    def _record_selector_trace(
        field_name: str,
        value: object,
        row: dict[str, object],
        *,
        selector_kind: str,
        selector_value: str,
    ) -> None:
        if selector_trace_candidates is None:
            return
        selector_trace_candidates.setdefault(field_name, []).append(
            {
                "selector_kind": selector_kind,
                "selector_value": selector_value,
                "selector_source": str(row.get("source") or "domain_memory").strip(),
                "selector_record_id": row.get("id"),
                "source_run_id": row.get("source_run_id"),
                "sample_value": str(value),
                "page_url": page_url,
                "_candidate_value": value,
            }
        )

    fields = surface_fields(surface, requested_fields)
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    selector_hit_fields: set[str] = set()
    for row in list(selector_rules or []):
        if not isinstance(row, dict):
            continue
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        if field_name not in fields or not bool(row.get("is_active", True)):
            continue
        xpath = str(row.get("xpath") or "").strip()
        css_selector = str(row.get("css_selector") or "").strip()
        regex = str(row.get("regex") or "").strip()
        values: list[object] = []
        selector_kind = ""
        selector_value = ""
        if xpath:
            values = extract_xpath_values(root, xpath, field_name, page_url)
            selector_kind = "xpath"
            selector_value = xpath
        if not values and css_selector:
            values = extract_selector_values(root, css_selector, field_name, page_url)
            selector_kind = "css_selector"
            selector_value = css_selector
        if values and regex:
            values = filter_values_by_regex(values, regex, field_name, page_url)
        elif not values and regex and not xpath and not css_selector:
            values = extract_regex_values(root, regex, field_name, page_url)
            selector_kind = "regex"
            selector_value = regex
        for value in values:
            _add(field_name, value, "selector_rule")
            if selector_kind and selector_value:
                _record_selector_trace(
                    field_name,
                    value,
                    row,
                    selector_kind=selector_kind,
                    selector_value=selector_value,
                )
        if values:
            selector_hit_fields.add(field_name)
    dom_patterns_raw = EXTRACTION_RULES.get("dom_patterns")
    dom_patterns = dict(dom_patterns_raw) if isinstance(dom_patterns_raw, dict) else {}
    for field_name in fields:
        if field_name in selector_hit_fields:
            continue
        selector = str(dom_patterns.get(field_name) or "").strip()
        if not selector:
            continue
        for value in extract_selector_values(root, selector, field_name, page_url):
            _add(field_name, value, "dom_selector")
    for label, value in extract_label_value_pairs(root):
        normalized_label = normalize_field_key(label)
        canonical = alias_lookup.get(normalized_label)
        if not canonical:
            canonical = alias_lookup.get(normalize_requested_field(label))
        if canonical:
            _add(
                canonical,
                coerce_field_value(canonical, value, page_url),
                "dom_selector",
            )
