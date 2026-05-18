from __future__ import annotations

__all__ = (
    "CONTENT_DETAIL_SURFACES",
    "extract",
)

import math
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import (
    CONTENT_SURFACE_CONTAINER_TAGS,
    CONTENT_SURFACE_DATE_SELECTORS,
    CONTENT_SURFACE_FORUM_BODY_SELECTORS,
    CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS,
    CONTENT_SURFACE_SANITIZE_SELECTORS,
)
from app.services.extract.table_extractor import extract_tables
from app.services.shared.field_coerce import absolute_url, clean_text

CONTENT_DETAIL_SURFACES = {"content_detail", "article_detail", "forum_detail"}


def extract(soup: BeautifulSoup, *, page_url: str, surface: str) -> dict[str, Any]:
    normalized = str(surface or "").strip().lower()
    working = BeautifulSoup(str(soup), "html.parser")
    _sanitize_dom(working)
    container = _main_container(working, normalized)
    tables = extract_tables(working, container, remove_from_dom=True)
    if normalized == "article_detail":
        record = _article_detail(working, container, page_url)
    elif normalized == "forum_detail":
        record = _forum_detail(working, container, page_url)
    else:
        record = _content_detail(working, container, page_url)
    if tables:
        record["tables"] = tables
    return {key: value for key, value in record.items() if value not in (None, "", [], {})}


def _content_detail(soup: BeautifulSoup, container: Tag, page_url: str) -> dict[str, Any]:
    content = _container_text(container)
    return {
        "title": _title(soup),
        "url": _canonical_url(soup, page_url),
        "content": content,
        "summary": _meta_description(soup) or _leading_paragraph(container),
        "headings": _headings(container),
        "word_count": _word_count(content),
        "image_url": _first_image(container, page_url),
        "language": _language(soup),
    }


def _article_detail(soup: BeautifulSoup, container: Tag, page_url: str) -> dict[str, Any]:
    content_container = _article_body_container(container) or _article_body_container(soup) or container
    content = _container_text(content_container)
    word_count = _word_count(content)
    return {
        "title": _title(soup),
        "url": _canonical_url(soup, page_url),
        "author": _selector_text(soup, [".author", "[rel='author']", "[itemprop='author']", ".byline"]),
        "publication_date": _date_text(soup),
        "content": content,
        "summary": _meta_description(soup) or _leading_paragraph(content_container),
        "image_url": _first_image(content_container, page_url),
        "tags": _tags(soup),
        "category": _category(soup),
        "language": _language(soup),
        "word_count": word_count,
        "reading_time": _reading_time(soup, word_count),
    }


def _forum_detail(soup: BeautifulSoup, container: Tag, page_url: str) -> dict[str, Any]:
    op_container = _first_match(
        soup,
        list(CONTENT_SURFACE_FORUM_BODY_SELECTORS),
    ) or container
    content = _container_text(op_container)
    return {
        "title": _title(soup),
        "url": _canonical_url(soup, page_url),
        "author": _selector_text(soup, [".author", "[rel='author']", "[itemprop='author']", ".username"]),
        "publication_date": _date_text(soup),
        "content": content,
        "summary": _meta_description(soup) or clean_text(content[:280]),
        "reply_count": _count_from_text(soup, ("reply", "replies", "comment", "comments")),
        "view_count": _count_from_text(soup, ("view", "views")),
        "tags": _tags(soup),
        "category": _category(soup),
    }


def _sanitize_dom(soup: BeautifulSoup) -> None:
    for selector in CONTENT_SURFACE_SANITIZE_SELECTORS:
        for node in soup.select(selector):
            if _sanitize_node_is_protected_container(node):
                continue
            node.decompose()


def _sanitize_node_is_protected_container(node: Tag) -> bool:
    name = str(getattr(node, "name", "") or "").strip().lower()
    if name in CONTENT_SURFACE_CONTAINER_TAGS:
        return True
    return any(node.select_one(selector) is not None for selector in CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS)


def _main_container(soup: BeautifulSoup, surface: str) -> Tag:
    selectors = ["main", "article", "[role='main']", ".content", ".post", ".entry-content"]
    if surface == "forum_detail":
        selectors = [".thread", ".topic", ".post", *selectors]
    return _first_match(soup, selectors) or soup


