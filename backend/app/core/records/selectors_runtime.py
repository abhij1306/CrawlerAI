from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.selector_runtime import (
    SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.crawl.domain_memory_service import (
    load_domain_memory,
    list_selector_memories,
    selector_rules_from_memory,
)
from app.core.domain_utils import normalize_domain
from app.extraction.documents import DocumentStore, HtmlDocument
from app.extraction.surfaces import parse_surface
from app.core.records.html_helpers import html_to_text
from app.acquisition.fetch.fetch_context import fetch_page
from app.acquisition.fetch.types import FetchPageCall
from app.core.records.field_policy import normalize_field_key
from app.core.shared.field_coerce import coerce_int as _coerce_int
from app.core.url_safety import ensure_public_crawl_targets

if TYPE_CHECKING:
    from app.crawl.domain_memory_service import SelectorMemory


# Crawled/fetched page HTML is attacker-controlled. Any endpoint that serves it
# as text/html from the API origin must send these headers so embedded scripts
# cannot execute in the origin's security context (CSP sandbox = unique opaque
# origin, no script execution).
SANDBOXED_HTML_PREVIEW_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "sandbox",
    "X-Content-Type-Options": "nosniff",
}


async def fetch_selector_document(url: str) -> dict[str, object]:
    await ensure_public_crawl_targets([url])
    result = await fetch_page(FetchPageCall(url=str(url), prefer_browser=False))
    final_url = result.final_url
    html = result.html
    promoted = False
    visited = {final_url}
    for _ in range(
        max(1, int(crawler_runtime_settings.iframe_promotion_max_candidates))
    ):
        candidate_url = _primary_iframe_candidate(final_url, html)
        if not candidate_url or candidate_url in visited:
            break
        iframe_result = await fetch_page(
            FetchPageCall(url=candidate_url, prefer_browser=False)
        )
        iframe_text = html_to_text(iframe_result.html)
        page_text = html_to_text(html)
        if len(iframe_text) <= len(page_text):
            break
        final_url = iframe_result.final_url
        html = iframe_result.html
        promoted = True
        visited.add(final_url)
    return {"url": final_url, "html": html, "iframe_promoted": promoted}


def build_preview_html(*, source_url: str, html: str) -> str:
    base = f'<base href="{_html_attr(source_url)}">'
    if re.search(r"<head\b[^>]*>", html or "", flags=re.I):
        return re.sub(
            r"(<head\b[^>]*>)", rf"\1{base}", str(html or ""), count=1, flags=re.I
        )
    return f"<html><head>{base}</head><body>{html or ''}</body></html>"


async def list_selector_records(
    session: AsyncSession,
    *,
    domain: str,
    surface: str = "",
) -> list[dict[str, object]]:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_domain:
        records: list[dict[str, object]] = []
        for memory in await _all_domain_memories(session):
            for row in selector_rules_from_memory(memory):
                records.append(_selector_record_from_memory(row, memory=memory))
        return records
    if not normalized_surface:
        domain_records: list[dict[str, object]] = []
        for memory in await _all_domain_memories(session):
            if memory.domain != normalized_domain:
                continue
            for row in selector_rules_from_memory(memory):
                domain_records.append(_selector_record_from_memory(row, memory=memory))
        return domain_records
    loaded_memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return [
        _selector_record_from_memory(
            row,
            memory=loaded_memory,
            domain=normalized_domain,
            surface=normalized_surface,
        )
        for row in selector_rules_from_memory(loaded_memory)
    ]


def _selector_record_from_memory(
    row: dict[str, object],
    *,
    memory: SelectorMemory | None,
    domain: str | None = None,
    surface: str | None = None,
) -> dict[str, object]:
    resolved_domain = (
        domain if domain is not None else (memory.domain if memory else "")
    )
    resolved_surface = (
        surface if surface is not None else (memory.surface if memory else "")
    )
    return {
        **dict(row),
        "id": _coerce_int(row.get("id"), default=0),
        "domain": resolved_domain,
        "surface": resolved_surface,
        "source_run_id": row.get("source_run_id"),
        "created_at": memory.created_at if memory is not None else None,
        "updated_at": memory.updated_at if memory is not None else None,
    }


async def suggest_selectors(
    session: AsyncSession,
    *,
    url: str,
    expected_columns: list[str],
    surface: str | None = None,
) -> dict[str, object]:
    document = await fetch_selector_document(url)
    final_url = str(document["url"])
    resolved_surface = parse_surface(surface).value
    domain = normalize_domain(final_url)
    expected = {normalize_field_key(item) for item in expected_columns}
    suggestions: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in await list_selector_records(
        session,
        domain=domain,
        surface=resolved_surface,
    ):
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        css_selector = str(row.get("css_selector") or "").strip()
        if field_name and field_name in expected and css_selector:
            suggestions[field_name].append(
                {
                    "field_name": field_name,
                    "css_selector": css_selector,
                    "sample_value": row.get("sample_value"),
                    "source": row.get("source") or "domain_memory",
                }
            )
    return {
        "surface": resolved_surface,
        "preview_url": final_url,
        "iframe_promoted": bool(document.get("iframe_promoted")),
        "suggestions": {
            normalize_field_key(field_name): values[:5]
            for field_name, values in suggestions.items()
        },
    }


async def test_selector(
    *,
    url: str,
    css_selector: str | None = None,
) -> dict[str, object]:
    selector = str(css_selector or "").strip()
    if not selector:
        raise ValueError("css_selector is required")
    document = await fetch_selector_document(url)
    doc = DocumentStore({"html": str(document["html"])}).html("html")
    nodes = _select(doc, selector)
    value = _node_value(nodes[0]) if nodes else None
    return {
        "matched_value": value,
        "count": len(nodes),
        "selector_used": selector if nodes else None,
    }


async def _all_domain_memories(session: AsyncSession) -> list[SelectorMemory]:
    return await list_selector_memories(session)


def _primary_iframe_candidate(page_url: str, html: str) -> str:
    page_text = html_to_text(html)
    if len(page_text) > int(SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT):
        return ""
    doc = DocumentStore({"html": html}).html("html")
    for node in _select(doc, "iframe[src]"):
        src = str(node.attribute("src") or "").strip()
        if src:
            return urljoin(page_url, src)
    return ""


def _select(doc: HtmlDocument, selector: str):
    try:
        return tuple(doc.css(selector))
    except Exception as exc:
        raise ValueError(f"Invalid css_selector: {selector}") from exc


def _node_value(node) -> str | None:
    for attr in ("content", "value", "href", "src", "alt", "title", "aria-label"):
        value = str(node.attribute(attr) or "").strip()
        if value:
            return value
    text = re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()
    return text or None


def _html_attr(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
