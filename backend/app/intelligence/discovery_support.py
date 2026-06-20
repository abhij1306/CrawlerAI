from __future__ import annotations

import contextlib
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.acquisition.browser_runtime import get_browser_runtime
from app.acquisition.dom_runtime import get_page_html
from app.acquisition.runtime import classify_blocked_page
from app.core.config.product_intelligence import (
    DISCOVERY_GENERIC_PRODUCT_TOKENS,
    DISCOVERY_TITLE_MISMATCH_MIN_DISTINCTIVE_TOKENS,
    DISCOVERY_TITLE_MISMATCH_MIN_OVERLAP_RATIO,
    GOOGLE_NATIVE_BLOCKED_CLASSIFICATION_OFFSET,
    GOOGLE_NATIVE_BLOCKED_HTML_PATTERNS,
    GOOGLE_NATIVE_BLOCKED_URL_PATTERNS,
    GOOGLE_NATIVE_BROWSER_ENGINE,
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
from app.core.shared.field_coerce import clean_text
from app.intelligence.candidate_urls import (
    clean_result_url,
    looks_like_product_detail_url,
    normalized_compare_url,
)
from app.intelligence.discovery_types import SearchResult
from app.intelligence.matching import manufacturer_style_code, normalize_brand, source_domain

if TYPE_CHECKING:
    from app.intelligence.discovery import DiscoveredCandidate


logger = logging.getLogger(__name__)


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