def _first_match(soup: BeautifulSoup | Tag, selectors: list[str]) -> Tag | None:
    for selector in selectors:
        match = soup.select_one(selector)
        if match is not None:
            return match
    return None


def _largest_text_match(soup: BeautifulSoup | Tag, selectors: list[str]) -> Tag | None:
    matches: list[Tag] = []
    for selector in selectors:
        matches.extend(node for node in soup.select(selector) if isinstance(node, Tag))
    if not matches:
        return None
    return max(matches, key=lambda node: len(_container_text(node)))


def _article_body_container(root: BeautifulSoup | Tag) -> Tag | None:
    for selectors in (
        ["[itemprop='articleBody']", ".article-body", ".post-content", ".entry-content"],
        ["article"],
        [".post"],
    ):
        match = _largest_text_match(root, selectors)
        if match is not None:
            return match
    return None


def _title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "meta[property='og:title']", "title"):
        node = soup.select_one(selector)
        value = clean_text(node.get("content") if node and node.name == "meta" else node.get_text(" ", strip=True) if node else "")
        if value:
            return value
    return ""


def _canonical_url(soup: BeautifulSoup, page_url: str) -> str:
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    return absolute_url(page_url, canonical.get("href") if canonical else "") or page_url


def _meta_description(soup: BeautifulSoup) -> str:
    for selector in ("meta[name='description']", "meta[property='og:description']", "meta[name='twitter:description']"):
        node = soup.select_one(selector)
        value = clean_text(node.get("content") if node else "")
        if value:
            return value
    return ""


def _container_text(container: Tag) -> str:
    return clean_text(container.get_text(" ", strip=True))


def _leading_paragraph(container: Tag) -> str:
    for paragraph in container.find_all("p"):
        value = clean_text(paragraph.get_text(" ", strip=True))
        if len(value) >= 40:
            return value
    return ""


def _headings(container: Tag) -> list[str]:
    return list(dict.fromkeys(clean_text(node.get_text(" ", strip=True)) for node in container.find_all(["h2", "h3"]) if clean_text(node.get_text(" ", strip=True))))


def _word_count(value: str) -> int:
    return len(re.findall(r"\w+", value or ""))


def _first_image(container: Tag, page_url: str) -> str:
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src")
        resolved = absolute_url(page_url, src)
        if resolved:
            return resolved
    return ""


def _language(soup: BeautifulSoup) -> str:
    html = soup.find("html")
    return clean_text(html.get("lang") if html else "")


def _selector_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    node = _first_match(soup, selectors)
    return clean_text(node.get_text(" ", strip=True) if node else "")


def _date_text(soup: BeautifulSoup) -> str:
    for selector in CONTENT_SURFACE_DATE_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        value = clean_text(node.get("datetime") or node.get("content") or node.get_text(" ", strip=True))
        if value:
            return value
    return ""


def _tags(soup: BeautifulSoup) -> list[str]:
    values = []
    for node in soup.select("[rel='tag'], .tag, .tags a"):
        value = clean_text(node.get_text(" ", strip=True))
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _category(soup: BeautifulSoup) -> str:
    return _selector_text(soup, [".category", "[rel='category']", ".breadcrumb"])


def _reading_time(soup: BeautifulSoup, word_count: int) -> int | None:
    node = _first_match(soup, [".reading-time", "[itemprop='timeRequired']", "[data-reading-time]"])
    raw = clean_text((node.get("content") or node.get("data-reading-time") or node.get_text(" ", strip=True)) if node else "")
    match = re.search(r"\d+", raw)
    if match:
        return int(match.group(0))
    if word_count:
        return int(math.ceil(word_count / 200))
    return None


def _count_from_text(soup: BeautifulSoup, labels: tuple[str, ...]) -> int | None:
    text = clean_text(soup.get_text(" ", strip=True)).lower()
    for label in labels:
        match = re.search(rf"(\d[\d,]*)\s+{re.escape(label)}\b", text)
        if match:
            return int(match.group(1).replace(",", ""))
    return None
