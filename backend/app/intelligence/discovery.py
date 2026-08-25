from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

import httpx
from app.acquisition.browser_runtime import (
    get_browser_runtime,
    real_chrome_browser_available,
)
from app.acquisition.dom_runtime import get_page_html
from app.core.config.product_intelligence import (
    AGGREGATOR_DOMAINS,
    BRAND_DOMAIN_MAP,
    DISCOVERY_SOURCE_TYPE_PRIORITY,
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
    product_intelligence_settings,
)
from app.intelligence.candidate_urls import candidate_dedupe_key, clean_result_url
from app.intelligence.discovery_support import (
    DiscoveredCandidate,
    _candidate_has_shopping_group,
    _candidate_matches_product,
    _candidate_model_token_match,
    _candidate_rank_text,
    _candidate_title_overlap,
    _dedupe_keep_order,
    _domain_allowed,
    _domain_matches,
    _google_native_blocked,
    _google_native_session,
    _identity_field,
    _identity_token_match,
    _join_query_parts,
    _query_identifier_value,
    _same_source_url,
    _source_excluded_domains,
    _source_excluded_urls,
    _title_without_brand,
    _parse_google_native_results,
    _quoted,
    SearchResult,
)
from app.intelligence.matching import normalize_brand, source_domain

logger = logging.getLogger(__name__)

QueryRunner = Callable[[str, int], Awaitable[list["SearchResult"]]]


def build_search_queries(
    product: dict[str, object],
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
            queries.append(
                _join_query_parts(brand_query, title, _quoted(query_identifier))
            )
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
    queries = build_search_queries(product)
    if not queries:
        return []
    provider_name = (
        str(provider or product_intelligence_settings.default_search_provider)
        .strip()
        .lower()
    )
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
            admitted = _admit_candidate(
                result,
                query=query,
                rank=rank,
                query_order=query_order,
                product=product,
                seen=seen,
                source_urls=source_urls,
                source_domains=source_domains,
                allowed_domains=allowed_domains,
                excluded_domains=excluded_domains,
                domain_counts=domain_counts,
            )
            if admitted is None:
                continue
            dedupe_key, candidate = admitted
            seen.add(dedupe_key)
            domain_counts[candidate.domain] = domain_counts.get(candidate.domain, 0) + 1
            candidates.append(candidate)
            if len(candidates) >= pool_limit:
                return _rank_discovered_candidates(candidates, product=product)[
                    :max_candidates
                ]
        if (
            product_intelligence_settings.search_delay_ms > 0
            and len(candidates) < pool_limit
            and query_order < len(queries) - 1
        ):
            await asyncio.sleep(product_intelligence_settings.search_delay_ms / 1000)
    return _rank_discovered_candidates(candidates, product=product)[:max_candidates]


def _admit_candidate(
    result: SearchResult,
    *,
    query: str,
    rank: int,
    query_order: int,
    product: dict[str, object],
    seen: set[str],
    source_urls: set[str],
    source_domains: set[str],
    allowed_domains: list[str],
    excluded_domains: list[str],
    domain_counts: dict[str, int],
) -> tuple[str, DiscoveredCandidate] | None:
    normalized_url = clean_result_url(result.url)
    if not normalized_url or _same_source_url(normalized_url, source_urls):
        return None
    dedupe_key = candidate_dedupe_key(normalized_url)
    if dedupe_key in seen:
        return None
    domain = source_domain(normalized_url)
    if not _domain_allowed(domain, allowed_domains, excluded_domains, source_domains):
        return None
    if not _candidate_matches_product(product, normalized_url, result.payload):
        return None
    if (
        domain_counts.get(domain, 0)
        >= product_intelligence_settings.max_urls_per_result_domain
    ):
        return None
    return dedupe_key, DiscoveredCandidate(
        url=normalized_url,
        domain=domain,
        source_type=classify_source_type(domain, product),
        query_used=query,
        search_rank=rank,
        payload=result.payload,
        query_order=query_order,
    )


@contextlib.asynccontextmanager
async def shared_query_runner(provider: str):
    if provider == SEARCH_PROVIDER_GOOGLE_NATIVE:
        if not real_chrome_browser_available():
            logger.error(
                "Product intelligence google_native discovery requires real Chrome (BROWSER_REAL_CHROME_ENABLED + executable path); refusing to silently downgrade to chromium"
            )
            yield None
            return
        async with google_native_session() as run:
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


async def _search_results(
    provider: str, query: str, *, limit: int | None = None
) -> list[SearchResult]:
    logger.info(
        "Product intelligence search dispatch provider=%r query=%r limit=%s",
        provider,
        query,
        limit,
    )
    if provider == SEARCH_PROVIDER_SERPAPI:
        if not product_intelligence_settings.serpapi_key:
            logger.warning(
                "Product intelligence SerpAPI discovery skipped: missing API key"
            )
            return []
        return await _search_serpapi(query, limit=limit)
    logger.warning(
        "Product intelligence discovery received unknown provider: %r", provider
    )
    return []


async def _search_serpapi(
    query: str, *, limit: int | None = None
) -> list[SearchResult]:
    shopping_query = _shopping_query(query)
    brand_scoped_query = _brand_scoped_query(query)

    # 1. Google Shopping is the most precise matching engine. Execute it first.
    shopping_raw = await _search_serpapi_engine(
        shopping_query, engine=SERPAPI_SHOPPING_ENGINE, limit=limit
    )
    shopping_results = _parse_serpapi_shopping_results(shopping_raw)
    immersive_results = await _expand_serpapi_immersive_results(
        shopping_raw, limit=limit
    )

    dtc_results: list[SearchResult] = []
    if brand_scoped_query:
        dtc_raw = await _search_serpapi_engine(
            brand_scoped_query,
            engine=SERPAPI_ENGINE,
            limit=limit,
        )
        dtc_results = _parse_serpapi_organic_results(dtc_raw)

    results = _dedupe_search_results(
        [*dtc_results, *immersive_results, *shopping_results]
    )

    # 2. Only fallback to broad organic web searches when brand-site lookup
    # did not produce a candidate and shopping coverage still looks thin.
    if len(results) < 2 and not dtc_results:
        organic_raw = await _search_serpapi_engine(
            shopping_query, engine=SERPAPI_ENGINE, limit=limit
        )
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
    return (
        str(query or "").strip()
        if any(token.lower().startswith(SEARCH_SITE_PREFIX) for token in tokens)
        else ""
    )


def _query_has_identifier(query: str) -> bool:
    for token in str(query or "").split():
        lowered = token.strip().strip('"').casefold()
        if lowered.startswith(SEARCH_SITE_PREFIX) or lowered.startswith(
            SEARCH_EXCLUDED_DOMAIN_PREFIX
        ):
            continue
        compact = re.sub(r"[^a-z0-9]+", "", lowered)
        if len(compact) >= 5 and any(char.isdigit() for char in compact):
            return True
    return False


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
        async with httpx.AsyncClient(
            timeout=product_intelligence_settings.search_timeout_seconds
        ) as client:
            response = await client.get(SERPAPI_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning(
            "Product intelligence SerpAPI discovery failed engine=%s: %s", engine, exc
        )
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
    max_products = int(
        product_intelligence_settings.serpapi_immersive_products_per_query
    )
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


async def _search_serpapi_immersive_product(
    item: dict[str, object],
) -> dict[str, object]:
    params = _serpapi_immersive_params(item)
    if not params:
        return {}
    try:
        async with httpx.AsyncClient(
            timeout=product_intelligence_settings.search_timeout_seconds
        ) as client:
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
    max_results = max(1, int(limit)) if limit is not None else None
    product_value = payload.get("product_results")
    product = product_value if isinstance(product_value, dict) else {}
    thumbnail = _immersive_thumbnail(product)
    store_rows = _dict_rows(product.get("stores"))
    results: list[SearchResult] = []
    pruned_product = _pruned_immersive_product(product)
    for position, store in enumerate(store_rows, start=1):
        result = _immersive_store_result(
            store,
            position=position,
            product=product,
            parent=parent_data,
            thumbnail=thumbnail,
            pruned_product=pruned_product,
        )
        if result is not None:
            results.append(result)
        if _result_limit_reached(results, max_results):
            break
    if _result_limit_reached(results, max_results):
        return results[:max_results]
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
                        "product_link": parent_data.get(
                            SERPAPI_SHOPPING_PRODUCT_LINK_FIELD
                        ),
                        "raw": {
                            "about_the_product": about,
                            "product": pruned_product,
                            "parent": parent_data,
                        },
                    },
                )
            )
    return results


