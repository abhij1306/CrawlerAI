from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from app.services.acquisition.runtime import classify_blocked_page
from app.services.acquisition.browser_runtime import get_browser_runtime, real_chrome_browser_available
from app.services.acquisition.dom_runtime import get_page_html
from app.services.config.product_intelligence import (
    AGGREGATOR_DOMAINS,
    BRAND_DOMAIN_MAP,
    DISCOVERY_SOURCE_TYPE_PRIORITY,
    DISCOVERY_GENERIC_PRODUCT_TOKENS,
    DISCOVERY_TITLE_MISMATCH_MIN_DISTINCTIVE_TOKENS,
    DISCOVERY_TITLE_MISMATCH_MIN_OVERLAP_RATIO,
    MARKETPLACE_DOMAINS,
    RETAILER_DOMAINS,
    SEARCH_EXCLUDED_DOMAIN_PREFIX,
    SEARCH_PHRASE_BUY,
    SEARCH_PROVIDER_GOOGLE_NATIVE,
    SEARCH_PROVIDER_SERPAPI,
    SEARCH_SITE_PREFIX,
    SERPAPI_ENGINE,
    SERPAPI_ENGINE_PARAM,
    SERPAPI_IMMERSIVE_PRODUCT_ENGINE,
    SERPAPI_KEY_PARAM,
    SERPAPI_LINK_FIELD,
    SERPAPI_MORE_STORES_PARAM,
    SERPAPI_PAGE_TOKEN_PARAM,
    SERPAPI_ORGANIC_RESULTS_FIELD,
    SERPAPI_POSITION_FIELD,
    SERPAPI_QUERY_PARAM,
    SERPAPI_RESULT_COUNT_PARAM,
    SERPAPI_SEARCH_URL,
    SERPAPI_SHOPPING_ENGINE,
    SERPAPI_SHOPPING_IMMERSIVE_API_FIELD,
    SERPAPI_SHOPPING_IMMERSIVE_TOKEN_FIELD,
    SERPAPI_SHOPPING_LINK_FIELDS,
    SERPAPI_SHOPPING_PRODUCT_ID_FIELD,
    SERPAPI_SHOPPING_PRODUCT_LINK_FIELD,
    SERPAPI_SHOPPING_RESULTS_FIELD,
    SERPAPI_SNIPPET_FIELD,
    SERPAPI_SOURCE_FIELD,
    SERPAPI_TITLE_FIELD,
    SOURCE_TYPE_AGGREGATOR,
    SOURCE_TYPE_BRAND_DTC,
    SOURCE_TYPE_MARKETPLACE,
    SOURCE_TYPE_RETAILER,
    SOURCE_TYPE_UNKNOWN,
    GOOGLE_NATIVE_BROWSER_ENGINE,
    GOOGLE_NATIVE_BLOCKED_HTML_PATTERNS,
    GOOGLE_NATIVE_BLOCKED_CLASSIFICATION_OFFSET,
    GOOGLE_NATIVE_BLOCKED_URL_PATTERNS,
    GOOGLE_NATIVE_HOME_URL,
    GOOGLE_NATIVE_IGNORED_DOMAINS,
    GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS,
    GOOGLE_NATIVE_PROVIDER_PAYLOAD,
    GOOGLE_NATIVE_QUERY_PARAM,
    GOOGLE_NATIVE_REDIRECT_PATH,
    GOOGLE_NATIVE_REDIRECT_TARGET_PARAM,
    GOOGLE_NATIVE_RESULT_COUNT_PARAM,
    GOOGLE_NATIVE_RESULT_LINK_SELECTOR,
    GOOGLE_NATIVE_RESULT_WAIT_MS,
    GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR,
    GOOGLE_NATIVE_SEARCH_URL,
    GOOGLE_NATIVE_SUBMIT_KEY,
    GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH,
    GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH,
    GOOGLE_NATIVE_TITLE_SELECTOR,
    GOOGLE_NATIVE_TYPING_EXTRA_WAIT_MS,
    product_intelligence_settings,
)
from app.services.shared.field_coerce import clean_text
from app.services.product_intelligence.candidate_urls import (
    candidate_dedupe_key,
    clean_result_url,
    looks_like_product_detail_url,
    normalized_compare_url,
)
from app.services.product_intelligence.matching import (
    manufacturer_style_code,
    normalize_brand,
    source_domain,
)

logger = logging.getLogger(__name__)

QueryRunner = Callable[[str, int], Awaitable[list["SearchResult"]]]


@dataclass(slots=True)
class DiscoveredCandidate:
    url: str
    domain: str
    source_type: str
    query_used: str
    search_rank: int
    payload: dict[str, object] | None = None
    query_order: int = 0


@dataclass(slots=True)
class SearchResult:
    url: str
    payload: dict[str, object]


