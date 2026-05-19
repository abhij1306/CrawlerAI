"""DOM label/value, semantic section, and feature-row extraction."""

from __future__ import annotations

import re
from typing import cast

from bs4 import BeautifulSoup, NavigableString, Tag
from soupsieve import SelectorSyntaxError

from app.services.config.extraction_rules import (
    DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS,
    DETAIL_LONG_TEXT_MAX_SECTION_CHARS,
    DETAIL_TEXT_HIDDEN_STYLE_TOKENS,
    FEATURE_SECTION_ALIASES,
    FEATURE_SECTION_SELECTORS,
    SEMANTIC_SECTION_LABEL_SKIP_TOKENS,
    SEMANTIC_SECTION_NOISE,
)
from app.services.extraction_html_helpers import html_to_text
from app.services.field_policy import normalize_field_key
from app.services.shared.coerce_primitives import safe_int as _safe_int
from app.services.shared.field_coerce import clean_text

_max_section_blocks = _safe_int(DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS, default=8) or 8
_max_section_chars = _safe_int(DETAIL_LONG_TEXT_MAX_SECTION_CHARS, default=1200) or 1200
_SECTION_SKIP_PATTERNS = tuple(
    str(token).lower() for token in (SEMANTIC_SECTION_NOISE.get("skip_patterns") or ())
)
_detail_text_hidden_style_tokens = tuple(
    str(token).lower()
    for token in tuple(DETAIL_TEXT_HIDDEN_STYLE_TOKENS or ())
    if str(token).strip()
)
_FEATURE_SECTION_ALIASES = frozenset(
    normalize_field_key(str(value))
    for value in tuple(FEATURE_SECTION_ALIASES or ())
    if str(value).strip()
)
_feature_section_selector = ", ".join(
    str(s) for s in tuple(FEATURE_SECTION_SELECTORS or ()) if str(s).strip()
)
_SECTION_LABEL_SELECTOR = ",".join(
    [
        "summary",
        "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",
        "[data-tab-heading]",
        "button",
        "[role='button']",
        "[role='tab']",
        "h2",
        "h3",
        "h4",
        "h5",
        "strong",
    ]
)
_SECTION_CONTAINER_SELECTORS = (
    "[data-accordion-content]",
    "[data-collapse-content]",
    "[data-content]",
    "[data-details-content]",
    "[data-tab-content]",
    "[role='tabpanel']",
    "[aria-labelledby]",
    ".accordion__answer",
    ".accordion-content",
    ".accordion-panel",
    ".accordion-body",
    ".tabs__content",
    ".tab-content",
    ".tab-panel",
    ".panel",
    "[class*='accordion' i]",
    "[class*='content' i]",
    "[class*='details' i]",
    "[class*='description' i]",
    "[class*='spec' i]",
)
_SECTION_STOP_TAGS = {"h1", "h2", "h3", "h4", "h5", "summary"}
_MATERIAL_TEXT_HINTS = (
    "acrylic",
    "cashmere",
    "composition",
    "cotton",
    "elastane",
    "fabric",
    "leather",
    "linen",
    "material",
    "nylon",
    "polyester",
    "rayon",
    "shell",
    "silk",
    "spandex",
    "suede",
    "trim",
    "viscose",
    "wool",
)


def extract_label_value_pairs(root: BeautifulSoup | Tag) -> list[tuple[str, str]]:
    def node_text(node: BeautifulSoup | Tag) -> str:
        return clean_text(node.get_text(" ", strip=True))

    rows: list[tuple[str, str]] = []
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = node_text(cells[0])
        value = node_text(cells[1])
        if label and value:
            rows.append((label, value))
    for dt in root.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = node_text(dt)
        value = node_text(dd)
        if label and value:
            rows.append((label, value))
    for node in root.find_all(["li", "p", "div", "span"]):
        text = node_text(node)
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        label = clean_text(label)
        value = clean_text(value)
        if not label or not value:
            continue
        if len(label) > 40 or len(value) > 250:
            continue
        rows.append((label, value))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in rows:
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, value))
    return deduped


