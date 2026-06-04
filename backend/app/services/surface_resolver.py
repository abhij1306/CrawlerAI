from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.config import surface_detection as config


@dataclass(frozen=True, slots=True)
class SurfaceResolution:
    surface: str
    confidence: float
    evidence: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def resolve_surface(
    requested_surface: str,
    *,
    url: str = "",
    html: str | None = None,
    run_type: str = "crawl",
    crawl_module: str | None = None,
) -> SurfaceResolution:
    normalized = str(requested_surface or "").strip().lower()
    if normalized and normalized != config.AUTO_SURFACE:
        return SurfaceResolution(normalized, 1.0, ["explicit_surface"])
    return resolve_auto_surface(
        url=url,
        html=html,
        is_listing=_is_listing_context(run_type=run_type, crawl_module=crawl_module),
    )


def resolve_public_surface(
    requested_surface: str,
    *,
    url: str = "",
    html: str | None = None,
    is_listing: bool = False,
) -> SurfaceResolution | None:
    normalized = str(requested_surface or "").strip().lower()
    if normalized == config.PUBLIC_SURFACE_AUTO:
        return resolve_auto_surface(url=url, html=html, is_listing=is_listing)
    if normalized in config.PUBLIC_TO_DETAIL_SURFACE:
        mapping = (
            config.PUBLIC_TO_LISTING_SURFACE
            if is_listing
            else config.PUBLIC_TO_DETAIL_SURFACE
        )
        surface = mapping.get(normalized) or config.PUBLIC_TO_DETAIL_SURFACE[normalized]
        return SurfaceResolution(surface, 1.0, [f"public_surface:{normalized}"])
    return None


def public_surface_for_internal(surface: str) -> str:
    normalized = str(surface or "").strip().lower()
    if normalized.startswith("ecommerce_"):
        return config.PUBLIC_SURFACE_ECOMMERCE
    if normalized.startswith("article_"):
        return config.PUBLIC_SURFACE_ARTICLE
    if normalized.startswith("content_"):
        return config.PUBLIC_SURFACE_CONTENT
    if normalized == "forum_detail":
        return config.PUBLIC_SURFACE_FORUM_THREAD
    return normalized


def resolve_auto_surface(
    *,
    url: str = "",
    html: str | None = None,
    is_listing: bool = False,
) -> SurfaceResolution:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    evidence: list[str] = ["requested_surface:auto"]

    typed_html_resolution = _resolve_from_html_schema(html)
    if typed_html_resolution is not None:
        return typed_html_resolution

    if _has_any(path, config.SURFACE_RESOLVER_ARTICLE_PATH_TOKENS) or (
        host in config.SURFACE_RESOLVER_ARTICLE_HOSTS
        and _has_article_detail_path(path)
    ):
        return SurfaceResolution(
            "article_detail",
            config.SURFACE_RESOLVER_HIGH_CONFIDENCE,
            [*evidence, "article_detail_url_signal"],
        )

    if _has_forum_signal(host, path):
        return SurfaceResolution(
            "forum_detail",
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, "forum_url_signal"],
        )

    if _has_any(path, config.SURFACE_RESOLVER_JOB_PATH_TOKENS):
        surface = "job_listing" if is_listing else "job_detail"
        return SurfaceResolution(
            surface,
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, "job_url_signal"],
        )

    if _has_any(path, config.SURFACE_RESOLVER_ECOMMERCE_LISTING_PATH_TOKENS):
        return SurfaceResolution(
            "ecommerce_listing",
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, "ecommerce_listing_url_signal"],
        )

    if _has_any(path, config.SURFACE_RESOLVER_ECOMMERCE_DETAIL_PATH_TOKENS):
        return SurfaceResolution(
            "ecommerce_detail",
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, "ecommerce_detail_url_signal"],
        )

    html_detail_signal = _html_detail_signal(path)
    if html_detail_signal:
        return SurfaceResolution(
            "ecommerce_detail",
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, html_detail_signal],
        )

    if _has_listing_segment(path):
        return SurfaceResolution(
            "ecommerce_listing",
            config.SURFACE_RESOLVER_MEDIUM_CONFIDENCE,
            [*evidence, "ecommerce_listing_segment_signal"],
        )

    fallback = "content_detail"
    if is_listing and _has_listing_url_shape(path):
        fallback = "content_listing"
    return SurfaceResolution(
        fallback,
        config.SURFACE_RESOLVER_LOW_CONFIDENCE,
        [*evidence, "fallback_content_surface"],
    )