def build_search_queries(
    product: dict[str, object],
    *,
    source_domain_value: str = "",
) -> list[str]:
    brand = normalize_brand(product.get("brand"))
    brand_query = brand
    title = _title_without_brand(
        product.get("title"),
        product.get("brand"),
        brand,
    )
    queries: list[str] = []
    gtin = _identity_field(product, "gtin")
    mpn = _query_identifier_value(product)
    # Prefer the UPC/GTIN as the identifier appended to brand+title queries; the
    # SKU/MPN-like token is only a fallback when no UPC is present. The UPC is the
    # strongest single matching signal and is GTIN-indexed by Google Shopping.
    query_identifier = gtin or mpn
    brand_domain = BRAND_DOMAIN_MAP.get(brand)
    brand_site = f"{SEARCH_SITE_PREFIX}{brand_domain}" if brand_domain else ""

    if gtin:
        queries.append(_quoted(gtin))

    if brand and title and brand_site:
        if query_identifier:
            queries.append(_join_query_parts(brand_site, _quoted(query_identifier)))
        queries.append(_join_query_parts(brand_site, brand_query, title))

    if brand and title:
        if query_identifier:
            queries.append(_join_query_parts(brand_query, title, _quoted(query_identifier)))
        queries.append(_join_query_parts(brand_query, title))

    if title and not brand:
        identifier = gtin or mpn
        if identifier:
            queries.append(_join_query_parts(_quoted(title), _quoted(identifier)))
        queries.append(_join_query_parts(_quoted(title), SEARCH_PHRASE_BUY))
    return _dedupe_keep_order(queries)


async def discover_candidates(
    product: dict[str, object],
    *,
    source_domain_value: str,
    provider: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    max_candidates: int,
    run_query: QueryRunner | None = None,
) -> list[DiscoveredCandidate]:
    queries = build_search_queries(product, source_domain_value=source_domain_value)
    if not queries:
        return []
    provider_name = str(provider or product_intelligence_settings.default_search_provider).strip().lower()
    pool_limit = max(
        max_candidates,
        max_candidates * product_intelligence_settings.discovery_pool_multiplier,
    )

    # In-memory execution cache for deduplication during the lifecycle of this discovery pass
    query_cache: dict[str, list[SearchResult]] = {}

    def make_cached_runner(target_runner: QueryRunner) -> QueryRunner:
        async def cached_run_query(q: str, lim: int) -> list[SearchResult]:
            normalized_q = " ".join(q.strip().lower().split())
            if normalized_q in query_cache:
                logger.info("Product Intelligence cache hit for query: %r", q)
                return query_cache[normalized_q]
            res = await target_runner(q, lim)
            query_cache[normalized_q] = res
            return res
        return cached_run_query

    if run_query is not None:
        cached_runner = make_cached_runner(run_query)
        return await _collect_candidates(
            queries=queries,
            run_query=cached_runner,
            product=product,
            source_domain_value=source_domain_value,
            allowed_domains=allowed_domains,
            excluded_domains=excluded_domains,
            max_candidates=max_candidates,
            pool_limit=pool_limit,
        )
    async with shared_query_runner(provider_name) as shared_run_query:
        if shared_run_query is None:
            return []
        cached_runner = make_cached_runner(shared_run_query)
        return await _collect_candidates(
            queries=queries,
            run_query=cached_runner,
            product=product,
            source_domain_value=source_domain_value,
            allowed_domains=allowed_domains,
            excluded_domains=excluded_domains,
            max_candidates=max_candidates,
            pool_limit=pool_limit,
        )


async def _collect_candidates(
    *,
    queries: list[str],
    run_query: QueryRunner,
    product: dict[str, object],
    source_domain_value: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    max_candidates: int,
    pool_limit: int,
) -> list[DiscoveredCandidate]:
    candidates: list[DiscoveredCandidate] = []
    seen: set[str] = set()
    domain_counts: dict[str, int] = {}
    source_domains = _source_excluded_domains(product, source_domain_value)
    source_urls = _source_excluded_urls(product)

    for query_order, query in enumerate(queries):
        results = await run_query(query, pool_limit)
        for rank, result in enumerate(results, start=1):
            normalized_url = clean_result_url(result.url)
            if not normalized_url:
                continue
            # Collapse the same listing offered at multiple sizes/colors (URLs differing only
            # by volatile query params) to one canonical key so a single product at N sizes
            # does not consume N per-product candidate slots.
            dedupe_key = candidate_dedupe_key(normalized_url)
            if dedupe_key in seen:
                continue
            if _same_source_url(normalized_url, source_urls):
                continue
            domain = source_domain(normalized_url)
            if not _domain_allowed(domain, allowed_domains, excluded_domains, source_domains):
                continue
            if not _candidate_matches_product(product, normalized_url, result.payload):
                continue
            if domain_counts.get(domain, 0) >= product_intelligence_settings.max_urls_per_result_domain:
                continue
            seen.add(dedupe_key)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            candidates.append(
                DiscoveredCandidate(
                    url=normalized_url,
                    domain=domain,
                    source_type=classify_source_type(domain, product),
                    query_used=query,
                    search_rank=rank,
                    payload=result.payload,
                    query_order=query_order,
                )
            )
            if len(candidates) >= pool_limit:
                return _rank_discovered_candidates(candidates, product=product)[:max_candidates]
        if (
            product_intelligence_settings.search_delay_ms > 0
            and len(candidates) < pool_limit
            and query_order < len(queries) - 1
        ):
            await asyncio.sleep(product_intelligence_settings.search_delay_ms / 1000)
    return _rank_discovered_candidates(candidates, product=product)[:max_candidates]


