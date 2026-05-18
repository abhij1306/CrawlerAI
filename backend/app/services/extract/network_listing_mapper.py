from __future__ import annotations

__all__ = (
    "backfill_listing_rows_from_network",
    "extract_listing_rows_from_network",
    "listing_identity_from_url",
)

import re
from typing import Any
from urllib.parse import urlsplit

from app.services.config.extraction_rules import (
    LISTING_NETWORK_BACKFILL_FIELDS,
    LISTING_NETWORK_BRAND_CANDIDATE_KEYS,
    LISTING_NETWORK_DIRECT_PRICE_KEYS,
    LISTING_NETWORK_FALLBACK_PRICE_KEYS,
    LISTING_NETWORK_ID_KEYS,
    LISTING_NETWORK_PRICE_BUCKETS,
    LISTING_NETWORK_PRICE_CANDIDATE_KEYS,
    LISTING_NETWORK_PRIMARY_PRICE_KEYS,
    LISTING_NETWORK_TITLE_KEYS,
)
from app.services.extract.field_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    coerce_text,
    finalize_record,
    surface_alias_lookup,
)


def backfill_listing_rows_from_network(
    rows: list[dict],
    *,
    network_payloads: list[dict[str, object]] | None,
) -> None:
    if not rows or not network_payloads:
        return
    fields_by_id, fields_by_title = _listing_network_backfill_maps(network_payloads)
    if not fields_by_id and not fields_by_title:
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(
            row.get(field_name) not in (None, "", [], {})
            for field_name in LISTING_NETWORK_BACKFILL_FIELDS
        ):
            continue
        candidate = None
        row_url = str(row.get("url") or "").strip()
        row_id = listing_identity_from_url(row_url)
        if row_id:
            candidate = fields_by_id.get(row_id)
        if candidate is None:
            row_title = clean_text(row.get("title"))
            if row_title:
                candidate = fields_by_title.get(row_title.lower())
        if not isinstance(candidate, dict):
            continue
        price = candidate.get("price")
        currency = candidate.get("currency")
        brand = candidate.get("brand")
        if price not in (None, "", [], {}) and row.get("price") in (None, "", [], {}):
            row["price"] = price
        if currency not in (None, "", [], {}) and row.get("currency") in (
            None,
            "",
            [],
            {},
        ):
            row["currency"] = currency
        if brand not in (None, "", [], {}) and row.get("brand") in (None, "", [], {}):
            row["brand"] = brand