def extract_heading_sections(
    root: BeautifulSoup | Tag,
    *,
    alias_lookup: dict[str, str] | None = None,
    allowed_fields: set[str] | None = None,
) -> dict[str, str]:
    scoped_root = _pruned_text_scope_root(root)
    sections: dict[str, str] = {}
    seen: set[int] = set()
    normalized_allowed_fields = {
        normalize_field_key(field_name)
        for field_name in allowed_fields or ()
        if normalize_field_key(field_name)
    }
    for heading in _safe_select(scoped_root, _SECTION_LABEL_SELECTOR):
        if id(heading) in seen:
            continue
        seen.add(id(heading))
        heading_text = section_label_text(heading)
        if not _is_section_label(heading_text):
            continue
        if normalized_allowed_fields and alias_lookup is not None:
            canonical_field = alias_lookup.get(normalize_field_key(heading_text))
            if canonical_field not in normalized_allowed_fields:
                continue
        content = extract_section_content(heading, scoped_root)
        if len(content) >= 12:
            sections.setdefault(heading_text, content)
    materials = _extract_product_materials(scoped_root) or _extract_product_materials(
        root
    )
    if materials and (
        not normalized_allowed_fields
        or alias_lookup is None
        or alias_lookup.get(normalize_field_key("Composition"))
        in normalized_allowed_fields
    ):
        sections.setdefault("Composition", materials)
    return sections


def extract_feature_rows(root: BeautifulSoup | Tag) -> list[str]:
    scoped_root = _pruned_text_scope_root(root)
    rows: list[str] = []
    seen: set[str] = set()

    def _add(values: list[str]) -> None:
        for value in values:
            cleaned = clean_text(value)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            rows.append(cleaned)

    for node in _safe_select(scoped_root, _feature_section_selector):
        if _node_is_hidden_or_auxiliary(node):
            continue
        _add(_feature_rows_from_node(node))

    for heading in _safe_select(scoped_root, _SECTION_LABEL_SELECTOR):
        label = normalize_field_key(section_label_text(heading))
        if label not in _FEATURE_SECTION_ALIASES:
            continue
        content = extract_section_content(heading, scoped_root)
        _add(_split_feature_text(content))
    return rows


