from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

from app.services.shared.field_coerce import absolute_url, clean_text, finalize_record

logger = logging.getLogger(__name__)

def extract_xml_sitemap_records(
    text: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    content_type: str | None,
) -> list[dict[str, Any]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    raw = str(text or "").lstrip("\ufeff").strip()
    lowered_content_type = str(content_type or "").strip().lower()
    if not _looks_like_xml_document(raw, content_type=lowered_content_type):
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        logger.exception(
            "ET.fromstring failed while parsing sitemap from %s; bytes=%d",
            page_url,
            len(raw.encode("utf-8")),
        )
        return []
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    limit = max(0, int(max_records or 0))
    for loc_text in _xml_sitemap_locations(root):
        if limit and len(records) >= limit:
            break
        url = absolute_url(page_url, loc_text)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _xml_listing_title(url)
        if not title:
            continue
        records.append(
            finalize_record(
                {
                    "source_url": page_url,
                    "_source": "xml_sitemap",
                    "title": title,
                    "url": url,
                },
                surface=surface,
            )
        )
    return records


def _looks_like_xml_document(text: str, *, content_type: str) -> bool:
    if not text:
        return False
    if any(token in content_type for token in ("xml", "rss", "atom")):
        return True
    return (
        text.startswith("<?xml")
        or text.startswith("<urlset")
        or text.startswith("<sitemapindex")
        or text.startswith("<rss")
        or text.startswith("<feed")
    )


def _xml_sitemap_locations(root: ET.Element) -> list[str]:
    locations: list[str] = []
    for node in root.iter():
        tag_name = str(node.tag or "")
        local_tag_name = tag_name.rsplit("}", 1)[-1]
        if local_tag_name == "loc":
            value = " ".join(str(node.text or "").split()).strip()
        elif local_tag_name == "link":
            value = " ".join(str(node.get("href") or node.text or "").split()).strip()
        else:
            continue
        if value:
            locations.append(value)
    return locations


def _xml_listing_title(url: str) -> str:
    path = str(urlsplit(url).path or "").strip("/")
    if not path:
        return ""
    terminal = unquote(path.rsplit("/", 1)[-1])
    terminal = re.sub(r"\.(html?|xml)$", "", terminal, flags=re.I)
    if not terminal:
        return ""
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if title:
        return title
    return clean_text(path.rsplit("/", 1)[-1])


