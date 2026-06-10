from __future__ import annotations

import asyncio
from typing import Any

from app.services.config.sitemap import (
    CRAWL_CATEGORY_DISCOVERY_PER_INPUT_TIMEOUT_SECONDS,
    PLAYGROUND_CATEGORY_MAX_LIMIT,
    SITE_LINK_DISCOVERY_MAX_DEPTH,
    SITE_LINK_DISCOVERY_MAX_PAGES,
    SITEMAP_DEFAULT_FILTER_KEYWORD,
)
from app.services.crawl.sitemap_resolver import resolve_category_urls_with_site_links
from app.services.crawl.utils import normalize_target_url


async def discover_category_urls(
    urls: list[str],
    *,
    limit: int,
    max_depth: int = SITE_LINK_DISCOVERY_MAX_DEPTH,
    max_pages: int = SITE_LINK_DISCOVERY_MAX_PAGES,
    strategy: str = "static_then_rendered",
    validate_candidates: bool = False,
) -> dict[str, Any]:
    normalized_inputs = _normalize_inputs(urls)
    bounded_limit = max(1, min(int(limit), PLAYGROUND_CATEGORY_MAX_LIMIT))
    tasks = [
        _resolve_one(
            input_url,
            limit=bounded_limit,
            max_depth=max_depth,
            max_pages=max_pages,
            strategy=strategy,
            validate_candidates=validate_candidates,
        )
        for input_url in normalized_inputs
    ]
    results = await asyncio.gather(*tasks)
    grouped: dict[str, list[str]] = {}
    sources: dict[str, str] = {}
    errors: dict[str, str] = {}
    trees: dict[str, list[dict[str, object]]] = {}
    diagnostics: dict[str, object] = {}
    flat_urls: list[str] = []
    for input_url, result in zip(normalized_inputs, results, strict=True):
        urls_for_input = result["urls"][:bounded_limit]
        grouped[input_url] = urls_for_input
        sources[input_url] = str(result["source"])
        if result.get("error"):
            errors[input_url] = str(result["error"])
        if isinstance(result.get("nav_tree"), list):
            trees[input_url] = result["nav_tree"]
        if isinstance(result.get("diagnostics"), dict):
            diagnostics[input_url] = result["diagnostics"]
        for url in urls_for_input:
            if url not in flat_urls:
                flat_urls.append(url)
    source = "multi"
    if len(set(sources.values())) == 1 and sources:
        source = next(iter(sources.values()))
    return {
        "status": "completed",
        "source": source,
        "sources": sources,
        "urls": flat_urls[:bounded_limit],
        "groups": grouped,
        "trees": trees,
        "errors": errors,
        "diagnostics": diagnostics,
        "total_found": len(flat_urls),
        "limit": bounded_limit,
    }


async def _resolve_one(
    input_url: str,
    *,
    limit: int,
    max_depth: int,
    max_pages: int,
    strategy: str,
    validate_candidates: bool,
) -> dict[str, Any]:
    try:
        resolution = await asyncio.wait_for(
            resolve_category_urls_with_site_links(
                domain=input_url,
                filter_keyword=SITEMAP_DEFAULT_FILTER_KEYWORD,
                max_urls=limit,
                allow_homepage_fallback=True,
                category_only=True,
                strategy=strategy,
                max_depth=max_depth,
                max_pages=max_pages,
                validate_candidates=validate_candidates,
            ),
            timeout=CRAWL_CATEGORY_DISCOVERY_PER_INPUT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return {
            "urls": [],
            "source": "timeout",
            "error": "TimeoutError",
            "nav_tree": None,
            "diagnostics": {},
        }
    except Exception as exc:
        return {
            "urls": [],
            "source": "failed",
            "error": type(exc).__name__,
            "nav_tree": None,
            "diagnostics": {"message": str(exc)},
        }
    return {
        "urls": resolution.urls,
        "source": resolution.source,
        "error": None,
        "nav_tree": resolution.nav_tree,
        "diagnostics": resolution.diagnostics,
    }


def _normalize_inputs(urls: list[str]) -> list[str]:
    normalized = [
        normalized
        for item in urls
        if item and (normalized := normalize_target_url(str(item).strip()))
    ]
    return list(dict.fromkeys(normalized))