def _safe_select(root: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [node for node in root.select(selector) if isinstance(node, Tag)]
    except SelectorSyntaxError:
        return []


def _node_style_is_hidden(node: Tag) -> bool:
    style = str(node.get("style") or "").lower()
    return any(token in style for token in _detail_text_hidden_style_tokens)


def _node_is_hidden_or_auxiliary(node: Tag) -> bool:
    if _node_style_is_hidden(node):
        return True
    if node.has_attr("hidden") or str(node.get("aria-hidden") or "").lower() == "true":
        return True
    name = str(node.name or "").lower()
    if name in {"script", "style", "noscript", "template", "svg"}:
        return True
    role = str(node.get("role") or "").strip().lower()
    return role in {"presentation", "none"}


def _clone_visible_only(
    node: Tag | NavigableString,
    *,
    remaining_depth: int = 8,
    _soup: BeautifulSoup | None = None,
) -> Tag | NavigableString | None:
    if isinstance(node, NavigableString):
        text = clean_text(str(node))
        return NavigableString(str(node)) if isinstance(node, NavigableString) else None
    if not isinstance(node, Tag) or _node_is_hidden_or_auxiliary(node):
        return None
    if remaining_depth <= 0:
        text = clean_text(node.get_text(" ", strip=True))
        return NavigableString(text) if text else None
    if _soup is None:
        _soup = BeautifulSoup("", "html.parser")
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
    main = root.select_one(
        "main, article, [role='main'], [class*='product' i], [class*='detail' i]"
    )
    scope = main if isinstance(main, Tag) else root
    cloned_scope = _clone_visible_only(scope)
    return cloned_scope if isinstance(cloned_scope, Tag) else root


def section_label_text(node: Tag) -> str:
    pieces = [
        node.get_text(" ", strip=True),
        node.get("aria-label"),
        node.get("title"),
    ]
    return clean_text(next((piece for piece in pieces if piece), ""))


def _is_section_label(label: str) -> bool:
    cleaned = clean_text(label)
    if len(cleaned) < 3 or len(cleaned) > 80:
        return False
    if cleaned.lower() in {"details", "more", "overview"}:
        return False
    if any(token in cleaned.lower() for token in SEMANTIC_SECTION_LABEL_SKIP_TOKENS):
        return False
    return any(char.isalpha() for char in cleaned)


def _section_text(node: Tag, *, label: str = "") -> str:
    cloned = _clone_visible_only(node)
    if cloned is None:
        return ""
    text = html_to_text(str(cloned), preserve_block_breaks=True)
    text = clean_text(text)
    text = re.sub(r":(?=\S)", ": ", text)
    if not text:
        return ""
    if label and text.lower().startswith(label.lower()):
        text = clean_text(text[len(label) :])
    return text


def _extract_sibling_content(node: Tag, *, label: str = "") -> str:
    values: list[str] = []
    for sibling in node.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in _SECTION_STOP_TAGS:
            break
        if isinstance(sibling, Tag) and _node_is_hidden_or_auxiliary(sibling):
            continue
        text = clean_text(
            sibling.get_text(" ", strip=True)
            if isinstance(sibling, Tag)
            else str(sibling)
        )
        if not text:
            continue
        if isinstance(sibling, Tag) and not section_text_is_meaningful(
            sibling,
            label=label,
            text=text,
        ):
            continue
        values.append(text)
        if (
            len(values) >= _max_section_blocks
            or sum(len(item) for item in values) >= _max_section_chars
        ):
            break
    return " ".join(values)


def _section_target_ids(node: Tag) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    candidates = [node, *node.select("[aria-controls], a[href^='#']")[:6]]
    for candidate in candidates:
        if not isinstance(candidate, Tag):
            continue
        for raw_value in (
            candidate.get("aria-controls"),
            candidate.get("href"),
        ):
            target = clean_text(raw_value)
            if not target:
                continue
            if target.startswith("#"):
                target = target[1:]
            if not target or target in seen:
                continue
            seen.add(target)
            targets.append(target)
    return targets


def section_text_is_meaningful(node: Tag | None, *, label: str, text: str) -> bool:
    lowered_label = clean_text(label).lower()
    lowered_text = clean_text(text).lower()
    if not lowered_text:
        return False
    if any(token in lowered_label for token in SEMANTIC_SECTION_LABEL_SKIP_TOKENS):
        return False
    if any(pattern in lowered_text for pattern in _SECTION_SKIP_PATTERNS):
        return False
    if isinstance(node, Tag):
        role = str(node.get("role") or "").strip().lower()
        if node.name in {"button", "summary"} or role in {"button", "tab"}:
            return False
        interactive_count = len(
            node.select("a[href], button, [role='button'], [role='tab'], summary")
        )
        content_count = sum(
            1
            for candidate in node.select("p, li, dd, td, dt")
            if candidate.find_parent(["a", "button", "summary"]) is None
            and str(candidate.get("role") or "").strip().lower()
            not in {"button", "tab"}
        )
        if interactive_count >= 2 and content_count == 0:
            return False
    return True


def _page_heading_text(root: BeautifulSoup | Tag) -> str:
    heading = root.select_one("main h1, article h1, h1")
    if isinstance(heading, Tag):
        return clean_text(heading.get_text(" ", strip=True)).lower()
    return ""


def _section_matches_page_heading(root: BeautifulSoup | Tag, text: str) -> bool:
    lowered_text = clean_text(text).lower()
    if not lowered_text:
        return False
    page_heading = _page_heading_text(root)
    return bool(page_heading) and lowered_text == page_heading


def _find_wrapped_section_content(node: Tag, *, label: str) -> str:
    container: Tag | None = node
    best_text = ""
    seen: set[int] = set()
    for _ in range(4):
        if not isinstance(container, Tag):
            break
        for selector in _SECTION_CONTAINER_SELECTORS:
            for target in _safe_select(container, selector):
                if id(target) in seen or target is node:
                    continue
                seen.add(id(target))
                text = _section_text(target, label=label)
                if (
                    len(text) >= 12
                    and section_text_is_meaningful(target, label=label, text=text)
                    and (not best_text or len(text) < len(best_text))
                ):
                    best_text = text
        parent = container.parent
        container = parent if isinstance(parent, Tag) else None
    return best_text


def _section_content_is_heading_like(
    text: str,
    *,
    label: str,
    root: BeautifulSoup | Tag,
) -> bool:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    if not lowered:
        return False
    if lowered == clean_text(label).lower():
        return True
    if (
        _is_section_label(cleaned)
        and len(cleaned.split()) <= 6
        and not any(token in cleaned for token in ".:;!?\n")
    ):
        for heading in _safe_select(root, _SECTION_LABEL_SELECTOR):
            heading_label = section_label_text(heading)
            if heading_label and lowered == heading_label.lower():
                return True
    return False


def _first_matching_text(node: Tag, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        candidate = node.select_one(selector)
        if isinstance(candidate, Tag):
            text = clean_text(candidate.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _looks_like_materials_text(text: str) -> bool:
    lowered = clean_text(text).lower()
    if not lowered:
        return False
    if "%" in lowered:
        return True
    return any(token in lowered for token in _MATERIAL_TEXT_HINTS)


def _extract_product_materials(root: BeautifulSoup | Tag) -> str:
    for container in _safe_select(
        root,
        ".product-detail-composition, [class*='detailed-composition' i]",
    ):
        rows: list[str] = []
        for part in _safe_select(
            container,
            "li.product-detail-composition__part, li[class*='composition__part' i]",
        ):
            part_name = _first_matching_text(
                part,
                (
                    ".product-detail-composition__part-name",
                    "[class*='part-name' i]",
                ),
            )
            area_rows: list[str] = []
            for area in _safe_select(
                part,
                "li.product-detail-composition__area, li[class*='composition__area' i]",
            ):
                area_name = _first_matching_text(
                    area,
                    (
                        ".product-detail-composition__part-name",
                        "[class*='part-name' i]",
                    ),
                )
                values = [
                    clean_text(item.get_text(" ", strip=True))
                    for item in area.select("ul > li")
                    if clean_text(item.get_text(" ", strip=True))
                ]
                if not values:
                    continue
                if area_name:
                    area_rows.append(f"{area_name}: {'; '.join(values)}")
                else:
                    area_rows.append("; ".join(values))
            if part_name and area_rows:
                rows.append(f"{part_name}: {' '.join(area_rows)}")
            elif area_rows:
                rows.extend(area_rows)
        if rows:
            return "\n".join(dict.fromkeys(rows))
        text = clean_text(container.get_text(" ", strip=True))
        if len(text) >= 12 and _looks_like_materials_text(text):
            return text
    return ""


def extract_section_content(node: Tag, root: BeautifulSoup | Tag) -> str:
    label = section_label_text(node)
    for target_id in _section_target_ids(node):
        target = root.find(id=target_id)
        if isinstance(target, Tag):
            text = _section_text(target, label=label)
            if (
                len(text) >= 12
                and section_text_is_meaningful(target, label=label, text=text)
                and not _section_matches_page_heading(root, text)
            ):
                return text

    if node.name == "summary":
        parent = node.parent if isinstance(node.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "details":
            text = _section_text(parent, label=label)
            if (
                len(text) >= 12
                and section_text_is_meaningful(parent, label=label, text=text)
                and not _section_matches_page_heading(root, text)
            ):
                return text

    sibling_content = _extract_sibling_content(node, label=label)
    wrapped = _find_wrapped_section_content(node, label=label)
    if wrapped and not _section_matches_page_heading(root, wrapped):
        if not (
            sibling_content
            and _section_content_is_heading_like(wrapped, label=label, root=root)
        ):
            return wrapped
    if section_text_is_meaningful(
        node,
        label=label,
        text=sibling_content,
    ) and not _section_matches_page_heading(root, sibling_content):
        return sibling_content
    return ""


def _feature_rows_from_node(node: Tag) -> list[str]:
    rows = [
        clean_text(item.get_text(" ", strip=True))
        for item in node.select("li")
        if clean_text(item.get_text(" ", strip=True))
    ]
    if rows:
        return rows
    text = html_to_text(str(node), preserve_block_breaks=True)
    return [row for row in _split_feature_text(text) if row]


def _split_feature_text(text: str) -> list[str]:
    rows: list[str] = []
    for line in str(text or "").splitlines():
        cleaned = clean_text(line)
        if not cleaned:
            continue
        if re.search(r"(?:^|\s)-\s+\S", cleaned):
            dash_cleaned = re.sub(r"^-\s*", "", cleaned)
            parts = [part for part in re.split(r"\s+-\s+", dash_cleaned) if part]
            if len(parts) > 1:
                rows.extend(clean_text(part) for part in parts if clean_text(part))
                continue
        rows.append(cleaned)
    return rows