@contextlib.asynccontextmanager
async def shared_query_runner(provider: str):
    if provider == SEARCH_PROVIDER_GOOGLE_NATIVE:
        if not real_chrome_browser_available():
            logger.error(
                "Product intelligence google_native discovery requires real Chrome (BROWSER_REAL_CHROME_ENABLED + executable path); refusing to silently downgrade to chromium"
            )
            yield None
            return
        async with _google_native_session() as run:
            yield run
        return

    async def _http_run(query: str, limit: int) -> list[SearchResult]:
        return await _search_results(provider, query, limit=limit)

    yield _http_run

def classify_source_type(domain: str, product: dict[str, object]) -> str:
    normalized_domain = str(domain or "").removeprefix("www.").lower()
    brand_domain = BRAND_DOMAIN_MAP.get(normalize_brand(product.get("brand")))
    if brand_domain and _domain_matches(normalized_domain, brand_domain):
        return SOURCE_TYPE_BRAND_DTC
    if any(_domain_matches(normalized_domain, item) for item in MARKETPLACE_DOMAINS):
        return SOURCE_TYPE_MARKETPLACE
    if any(_domain_matches(normalized_domain, item) for item in AGGREGATOR_DOMAINS):
        return SOURCE_TYPE_AGGREGATOR
    if any(_domain_matches(normalized_domain, item) for item in RETAILER_DOMAINS):
        return SOURCE_TYPE_RETAILER
    return SOURCE_TYPE_UNKNOWN


def _rank_discovered_candidates(
    candidates: list[DiscoveredCandidate],
    *,
    product: dict[str, object] | None = None,
) -> list[DiscoveredCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -int(_identity_token_match(product or {}, _candidate_rank_text(candidate))),
            -int(_candidate_model_token_match(product or {}, candidate)),
            -int(_candidate_has_shopping_group(candidate)),
            -_candidate_title_overlap(product or {}, candidate),
            int(DISCOVERY_SOURCE_TYPE_PRIORITY.get(candidate.source_type, 99)),
            candidate.query_order,
            candidate.search_rank,
        ),
    )


async def _search_results(provider: str, query: str, *, limit: int | None = None) -> list[SearchResult]:
    logger.info("Product intelligence search dispatch provider=%r query=%r limit=%s", provider, query, limit)
    if provider == SEARCH_PROVIDER_SERPAPI:
        if not product_intelligence_settings.serpapi_key:
            logger.warning("Product intelligence SerpAPI discovery skipped: missing API key")
            return []
        return await _search_serpapi(query, limit=limit)
    logger.warning("Product intelligence discovery received unknown provider: %r", provider)
    return []


async def _search_serpapi(query: str, *, limit: int | None = None) -> list[SearchResult]:
    shopping_query = _shopping_query(query)
    brand_scoped_query = _brand_scoped_query(query)

    # 1. Google Shopping is the most precise matching engine. Execute it first.
    shopping_raw = await _search_serpapi_engine(shopping_query, engine=SERPAPI_SHOPPING_ENGINE, limit=limit)
    shopping_results = _parse_serpapi_shopping_results(shopping_raw)
    immersive_results = await _expand_serpapi_immersive_results(shopping_raw, limit=limit)

    dtc_results: list[SearchResult] = []
    if brand_scoped_query:
        dtc_raw = await _search_serpapi_engine(
            brand_scoped_query,
            engine=SERPAPI_ENGINE,
            limit=limit,
        )
        dtc_results = _parse_serpapi_organic_results(dtc_raw)

    results = _dedupe_search_results([*dtc_results, *immersive_results, *shopping_results])

    # 2. Only fallback to broad organic web searches when brand-site lookup
    # did not produce a candidate and shopping coverage still looks thin.
    if len(results) < 2 and not dtc_results:
        organic_raw = await _search_serpapi_engine(shopping_query, engine=SERPAPI_ENGINE, limit=limit)
        organic_results = _parse_serpapi_organic_results(organic_raw)
        results = _dedupe_search_results([*dtc_results, *results, *organic_results])

    return results


def _shopping_query(query: str) -> str:
    natural_tokens = [
        token
        for token in str(query or "").split()
        if not token.lower().startswith(SEARCH_EXCLUDED_DOMAIN_PREFIX)
        and not token.lower().startswith(SEARCH_SITE_PREFIX)
    ]
    return " ".join(natural_tokens).strip() or str(query or "").strip()


def _brand_scoped_query(query: str) -> str:
    tokens = str(query or "").split()
    return str(query or "").strip() if any(token.lower().startswith(SEARCH_SITE_PREFIX) for token in tokens) else ""


def _query_has_identifier(query: str) -> bool:
    for token in str(query or "").split():
        lowered = token.strip().strip('"').casefold()
        if lowered.startswith(SEARCH_SITE_PREFIX) or lowered.startswith(SEARCH_EXCLUDED_DOMAIN_PREFIX):
            continue
        compact = re.sub(r"[^a-z0-9]+", "", lowered)
        if len(compact) >= 5 and any(char.isdigit() for char in compact):
            return True
    return False


