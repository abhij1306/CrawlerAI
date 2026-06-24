from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from app.extraction.documents import HtmlNode

from app.core.config.sitemap import (
    SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS,
    SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS,
    SITEMAP_CATEGORY_EXCLUDED_PATH_TOKENS,
    SITEMAP_CATEGORY_PATH_TOKENS,
    SITEMAP_HOMEPAGE_CATEGORY_PATH_SCORE_BOOST,
    SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_EXTENSIONS,
    SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS,
)
from app.crawl.utils import text_has_token


def _build_nav_tree(
    urls: list[str],
    *,
    labels_by_url: Mapping[str, str | None] | None = None,
) -> list[dict[str, object]]:
    labels = {
        _url_key(url): label for url, label in (labels_by_url or {}).items() if label
    }
    url_by_key = {_url_key(url): url for url in urls}
    roots: list[dict[str, object]] = []
    child_maps: dict[int, dict[str, dict[str, object]]] = {}

    def children_for(node: dict[str, object]) -> list[dict[str, object]]:
        children = node.setdefault("children", [])
        if not isinstance(children, list):
            children = []
            node["children"] = children
        return children

    for raw_url in urls:
        parsed = urlsplit(raw_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            continue
        parent_children = roots
        current_path: list[str] = []
        for segment in segments:
            current_path.append(segment)
            prefix_url = urlunsplit(
                (parsed.scheme, parsed.netloc, "/" + "/".join(current_path), "", "")
            )
            prefix_key = _url_key(prefix_url)
            siblings = child_maps.setdefault(id(parent_children), {})
            node = siblings.get(segment.lower())
            if node is None:
                node = {
                    "label": labels.get(prefix_key)
                    or _label_from_path_segment(segment),
                    "children": [],
                }
                siblings[segment.lower()] = node
                parent_children.append(node)
            if prefix_key in url_by_key:
                node["url"] = url_by_key[prefix_key]
                if prefix_key in labels:
                    node["label"] = labels[prefix_key]
            parent_children = children_for(node)

    return roots


def _labels_by_url_from_tree(tree: list[dict[str, object]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    stack = list(tree)
    while stack:
        node = stack.pop()
        url = node.get("url")
        label = node.get("label")
        if isinstance(url, str) and isinstance(label, str):
            labels[_url_key(url)] = label
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return labels


def build_category_nav_tree(
    urls: list[str],
    *,
    labels_by_url: Mapping[str, str | None] | None = None,
) -> list[dict[str, object]]:
    return _build_nav_tree(urls, labels_by_url=labels_by_url)


def category_labels_by_url_from_tree(tree: list[dict[str, object]]) -> dict[str, str]:
    return _labels_by_url_from_tree(tree)


def category_url_key(url: str) -> str:
    return _url_key(url)


def category_origin_key(value: str) -> tuple[str, str, int]:
    return _origin_key(value)


def strip_url_fragment(value: str) -> str:
    return _strip_fragment(value)


def category_link_rejected(candidate_url: str) -> bool:
    return _reject_homepage_candidate(candidate_url)


def looks_like_category_url(url: str) -> bool:
    return _looks_like_category_url(url)


def has_category_anchor_signal(url: str, anchor: HtmlNode) -> bool:
    return _has_category_homepage_signal(url, anchor)


def _url_key(url: str) -> str:
    return _strip_fragment(url).rstrip("/").lower()


def _label_from_path_segment(segment: str) -> str:
    cleaned = segment.replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return segment
    return " ".join(word.capitalize() for word in cleaned.split())


def _anchor_label(anchor: HtmlNode) -> str | None:
    label = " ".join(anchor.text().split()).strip()
    if not label:
        return None
    return " ".join(label.split())


def _classify_homepage_candidate(
    *,
    candidate_url: str,
    keyword: str,
    anchor: HtmlNode,
) -> tuple[str, int]:
    path = urlsplit(candidate_url).path.lower().rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    depth = _path_depth(path)
    anchor_text = " ".join(anchor.text().split()).strip().lower()
    anchor_words = len([word for word in anchor_text.split() if word])
    keyword_hit = bool(keyword) and (
        keyword in candidate_url.lower() or keyword in anchor_text
    )
    nav_boost = 12 if any(node.tag() in {"nav", "header"} for node in anchor.ancestors()) else 0
    category_path_boost = _category_path_score_boost(path)
    if _looks_like_category_url(candidate_url) or _has_category_homepage_signal(
        candidate_url, anchor
    ):
        return "listing", 300 + nav_boost + category_path_boost + (
            25 if keyword_hit else 0
        )
    if _looks_like_detail_link(slug, depth=depth, anchor_words=anchor_words):
        return "detail", 120 + (25 if keyword_hit else 0)
    return "", 0


def _category_path_score_boost(path: str) -> int:
    return (
        SITEMAP_HOMEPAGE_CATEGORY_PATH_SCORE_BOOST
        if any(token in path for token in SITEMAP_CATEGORY_PATH_TOKENS)
        else 0
    )


def _looks_like_detail_link(slug: str, *, depth: int, anchor_words: int) -> bool:
    if depth < 2:
        return False
    if anchor_words == 0 or anchor_words > 12:
        return False
    if any(char.isdigit() for char in slug):
        return True
    return slug.count("-") >= 2 or slug.count("_") >= 2


def _looks_like_category_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    excluded_tokens = (
        *SITEMAP_CATEGORY_EXCLUDED_PATH_TOKENS,
        *SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS,
    )
    if _path_has_excluded_token(path, excluded_tokens):
        return False
    if any(token in path for token in SITEMAP_CATEGORY_PATH_TOKENS):
        return True
    segments = [segment for segment in path.split("/") if segment]
    if not segments or any(_looks_like_locale_segment(segment) for segment in segments):
        return False
    if any(segment.isdigit() for segment in segments):
        return False
    segment_text = " ".join(segment.replace("-", " ") for segment in segments)
    if any(
        token in segment_text for token in SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS
    ):
        return False
    category_segments = {
        token
        for token in SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS
        if token and " " not in token
    }
    return (
        1 <= len(segments) <= 3
        and all(len(segment) >= 2 for segment in segments)
        and any(segment.replace("-", " ") in category_segments for segment in segments)
    )


def _has_category_homepage_signal(url: str, anchor: HtmlNode) -> bool:
    if _looks_like_category_url(url):
        return True
    path = urlsplit(url).path.lower().strip("/")
    if not path or _looks_like_locale_path(path):
        return False
    text = " ".join(anchor.text().split()).strip().lower()
    if not text:
        return False
    if any(
        text_has_token(text, token)
        for token in SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS
    ):
        return False
    return any(
        text_has_token(text, token) for token in SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS
    )


def _looks_like_locale_path(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if not parts or len(parts) > 2:
        return False
    return all(_looks_like_locale_segment(part.replace("_", "-")) for part in parts)


def _reject_homepage_candidate(candidate_url: str) -> bool:
    parsed = urlsplit(candidate_url)
    if parsed.scheme not in {"http", "https"}:
        return True
    path = parsed.path.lower()
    if not path or path == "/":
        return True
    if any(path.endswith(ext) for ext in SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_EXTENSIONS):
        return True
    return _path_has_excluded_token(
        path,
        SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS,
    )


def _path_has_excluded_token(path: str, tokens: tuple[str, ...]) -> bool:
    for token in tokens:
        start = path.find(token)
        if start < 0:
            continue
        end = start + len(token)
        if end == len(path) or token.endswith("/") or path[end] in "/-_":
            return True
    return False


def _path_depth(path: str) -> int:
    parts = [
        part
        for part in path.split("/")
        if part and not _looks_like_locale_segment(part)
    ]
    return len(parts)


def _looks_like_locale_segment(value: str) -> bool:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) == 2 and cleaned.isalpha():
        return True
    if len(cleaned) == 5 and cleaned[2] == "-":
        return cleaned[:2].isalpha() and cleaned[3:].isalpha()
    return False


def _strip_fragment(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _origin_key(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    scheme = str(parsed.scheme or "").lower()
    hostname = str(parsed.hostname or "").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, hostname, port