def _resolve_from_html_schema(html: str | None) -> SurfaceResolution | None:
    if not html or not str(html).strip():
        return None
    soup = BeautifulSoup(html, "html.parser")
    typed_surface = _surface_from_schema_types(soup)
    if typed_surface:
        return SurfaceResolution(
            typed_surface,
            config.SURFACE_RESOLVER_HIGH_CONFIDENCE,
            [f"schema_type:{typed_surface}"],
        )
    return None


def _surface_from_schema_types(soup: BeautifulSoup) -> str:
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        for schema_type in _schema_types_from_json_ld(node.string or ""):
            normalized = schema_type.lower()
            surface = config.SURFACE_RESOLVER_HTML_TYPES.get(normalized)
            if surface:
                return surface
    for node in soup.select("[itemtype]"):
        raw_itemtype = str(node.get("itemtype") or "")
        for token in raw_itemtype.split():
            token = token.strip()
            if not token:
                continue
            normalized = token.lower().rsplit("/", maxsplit=1)[-1]
            surface = config.SURFACE_RESOLVER_HTML_TYPES.get(normalized)
            if surface:
                return surface
    return ""


def _schema_types_from_json_ld(raw: str) -> list[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    results: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            raw_type = value.get("@type")
            if isinstance(raw_type, str):
                results.append(raw_type)
            elif isinstance(raw_type, list):
                results.extend(str(item) for item in raw_type if item)
            graph = value.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return results


def _is_listing_context(*, run_type: str, crawl_module: str | None) -> bool:
    normalized_run_type = str(run_type or "").strip().lower()
    normalized_module = str(crawl_module or "").strip().lower()
    return normalized_run_type in {"batch", "csv"} or normalized_module == "category"


def _has_article_detail_path(path: str) -> bool:
    return any(token in path for token in ("/blog/entry/", "/article/", "/post/"))


def _has_forum_signal(host: str, path: str) -> bool:
    return any(token in host for token in config.SURFACE_RESOLVER_FORUM_HOST_TOKENS) or _has_any(
        path,
        config.SURFACE_RESOLVER_FORUM_PATH_TOKENS,
    )


def _has_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


def _has_listing_segment(path: str) -> bool:
    segments = {
        segment.strip().lower()
        for segment in str(path or "").split("/")
        if segment.strip()
    }
    return bool(
        segments.intersection(config.SURFACE_RESOLVER_ECOMMERCE_LISTING_PATH_SEGMENTS)
    )


def _html_detail_signal(path: str) -> str:
    normalized = str(path or "").strip().lower()
    slug = normalized.rstrip("/").rsplit("/", maxsplit=1)[-1]
    if not slug.endswith(config.SURFACE_RESOLVER_ECOMMERCE_DETAIL_HTML_EXTENSION):
        return ""
    if re.search(config.SURFACE_RESOLVER_ECOMMERCE_DETAIL_SKU_HTML_PATTERN, normalized):
        return "ecommerce_detail_sku_html_signal"
    if slug.count("-") >= config.SURFACE_RESOLVER_ECOMMERCE_DETAIL_HTML_MIN_HYPHENS:
        return "ecommerce_detail_html_slug_signal"
    return ""


def _has_listing_url_shape(path: str) -> bool:
    normalized = str(path or "").strip().lower().rstrip("/")
    return normalized in {
        "/archive",
        "/archives",
        "/blog",
        "/blogs",
        "/docs",
        "/documentation",
        "/events",
        "/forum",
        "/forums",
        "/news",
        "/posts",
        "/resources",
        "/topics",
    }
