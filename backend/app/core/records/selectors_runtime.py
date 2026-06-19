from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_rules import (
    SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.crawl.domain_memory_service import (
    load_domain_memory,
    save_domain_memory,
    selector_payload_from_rules,
    selector_rules_from_memory,
)
from app.core.domain_utils import normalize_domain
from app.extraction.documents import DocumentStore, HtmlDocument
from app.extraction.surfaces import parse_surface
from app.core.records.html_helpers import html_to_text
from app.acquisition.fetch.fetch_context import fetch_page
from app.core.records.field_policy import normalize_field_key
from app.core.shared.field_coerce import coerce_int as _coerce_int
from app.core.url_safety import ensure_public_crawl_targets

if TYPE_CHECKING:
    from app.models.domain_memory import DomainMemory

coerce_int = _coerce_int


async def fetch_selector_document(url: str) -> dict[str, object]:
    await ensure_public_crawl_targets([url])
    result = await fetch_page(str(url), prefer_browser=False)
    final_url = result.final_url
    html = result.html
    promoted = False
    visited = {final_url}
    for _ in range(max(1, int(crawler_runtime_settings.iframe_promotion_max_candidates))):
        candidate_url = _primary_iframe_candidate(final_url, html)
        if not candidate_url or candidate_url in visited:
            break
        iframe_result = await fetch_page(candidate_url, prefer_browser=False)
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
        return re.sub(r"(<head\b[^>]*>)", rf"\1{base}", str(html or ""), count=1, flags=re.I)
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
    memory: DomainMemory | None,
    domain: str | None = None,
    surface: str | None = None,
) -> dict[str, object]:
    resolved_domain = domain if domain is not None else (memory.domain if memory else "")
    resolved_surface = surface if surface is not None else (memory.surface if memory else "")
    return {
        **dict(row),
        "id": _coerce_int(row.get("id"), default=0),
        "domain": resolved_domain,
        "surface": resolved_surface,
        "source_run_id": row.get("source_run_id"),
        "created_at": memory.created_at if memory is not None else None,
        "updated_at": memory.updated_at if memory is not None else None,
    }


async def list_selector_domain_summaries(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, object]]:
    from sqlalchemy import select

    from app.models.domain_memory import DomainMemory

    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    query = select(DomainMemory).order_by(DomainMemory.id.asc())
    if normalized_domain:
        query = query.where(DomainMemory.domain == normalized_domain)
    if normalized_surface:
        query = query.where(DomainMemory.surface == normalized_surface)
    if offset > 0:
        query = query.offset(int(offset))
    if limit is not None:
        query = query.limit(int(limit))
    result = await session.execute(query)
    return [
        {
            "domain": memory.domain,
            "surface": memory.surface,
            "selector_count": _selector_rule_count(memory.selectors),
            "updated_at": memory.updated_at,
        }
        for memory in result.scalars().all()
    ]


async def create_selector_record(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    payload: dict[str, object],
    commit: bool = True,
) -> dict[str, object]:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = parse_surface(surface).value
    css_selector = str(payload.get("css_selector") or "").strip()
    if not css_selector:
        raise ValueError("css_selector is required")
    await _ensure_unique_selector_ids(session)
    memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    rules = selector_rules_from_memory(memory)
    next_id = await _next_selector_id(session)
    record = {
        "id": next_id,
        "field_name": normalize_field_key(str(payload.get("field_name") or "")),
        "css_selector": css_selector,
        "status": str(payload.get("status") or "validated").strip(),
        "sample_value": str(payload.get("sample_value") or "").strip() or None,
        "source": str(payload.get("source") or "domain_memory").strip(),
        "source_run_id": payload.get("source_run_id"),
        "is_active": bool(payload.get("is_active", True)),
    }
    rules = [row for row in rules if _coerce_int(row.get("id"), default=0) != next_id]
    rules.append(record)
    await save_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        selectors=selector_payload_from_rules(rules),
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    memory = await load_domain_memory(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return {
        "domain": normalized_domain,
        "surface": normalized_surface,
        **record,
        "created_at": memory.created_at if memory is not None else None,
        "updated_at": memory.updated_at if memory is not None else None,
    }


async def update_selector_record(
    session: AsyncSession,
    *,
    selector_id: int,
    payload: dict[str, object],
    commit: bool = True,
) -> dict[str, object] | None:
    await _ensure_unique_selector_ids(session)
    for memory in await _all_domain_memories(session):
        rules = selector_rules_from_memory(memory)
        updated = False
        for row in rules:
            if _coerce_int(row.get("id"), default=0) != int(selector_id):
                continue
            for key in (
                "field_name",
                "css_selector",
                "status",
                "sample_value",
                "source",
                "source_run_id",
                "is_active",
            ):
                if key not in payload:
                    continue
                value = payload.get(key)
                if key == "field_name":
                    row[key] = normalize_field_key(str(value or ""))
                elif key == "is_active":
                    row[key] = bool(value)
                elif key == "source_run_id":
                    row[key] = value
                elif key == "css_selector" and not str(value or "").strip():
                    raise ValueError("css_selector is required")
                else:
                    row[key] = str(value or "").strip() or None
            updated = True
            break
        if not updated:
            continue
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(rules),
        )
        if commit:
            await session.commit()
        else:
            await session.flush()
        refreshed_memory = await load_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
        )
        refreshed = next(
            (
                row
                for row in rules
                if _coerce_int(row.get("id"), default=0) == int(selector_id)
            ),
            None,
        )
        if refreshed is None:
            raise ValueError(f"Selector {selector_id} was not found after update")
        return {
            "domain": memory.domain,
            "surface": memory.surface,
            **refreshed,
            "created_at": (
                refreshed_memory.created_at if refreshed_memory is not None else None
            ),
            "updated_at": (
                refreshed_memory.updated_at if refreshed_memory is not None else None
            ),
        }
    return None