def extract_listing_rows_from_network(
    network_payloads: list[dict[str, object]] | None,
    *,
    page_url: str,
    surface: str,
    max_records: int,
) -> list[dict[str, Any]]:
    if not network_payloads:
        return []
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for payload in list(network_payloads):
        body = payload.get("body") if isinstance(payload, dict) else None
        for candidate in _iter_listing_price_candidates(body):
            row = _network_listing_row(candidate, page_url=page_url, surface=surface)
            url = str(row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            rows.append(row)
            if len(rows) >= max_records:
                return rows
    return rows


def _network_listing_row(
    candidate: dict[str, Any],
    *,
    page_url: str,
    surface: str,
) -> dict[str, Any]:
    title = _first_candidate_text(candidate, LISTING_NETWORK_TITLE_KEYS)
    url = _network_listing_url(candidate, page_url=page_url)
    if not title or not url:
        return {}
    row: dict[str, Any] = {
        "source_url": page_url,
        "_source": "network_listing",
        "title": title,
        "url": url,
    }
    product_id = clean_text(
        candidate.get("productId") or candidate.get("product_id") or candidate.get("id")
    )
    if product_id:
        row["product_id"] = product_id
    description = coerce_text(
        candidate.get("shortDescription") or candidate.get("description")
    )
    if description:
        row["description"] = description
    image_url = _network_listing_image_url(candidate, page_url=page_url)
    if image_url:
        row["image_url"] = image_url
    review = candidate.get("review")
    if isinstance(review, dict):
        if review.get("rating") not in (None, "", [], {}):
            row["rating"] = review.get("rating")
        if review.get("count") not in (None, "", [], {}):
            row["review_count"] = review.get("count")
    row.update(
        _listing_candidate_backfill_entry(
            candidate,
            alias_lookup=surface_alias_lookup(surface, None),
        )
    )
    return finalize_record(row, surface=surface)


def _network_listing_url(candidate: dict[str, Any], *, page_url: str) -> str:
    for key in ("url", "link", "href", "permalink"):
        resolved = absolute_url(page_url, candidate.get(key))
        if resolved:
            return resolved
    slug = clean_text(candidate.get("slug") or candidate.get("handle"))
    if not slug:
        return ""
    if re.match(r"^https?://", slug, re.I):
        return slug
    if slug.startswith("/"):
        return absolute_url(page_url, slug) or ""
    parsed = urlsplit(page_url)
    origin = (
        f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme and parsed.netloc
        else page_url
    )
    return absolute_url(origin, f"/{slug}") or ""


def _network_listing_image_url(candidate: dict[str, Any], *, page_url: str) -> str:
    for key in ("image", "image_url", "imageUrl", "thumbnail", "hoverImage"):
        resolved = _image_url_from_value(candidate.get(key), page_url=page_url)
        if resolved:
            return resolved
    colour_options = candidate.get("colourOptions") or candidate.get("colorOptions")
    if isinstance(colour_options, list):
        for option in colour_options:
            if not isinstance(option, dict):
                continue
            for key in ("image", "thumbnail", "hoverImage"):
                resolved = _image_url_from_value(option.get(key), page_url=page_url)
                if resolved:
                    return resolved
    return ""


def _image_url_from_value(value: object, *, page_url: str) -> str:
    if isinstance(value, dict):
        for key in ("url", "src", "href"):
            resolved = absolute_url(page_url, value.get(key))
            if resolved:
                return resolved
    return absolute_url(page_url, value) or ""


def _listing_network_backfill_maps(
    network_payloads: list[dict[str, object]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_id: dict[str, dict[str, str]] = {}
    by_title: dict[str, dict[str, str]] = {}
    alias_lookup = surface_alias_lookup("ecommerce_listing", None)
    for payload in list(network_payloads):
        body = payload.get("body")
        for candidate in _iter_listing_price_candidates(body):
            entry = _listing_candidate_backfill_entry(
                candidate, alias_lookup=alias_lookup
            )
            if not entry:
                continue
            identifier = _first_candidate_text(candidate, LISTING_NETWORK_ID_KEYS)
            if identifier:
                by_id[identifier.lower()] = entry
            title = _first_candidate_text(candidate, LISTING_NETWORK_TITLE_KEYS)
            if title:
                by_title[title.lower()] = entry
    return by_id, by_title


def _iter_listing_price_candidates(
    value: object, *, depth: int = 0
) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(
            key in value
            for key in (
                *LISTING_NETWORK_PRICE_CANDIDATE_KEYS,
                *LISTING_NETWORK_BRAND_CANDIDATE_KEYS,
            )
        ) and any(
            key in value
            for key in (
                *LISTING_NETWORK_TITLE_KEYS,
                *LISTING_NETWORK_ID_KEYS,
            )
        ):
            rows.append(value)
        for item in value.values():
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
        return rows
    if isinstance(value, list):
        for item in value[:200]:
            rows.extend(_iter_listing_price_candidates(item, depth=depth + 1))
    return rows


def _first_candidate_text(candidate: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = clean_text(candidate.get(key))
        if value:
            return value
    return ""


def _listing_candidate_backfill_entry(
    candidate: dict[str, Any],
    *,
    alias_lookup: dict[str, str],
) -> dict[str, str]:
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(candidate, alias_lookup, "", candidates)
    entry: dict[str, str] = {}
    brand = finalize_candidate_value("brand", candidates.get("brand", []))
    if brand not in (None, "", [], {}):
        entry["brand"] = str(brand)
    price = _listing_candidate_price(candidate)
    if price:
        entry["price"] = price
    currency = _listing_candidate_currency(candidate)
    if currency:
        entry["currency"] = currency
    return entry


def _listing_candidate_price(candidate: dict[str, Any]) -> str | None:
    currency = _listing_candidate_currency(candidate)
    raw_price = _listing_candidate_raw_price(candidate)
    if raw_price in (None, "", [], {}):
        return None
    digits_only = re.sub(r"\D+", "", str(raw_price))
    return normalize_decimal_price(
        raw_price,
        interpret_integral_as_cents=(
            "." not in str(raw_price)
            and len(digits_only) >= 4
            and currency in {"AUD", "CAD", "EUR", "GBP", "NZD", "USD"}
        ),
    )


def _listing_candidate_raw_price(candidate: dict[str, Any]) -> object | None:
    prices = candidate.get("prices")
    price_range = candidate.get("priceRange")
    offers = candidate.get("offers")
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), None)
    for key in LISTING_NETWORK_DIRECT_PRICE_KEYS:
        if candidate.get(key) not in (None, "", [], {}):
            return candidate.get(key)
    if isinstance(prices, dict):
        for bucket_name in LISTING_NETWORK_PRICE_BUCKETS:
            bucket = prices.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            for key in ("value", *LISTING_NETWORK_PRIMARY_PRICE_KEYS):
                if bucket.get(key) not in (None, "", [], {}):
                    return bucket.get(key)
            for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
                if bucket.get(key) not in (None, "", [], {}):
                    return bucket.get(key)
        for key in LISTING_NETWORK_PRIMARY_PRICE_KEYS:
            if prices.get(key) not in (None, "", [], {}):
                return prices.get(key)
        for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
            if prices.get(key) not in (None, "", [], {}):
                return prices.get(key)
    if isinstance(price_range, dict):
        for key in LISTING_NETWORK_PRIMARY_PRICE_KEYS:
            if price_range.get(key) not in (None, "", [], {}):
                return price_range.get(key)
        for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
            if price_range.get(key) not in (None, "", [], {}):
                return price_range.get(key)
    if isinstance(offers, dict):
        for key in LISTING_NETWORK_PRIMARY_PRICE_KEYS:
            if offers.get(key) not in (None, "", [], {}):
                return offers.get(key)
        for key in LISTING_NETWORK_FALLBACK_PRICE_KEYS:
            if offers.get(key) not in (None, "", [], {}):
                return offers.get(key)
    return None


def _listing_candidate_currency(candidate: dict[str, Any]) -> str | None:
    prices = candidate.get("prices")
    price_range = candidate.get("priceRange")
    if isinstance(prices, dict):
        for bucket_name in LISTING_NETWORK_PRICE_BUCKETS:
            bucket = prices.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            code = _listing_currency_code(bucket.get("currency"))
            if code:
                return code
        code = _listing_currency_code(prices.get("currency"))
        if code:
            return code
        for key in ("currencyCode", "priceCurrency"):
            code = clean_text(prices.get(key))
            if code:
                return code
    if isinstance(price_range, dict):
        for key in ("currency", "currencyCode", "priceCurrency"):
            code = _listing_currency_code(price_range.get(key))
            if code:
                return code
    offers = candidate.get("offers")
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), None)
    if isinstance(offers, dict):
        code = clean_text(offers.get("priceCurrency"))
        if code:
            return code
    return (
        clean_text(candidate.get("currency") or candidate.get("currencyCode")) or None
    )


def _listing_currency_code(value: object) -> str | None:
    if isinstance(value, dict):
        return clean_text(value.get("code") or value.get("currencyCode"))
    return clean_text(value) or None


def listing_identity_from_url(url: str) -> str:
    """Extract listing identity from URL.

    Matches retailer SKU paths like /products/A123456-789/ -> a123456-789.
    Falls back to the terminal path segment for feeds without that SKU shape.
    """
    if not url:
        return ""
    path = urlsplit(url).path
    match = re.search(r"/([A-Z]\d{6}-\d{3})(?:/|$)", path)
    if match is not None:
        return match.group(1).lower()
    match = re.search(r"/([^/?#]+)/?$", path)
    segment = str(match.group(1) if match is not None else "").strip().lower()
    if not segment:
        return ""
    return re.sub(r"\.(?:html?|php|aspx?)$", "", segment)