async def _empty_search_payload() -> dict[str, object]:
    return {}


async def _search_serpapi_engine(
    query: str,
    *,
    engine: str,
    limit: int | None = None,
) -> dict[str, object]:
    params = {
        SERPAPI_ENGINE_PARAM: engine,
        SERPAPI_QUERY_PARAM: query,
        SERPAPI_KEY_PARAM: product_intelligence_settings.serpapi_key,
    }
    if limit is not None:
        params[SERPAPI_RESULT_COUNT_PARAM] = str(max(1, int(limit)))
    try:
        async with httpx.AsyncClient(timeout=product_intelligence_settings.search_timeout_seconds) as client:
            response = await client.get(SERPAPI_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning("Product intelligence SerpAPI discovery failed engine=%s: %s", engine, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


async def _expand_serpapi_immersive_results(
    payload: dict[str, object],
    *,
    limit: int | None = None,
) -> list[SearchResult]:
    rows = payload.get(SERPAPI_SHOPPING_RESULTS_FIELD)
    if not isinstance(rows, list):
        return []
    max_products = int(product_intelligence_settings.serpapi_immersive_products_per_query)
    if max_products <= 0:
        return []
    results: list[SearchResult] = []
    for item in rows[:max_products]:
        if not isinstance(item, dict):
            continue
        immersive_payload = await _search_serpapi_immersive_product(item)
        if not immersive_payload:
            continue
        results.extend(
            _parse_serpapi_immersive_results(
                immersive_payload,
                parent=item,
                limit=limit,
            )
        )
    return results


async def _search_serpapi_immersive_product(item: dict[str, object]) -> dict[str, object]:
    params = _serpapi_immersive_params(item)
    if not params:
        return {}
    try:
        async with httpx.AsyncClient(timeout=product_intelligence_settings.search_timeout_seconds) as client:
            response = await client.get(SERPAPI_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning("Product intelligence SerpAPI immersive lookup failed: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _serpapi_immersive_params(item: dict[str, object]) -> dict[str, str]:
    api_url = str(item.get(SERPAPI_SHOPPING_IMMERSIVE_API_FIELD) or "").strip()
    page_token = ""  # nosec B105
    if api_url:
        try:
            parsed = urlsplit(api_url)
        except ValueError:
            parsed = None
        if parsed is not None:
            page_token = parse_qs(parsed.query).get(SERPAPI_PAGE_TOKEN_PARAM, [""])[0]
    if not page_token:
        page_token = str(
            item.get(SERPAPI_SHOPPING_IMMERSIVE_TOKEN_FIELD)
            or item.get(SERPAPI_PAGE_TOKEN_PARAM)
            or ""
        ).strip()
    if not page_token:
        return {}
    return {
        SERPAPI_ENGINE_PARAM: SERPAPI_IMMERSIVE_PRODUCT_ENGINE,
        SERPAPI_PAGE_TOKEN_PARAM: page_token,
        SERPAPI_MORE_STORES_PARAM: "true",
        SERPAPI_KEY_PARAM: product_intelligence_settings.serpapi_key,
    }


def _parse_serpapi_organic_results(payload: dict[str, object]) -> list[SearchResult]:
    rows = payload.get(SERPAPI_ORGANIC_RESULTS_FIELD)
    if not isinstance(rows, list):
        return []
    return [
        SearchResult(
            url=str(item.get(SERPAPI_LINK_FIELD) or ""),
            payload={
                "provider": SEARCH_PROVIDER_SERPAPI,
                "title": str(item.get(SERPAPI_TITLE_FIELD) or ""),
                "snippet": str(item.get(SERPAPI_SNIPPET_FIELD) or ""),
                "position": item.get(SERPAPI_POSITION_FIELD),
                "raw": item,
            },
        )
        for item in rows
        if isinstance(item, dict) and item.get(SERPAPI_LINK_FIELD)
    ]


def _parse_serpapi_shopping_results(payload: dict[str, object]) -> list[SearchResult]:
    rows = payload.get(SERPAPI_SHOPPING_RESULTS_FIELD)
    if not isinstance(rows, list):
        return []
    results: list[SearchResult] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = _first_shopping_url(item)
        if not url:
            continue
        results.append(
            SearchResult(
                url=url,
                payload={
                    "provider": "serpapi_shopping",
                    "title": str(item.get(SERPAPI_TITLE_FIELD) or ""),
                    "snippet": str(item.get("snippet") or item.get("extensions") or ""),
                    "source": str(item.get(SERPAPI_SOURCE_FIELD) or ""),
                    "price": item.get("price"),
                    "extracted_price": item.get("extracted_price"),
                    "thumbnail": str(item.get("thumbnail") or ""),
                    "position": item.get(SERPAPI_POSITION_FIELD),
                    "product_id": item.get(SERPAPI_SHOPPING_PRODUCT_ID_FIELD),
                    "product_link": item.get(SERPAPI_SHOPPING_PRODUCT_LINK_FIELD),
                    "serpapi_immersive_product_api": item.get(
                        SERPAPI_SHOPPING_IMMERSIVE_API_FIELD
                    ),
                    "rating": item.get("rating"),
                    "reviews": item.get("reviews"),
                    "delivery": item.get("delivery"),
                    "raw": item,
                },
            )
        )
    return results


def _parse_serpapi_immersive_results(
    payload: dict[str, object],
    *,
    parent: dict[str, object] | None = None,
    limit: int | None = None,
) -> list[SearchResult]:
    parent_data = parent or {}
    product_value = payload.get("product_results")
    product = product_value if isinstance(product_value, dict) else {}
    thumbnails = product.get("thumbnails")
    thumbnail = ""
    if isinstance(thumbnails, list) and thumbnails:
        thumbnail = str(thumbnails[0] or "")
    stores = product.get("stores")
    store_rows = stores if isinstance(stores, list) else []
    results: list[SearchResult] = []

    # Prune product block to prevent heavy recursive variants / video listings duplication inside db entries
    about_value = product.get("about_the_product")
    about_data = about_value if isinstance(about_value, dict) else {}
    pruned_product = {
        "title": product.get("title"),
        "brand": product.get("brand"),
        "rating": product.get("rating"),
        "reviews": product.get("reviews"),
        "description": product.get("description") or about_data.get("description") or "",
    }

    for position, store in enumerate(store_rows, start=1):
        if not isinstance(store, dict):
            continue
        url = clean_result_url(store.get("link"))
        if not url:
            continue
        results.append(
            SearchResult(
                url=url,
                payload={
                    "provider": "serpapi_immersive",
                    "title": str(store.get("title") or product.get("title") or parent_data.get("title") or ""),
                    "snippet": str(product.get("description") or ""),
                    "source": str(store.get("name") or ""),
                    "price": store.get("price"),
                    "extracted_price": store.get("extracted_price"),
                    "thumbnail": thumbnail,
                    "position": position,
                    "product_id": product.get("product_id")
                    or parent_data.get(SERPAPI_SHOPPING_PRODUCT_ID_FIELD),
                    "product_link": parent_data.get(SERPAPI_SHOPPING_PRODUCT_LINK_FIELD),
                    "rating": store.get("rating") or product.get("rating"),
                    "reviews": store.get("reviews") or product.get("reviews"),
                    "delivery": store.get("shipping") or "",
                    "raw": {"store": store, "product": pruned_product, "parent": parent_data},
                },
            )
        )
        if limit is not None and len(results) >= max(1, int(limit)):
            break
    if limit is not None and len(results) >= max(1, int(limit)):
        return results[: max(1, int(limit))]
    about = product.get("about_the_product")
    if isinstance(about, dict):
        about_url = clean_result_url(about.get("link"))
        if about_url:
            results.append(
                SearchResult(
                    url=about_url,
                    payload={
                        "provider": "serpapi_immersive",
                        "title": str(about.get("title") or product.get("title") or ""),
                        "snippet": str(about.get("description") or ""),
                        "source": str(about.get("displayed_link") or ""),
                        "thumbnail": thumbnail,
                        "position": len(results) + 1,
                        "product_id": product.get("product_id")
                        or parent_data.get(SERPAPI_SHOPPING_PRODUCT_ID_FIELD),
                        "product_link": parent_data.get(SERPAPI_SHOPPING_PRODUCT_LINK_FIELD),
                        "raw": {"about_the_product": about, "product": pruned_product, "parent": parent_data},
                    },
                )
            )
    return results


def _first_shopping_url(item: dict[str, object]) -> str:
    for field in SERPAPI_SHOPPING_LINK_FIELDS:
        value = item.get(field)
        if value:
            cleaned = clean_result_url(value)
            if cleaned:
                return cleaned
    return ""


def _dedupe_search_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        cleaned = clean_result_url(result.url)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(SearchResult(url=cleaned, payload=result.payload))
    return deduped


@contextlib.asynccontextmanager
async def _google_native_session():
    """Open one real-Chrome page on google.com and reuse it across multiple queries."""
    runtime = await get_browser_runtime(browser_engine=GOOGLE_NATIVE_BROWSER_ENGINE)
    blocked = False

    async with runtime.page(domain=source_domain(GOOGLE_NATIVE_HOME_URL)) as page:
        async def _run(query: str, limit: int) -> list[SearchResult]:
            nonlocal blocked
            normalized_query = str(query or "").strip()
            if blocked or not normalized_query:
                return []
            result_limit = min(
                max(1, int(limit or product_intelligence_settings.google_native_max_results)),
                int(product_intelligence_settings.google_native_max_results),
            )
            logger.info("Product intelligence search dispatch provider='google_native' query=%r limit=%s", normalized_query, limit)
            try:
                await page.goto(
                    GOOGLE_NATIVE_HOME_URL,
                    wait_until="domcontentloaded",
                    timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS),
                )

                locator_factory = getattr(page, "locator", None)
                if not callable(locator_factory):
                    logger.warning(
                        "Product intelligence native Google query aborted: page locator API unavailable"
                    )
                    return []
                locator = locator_factory(GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR)
                fill = getattr(locator, "fill", None)
                press = getattr(locator, "press", None)
                if not callable(fill) or not callable(press):
                    logger.warning(
                        "Product intelligence native Google query aborted: search input does not support fill/press"
                    )
                    return []
                await fill(normalized_query)
                await press(GOOGLE_NATIVE_SUBMIT_KEY)
                await page.wait_for_timeout(
                    int(GOOGLE_NATIVE_RESULT_WAIT_MS)
                    + int(GOOGLE_NATIVE_TYPING_EXTRA_WAIT_MS)
                )

                html = await get_page_html(page)
                current_url = _page_url(page)
            except Exception as exc:
                logger.warning("Product intelligence native Google query failed: %s", exc)
                return []

            if _google_native_blocked(current_url, html):
                blocked = True
                logger.warning("Product intelligence native Google query blocked by challenge page; stopping searches for this session")
                return []

            return _parse_google_native_results(html, limit=result_limit)

        yield _run


def _google_native_search_url(query: str, limit: int) -> str:
    return (
        f"{GOOGLE_NATIVE_SEARCH_URL}?"
        f"{urlencode({GOOGLE_NATIVE_QUERY_PARAM: query, GOOGLE_NATIVE_RESULT_COUNT_PARAM: str(limit)})}"
    )


def _page_url(page: object) -> str:
    value = getattr(page, "url", "")
    if callable(value):
        try:
            value = value()
        except Exception:
            value = ""
    return str(value or "").strip()


def _google_native_blocked(url: str, html: str) -> bool:
    normalized_url = str(url or "").lower()
    if any(pattern in normalized_url for pattern in GOOGLE_NATIVE_BLOCKED_URL_PATTERNS):
        return True
    normalized_html = str(html or "").lower()
    if any(pattern in normalized_html for pattern in GOOGLE_NATIVE_BLOCKED_HTML_PATTERNS):
        return True
    classification = classify_blocked_page(
        str(html or ""), GOOGLE_NATIVE_BLOCKED_CLASSIFICATION_OFFSET
    )
    return bool(classification.blocked)


def _parse_google_native_results(html: str, *, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()

    for anchor in soup.select(GOOGLE_NATIVE_RESULT_LINK_SELECTOR):
        href = str(anchor.get("href") or "").strip()
        url = _google_native_result_url(href)
        if not url or url in seen:
            continue

        domain = source_domain(url).removeprefix("www.").lower()
        if any(
            _domain_matches(domain, item) for item in GOOGLE_NATIVE_IGNORED_DOMAINS
        ):
            continue
        title = _google_native_anchor_title(anchor, url=url)
        if not title:
            continue
        thumbnail = _google_native_anchor_thumbnail(anchor)

        seen.add(url)
        results.append(
            SearchResult(
                url=url,
                payload={
                    "provider": GOOGLE_NATIVE_PROVIDER_PAYLOAD,
                    "title": title,
                    "snippet": "",
                    "thumbnail": thumbnail,
                    "position": len(results) + 1,
                    "raw": {"href": href, "thumbnail": thumbnail},
                },
            )
        )
        if len(results) >= max(1, int(limit)):
            break

    return results


def _google_native_anchor_title(anchor, *, url: str) -> str:
    heading = anchor.select_one(GOOGLE_NATIVE_TITLE_SELECTOR)
    if heading is not None:
        return clean_text(heading.get_text(" ", strip=True))
    if not looks_like_product_detail_url(url):
        return ""
    for attr in ("aria-label", "title"):
        value = clean_text(anchor.get(attr))
        if value:
            return value
    return clean_text(anchor.get_text(" ", strip=True))


def _google_native_anchor_thumbnail(anchor) -> str:
    parent = anchor
    for _ in range(int(GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH)):
        parent = getattr(parent, "parent", None)
        if parent is None:
            break
        for img in parent.find_all("img"):
            src = str(img.get("src") or img.get("data-src") or "").strip()
            if len(src) >= int(GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH):
                return src
    return ""


def _google_native_result_url(href: str) -> str:
    raw = str(href or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if (
            (host == "google.com" or host.endswith(".google.com"))
            and parsed.path == GOOGLE_NATIVE_REDIRECT_PATH
        ):
            target = parse_qs(parsed.query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
            return clean_result_url(target)
        return clean_result_url(raw)
    if raw.startswith(GOOGLE_NATIVE_REDIRECT_PATH):
        target = parse_qs(urlsplit(raw).query).get(GOOGLE_NATIVE_REDIRECT_TARGET_PARAM, [""])[0]
        return clean_result_url(target)
    if raw.startswith("/"):
        return clean_result_url(urljoin(GOOGLE_NATIVE_HOME_URL, raw))
    return ""


def _candidate_matches_product(
    product: dict[str, object],
    url: str,
    payload: dict[str, object] | None,
) -> bool:
    if not looks_like_product_detail_url(url):
        return False
    result_text = _search_result_text(payload)
    candidate_text = " ".join(part for part in (result_text, url) if part)
    if _identity_token_match(product, candidate_text):
        return True
    if _has_conflicting_numeric_identity(product, result_text):
        return False
    return not _title_mismatch(product, result_text or url)


def _search_result_text(payload: dict[str, object] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    raw_value = data.get("raw")
    raw = raw_value if isinstance(raw_value, dict) else {}
    values = [
        data.get("title"),
        data.get("snippet"),
        data.get("source"),
        raw.get("title"),
        raw.get("snippet"),
        raw.get("displayed_link"),
        raw.get("source"),
    ]
    return " ".join(str(value or "") for value in values).strip()


def _identity_token_match(product: dict[str, object], candidate_text: object) -> bool:
    source_tokens = _identity_tokens(
        product.get("title"),
        product.get("sku"),
        product.get("mpn"),
        product.get("gtin"),
    )
    # The manufacturer style core (e.g. "fv5285") decomposed from a composite SKU is the
    # cross-retailer identity key. A naive token match misses it because the source SKU
    # ("3900462fv5285") carries a retailer prefix while candidates state it bare or with a
    # colorway suffix ("fv5285-002"). Add the decomposed code on both sides.
    source_codes = _style_code_tokens(
        product.get("style_code"),
        manufacturer_style_code(
            product.get("sku"),
            product.get("style"),
            product.get("mpn"),
            gtin_value=product.get("gtin"),
        ),
    )
    source_tokens |= source_codes
    if not source_tokens:
        return False
    candidate_tokens = _identity_tokens(candidate_text)
    candidate_tokens |= _style_code_tokens(manufacturer_style_code(candidate_text))
    return bool(source_tokens & candidate_tokens)


def _style_code_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in str(value or "").casefold().split():
            if token:
                tokens.add(token)
    return tokens


def _has_conflicting_numeric_identity(
    product: dict[str, object],
    candidate_text: object,
) -> bool:
    source_tokens = _identity_tokens(
        product.get("title"),
        product.get("sku"),
        product.get("mpn"),
        product.get("gtin"),
    )
    candidate_tokens = _identity_tokens(candidate_text)
    return bool(source_tokens and candidate_tokens and not (source_tokens & candidate_tokens))


def _identity_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        raw = str(value or "").casefold()
        parts = [
            token
            for token in re.split(r"[^a-z0-9]+", raw)
            if token
        ]
        compact = re.sub(r"[^a-z0-9]+", "", raw)
        if (
            1 < len(parts) <= 3
            and len(compact) >= 5
            and any(char.isdigit() for char in compact)
        ):
            tokens.add(compact)
        for token in parts:
            if len(token) >= 3 and any(char.isdigit() for char in token):
                tokens.add(token)
    return tokens


def _title_mismatch(product: dict[str, object], candidate_text: object) -> bool:
    source_tokens = _distinctive_title_tokens(
        product.get("title"),
        product.get("brand"),
    )
    candidate_tokens = _distinctive_title_tokens(
        candidate_text,
        product.get("brand"),
    )
    minimum = int(DISCOVERY_TITLE_MISMATCH_MIN_DISTINCTIVE_TOKENS)
    if len(source_tokens) < minimum or len(candidate_tokens) < minimum:
        return False
    overlap = len(source_tokens & candidate_tokens) / max(
        min(len(source_tokens), len(candidate_tokens)),
        1,
    )
    return overlap < float(DISCOVERY_TITLE_MISMATCH_MIN_OVERLAP_RATIO)


def _distinctive_title_tokens(title: object, brand: object) -> set[str]:
    brand_tokens = _text_tokens(normalize_brand(brand))
    return {
        token
        for token in _text_tokens(title)
        if token not in brand_tokens and token not in DISCOVERY_GENERIC_PRODUCT_TOKENS
    }


def _text_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    for token in re.split(r"[^a-z0-9]+", str(value or "").casefold()):
        if len(token) <= 1:
            continue
        normalized = token[:-1] if token.endswith("s") and len(token) > 3 else token
        if normalized:
            tokens.add(normalized)
    return tokens


def _domain_allowed(
    domain: str,
    allowed_domains: list[str],
    excluded_domains: list[str],
    source_domains: set[str],
) -> bool:
    normalized = domain.removeprefix("www.").lower()
    if not normalized:
        return False
    excluded = {item.removeprefix("www.").lower() for item in excluded_domains if item}
    excluded.update(item.removeprefix("www.").lower() for item in source_domains if item)
    if any(_domain_matches(normalized, item) for item in excluded):
        return False
    allowed = {item.removeprefix("www.").lower() for item in allowed_domains if item}
    return not allowed or any(_domain_matches(normalized, item) for item in allowed)


def _source_excluded_domains(
    product: dict[str, object],
    source_domain_value: str,
) -> set[str]:
    domains = {str(source_domain_value or "").removeprefix("www.").lower()}
    for url in _source_url_values(product):
        domains.add(source_domain(url))
    return {domain for domain in domains if domain}


def _source_excluded_urls(product: dict[str, object]) -> set[str]:
    return {
        normalized
        for normalized in (normalized_compare_url(url) for url in _source_url_values(product))
        if normalized
    }


def _source_url_values(product: dict[str, object]) -> list[object]:
    values: list[object] = [
        product.get("url"),
        product.get("source_url"),
        product.get("canonical_url"),
        product.get("product_url"),
    ]
    raw = product.get("raw")
    if isinstance(raw, dict):
        values.extend(
            raw.get(key)
            for key in ("url", "source_url", "canonical_url", "product_url")
        )
    return values


def _same_source_url(candidate_url: str, source_urls: set[str]) -> bool:
    return bool(source_urls and normalized_compare_url(candidate_url) in source_urls)


def _domain_matches(normalized_domain: str, target: str) -> bool:
    normalized_target = str(target or "").removeprefix("www.").lower()
    return bool(
        normalized_target
        and (
            normalized_domain == normalized_target
            or normalized_domain.endswith(f".{normalized_target}")
        )
    )


def _title_without_brand(title: object, *brand_variants: object) -> str:
    normalized_title = _query_text(title)
    if not normalized_title:
        return ""
    for brand_variant in brand_variants:
        trimmed = _strip_query_prefix(normalized_title, _query_text(brand_variant))
        if trimmed != normalized_title:
            return _limit_query_tokens(trimmed)
    return _limit_query_tokens(normalized_title)


def _identity_field(product: dict[str, object], key: str) -> str:
    return str(product.get(key) or "").strip()


def _query_text(value: object) -> str:
    return clean_text(value).strip()


def _strip_query_prefix(text: str, prefix: str) -> str:
    normalized_text = str(text or "").strip()
    normalized_prefix = str(prefix or "").strip()
    if not normalized_text or not normalized_prefix:
        return normalized_text
    if not normalized_text.casefold().startswith(normalized_prefix.casefold()):
        return normalized_text
    trimmed = normalized_text[len(normalized_prefix) :].lstrip(" -\u2013\u2014:/|,")
    return trimmed or normalized_text


def _limit_query_tokens(text: str) -> str:
    tokens = str(text or "").split()
    if not tokens:
        return ""
    return " ".join(tokens[: product_intelligence_settings.title_token_limit])


def _query_identifier_value(product: dict[str, object]) -> str:
    mpn = _identity_field(product, "mpn")
    if mpn:
        return mpn
    # Prefer the decomposed manufacturer style core (e.g. "FV5285") over a raw composite
    # retailer SKU ("3900462FV5285"): external retailers index by the bare manufacturer code,
    # so the composite would not match. Fall back to a manufacturer-looking style/product_id.
    style_core = manufacturer_style_code(
        product.get("style_code"),
        product.get("sku"),
        product.get("style"),
        product.get("product_id"),
        gtin_value=product.get("gtin"),
    )
    if style_core:
        # A title may yield more than one code; use the first deterministic token.
        return style_core.split()[0]
    for key in ("style", "product_id"):
        value = _identity_field(product, key)
        if _looks_like_manufacturer_identifier(value):
            return value
    return ""


def _looks_like_manufacturer_identifier(value: object) -> bool:
    text = str(value or "").strip()
    compact = re.sub(r"[^a-z0-9]+", "", text.casefold())
    return bool(compact and any(char.isalpha() for char in compact) and any(char.isdigit() for char in compact))


def _query_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if token
    ]


def _candidate_rank_text(candidate: DiscoveredCandidate) -> str:
    return " ".join(part for part in (_search_result_text(candidate.payload), candidate.url) if part)


def _candidate_has_shopping_group(candidate: DiscoveredCandidate) -> bool:
    payload = candidate.payload if isinstance(candidate.payload, dict) else {}
    provider = str(payload.get("provider") or "").casefold()
    return provider in {"serpapi_shopping", "serpapi_immersive"} and bool(
        payload.get("product_id") or payload.get("product_link")
    )


def _candidate_title_overlap(
    product: dict[str, object],
    candidate: DiscoveredCandidate,
) -> float:
    source_tokens = _distinctive_title_tokens(product.get("title"), product.get("brand"))
    candidate_tokens = _distinctive_title_tokens(_candidate_rank_text(candidate), product.get("brand"))
    if not source_tokens or not candidate_tokens:
        return 0.0
    return len(source_tokens & candidate_tokens) / max(min(len(source_tokens), len(candidate_tokens)), 1)


def _candidate_model_token_match(
    product: dict[str, object],
    candidate: DiscoveredCandidate,
) -> bool:
    source_tokens = _distinctive_title_tokens(product.get("title"), product.get("brand"))
    candidate_tokens = _distinctive_title_tokens(_candidate_rank_text(candidate), product.get("brand"))
    return bool(source_tokens and candidate_tokens and source_tokens & candidate_tokens)


def _quoted(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.replace('"', '\\"').split())
    return f"\"{text}\"" if text else ""


def _join_query_parts(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


google_native_blocked = _google_native_blocked
google_native_session = _google_native_session
parse_google_native_results = _parse_google_native_results
parse_serpapi_shopping_results = _parse_serpapi_shopping_results
parse_serpapi_immersive_results = _parse_serpapi_immersive_results