async def delete_selector_record(
    session: AsyncSession,
    *,
    selector_id: int,
) -> bool:
    await _ensure_unique_selector_ids(session)
    for memory in await _all_domain_memories(session):
        rules = selector_rules_from_memory(memory)
        next_rules = [
            row
            for row in rules
            if _coerce_int(row.get("id"), default=0) != int(selector_id)
        ]
        if len(next_rules) == len(rules):
            continue
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(next_rules),
        )
        await session.commit()
        return True
    return False


async def delete_domain_selector_records(
    session: AsyncSession,
    *,
    domain: str,
    surface: str | None = None,
) -> int:
    await _ensure_unique_selector_ids(session)
    deleted = 0
    normalized_domain = str(domain or "").strip().lower()
    for memory in await _all_domain_memories(session):
        if memory.domain != normalized_domain:
            continue
        if surface and memory.surface != parse_surface(surface).value:
            continue
        rules = selector_rules_from_memory(memory)
        deleted += len(rules)
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules([]),
        )
    if deleted:
        await session.commit()
    return deleted


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


async def _all_domain_memories(session: AsyncSession) -> list[DomainMemory]:
    from sqlalchemy import select

    from app.models.domain_memory import DomainMemory

    result = await session.execute(select(DomainMemory).order_by(DomainMemory.id.asc()))
    return list(result.scalars().all())


async def _next_selector_id(session: AsyncSession) -> int:
    max_id = 0
    for memory in await _all_domain_memories(session):
        for row in selector_rules_from_memory(memory):
            max_id = max(max_id, _coerce_int(row.get("id"), default=0))
    return max_id + 1


async def _ensure_unique_selector_ids(session: AsyncSession) -> None:
    memories = await _all_domain_memories(session)
    seen_ids: set[int] = set()
    next_id = 1
    changed = False
    for memory in memories:
        rules = selector_rules_from_memory(memory)
        memory_changed = False
        for row in rules:
            current_id = _coerce_int(row.get("id"), default=0)
            if current_id > 0 and current_id not in seen_ids:
                seen_ids.add(current_id)
                next_id = max(next_id, current_id + 1)
                continue
            row["id"] = next_id
            seen_ids.add(next_id)
            next_id += 1
            memory_changed = True
        if not memory_changed:
            continue
        changed = True
        await save_domain_memory(
            session,
            domain=memory.domain,
            surface=memory.surface,
            platform=memory.platform,
            selectors=selector_payload_from_rules(rules),
        )
    if changed:
        await session.flush()


def _selector_rule_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    rules = value.get("rules")
    if isinstance(rules, list):
        return sum(
            1
            for row in rules
            if isinstance(row, dict) and str(row.get("css_selector") or "").strip()
        )
    return sum(
        1
        for field_name, payload in value.items()
        if not str(field_name).startswith("_")
        and isinstance(payload, dict)
        and str(payload.get("css_selector") or payload.get("css") or "").strip()
    )


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