def _result_limit_reached(results: list[SearchResult], max_results: int | None) -> bool:
    return max_results is not None and len(results) >= max_results


def _immersive_thumbnail(product: dict[str, object]) -> str:
    thumbnails = product.get("thumbnails")
    if not isinstance(thumbnails, list) or not thumbnails:
        return ""
    return str(thumbnails[0] or "")


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _pruned_immersive_product(product: dict[str, object]) -> dict[str, object]:
    about_value = product.get("about_the_product")
    about = about_value if isinstance(about_value, dict) else {}
    return {
        "title": product.get("title"),
        "brand": product.get("brand"),
        "rating": product.get("rating"),
        "reviews": product.get("reviews"),
        "description": product.get("description") or about.get("description") or "",
    }


def _immersive_store_result(
    store: dict[str, object],
    *,
    position: int,
    product: dict[str, object],
    parent: dict[str, object],
    thumbnail: str,
    pruned_product: dict[str, object],
) -> SearchResult | None:
    url = clean_result_url(store.get("link"))
    if not url:
        return None
    return SearchResult(
        url=url,
        payload={
            "provider": "serpapi_immersive",
            "title": str(
                store.get("title") or product.get("title") or parent.get("title") or ""
            ),
            "snippet": str(product.get("description") or ""),
            "source": str(store.get("name") or ""),
            "price": store.get("price"),
            "extracted_price": store.get("extracted_price"),
            "thumbnail": thumbnail,
            "position": position,
            "product_id": product.get("product_id")
            or parent.get(SERPAPI_SHOPPING_PRODUCT_ID_FIELD),
            "product_link": parent.get(SERPAPI_SHOPPING_PRODUCT_LINK_FIELD),
            "rating": store.get("rating") or product.get("rating"),
            "reviews": store.get("reviews") or product.get("reviews"),
            "delivery": store.get("shipping") or "",
            "raw": {"store": store, "product": pruned_product, "parent": parent},
        },
    )


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


google_native_blocked = _google_native_blocked
parse_google_native_results = _parse_google_native_results
parse_serpapi_shopping_results = _parse_serpapi_shopping_results
parse_serpapi_immersive_results = _parse_serpapi_immersive_results


@contextlib.asynccontextmanager
async def google_native_session():
    # Getters are passed through (not read inside discovery_support) so test
    # monkeypatches on ``app.intelligence.discovery.get_browser_runtime`` /
    # ``get_page_html`` still take effect.
    async with _google_native_session(
        browser_runtime_getter=get_browser_runtime,
        page_html_getter=get_page_html,
    ) as run_query:
        yield run_query
