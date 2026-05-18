from __future__ import annotations

__all__ = (
    "extract_structured_listing",
    "allow_embedded_json_listing_payloads",
)

import re
from typing import Any, Iterator
from urllib.parse import urlsplit

from app.services.config.extraction_rules import LISTING_NAVIGATION_TITLE_HINTS
from app.services.extract.detail.identity.core import listing_url_is_structural
from app.services.extract.listing_record_finalizer import finalize_listing_price_fields
from app.services.extract.field_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    coerce_text,
    finalize_record,
    is_title_noise,
    same_host,
    surface_alias_lookup,
    surface_fields,
)
from app.services.shared.url_utils import extract_urls


def _structured_listing_record(
    payload: dict[str, Any],
    page_url: str,
    surface: str,
) -> dict[str, Any]:
    alias_lookup = surface_alias_lookup(surface, None)
    candidates: dict[str, list[object]] = {}
    collect_structured_candidates(payload, alias_lookup, page_url, candidates)
    record: dict[str, Any] = {
        "source_url": page_url,
        "_source": "structured_listing",
    }
    for field_name in surface_fields(surface, None):
        finalized = finalize_candidate_value(field_name, candidates.get(field_name, []))
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
    preferred_title = coerce_text(payload.get("name") or payload.get("title"))
    if preferred_title:
        record["title"] = preferred_title
    if not record.get("url"):
        fallback_url = _structured_listing_url(payload, page_url)
        if fallback_url:
            record["url"] = fallback_url
    if not record.get("image_url"):
        raw_image = payload.get("image")
        if raw_image:
            image_urls = extract_urls(raw_image, page_url)
            if image_urls:
                record["image_url"] = image_urls[0]
    url = str(record.get("url") or "")
    if not url:
        return {}
    title = clean_text(record.get("title"))
    if not title or is_title_noise(title):
        fallback_title = _title_from_url(url)
        if fallback_title and not is_title_noise(fallback_title):
            record["title"] = fallback_title
    if not record.get("title"):
        return {}
    if listing_url_is_structural(url, page_url):
        return {}
    return finalize_listing_price_fields(finalize_record(record, surface=surface))


def _structured_listing_url(payload: dict[str, Any], page_url: str) -> str | None:
    for key in ("url", "link", "href", "@id"):
        resolved = absolute_url(page_url, payload.get(key))
        if resolved and not listing_url_is_structural(resolved, page_url):
            return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        for key in ("url", "link", "href"):
            resolved = absolute_url(page_url, author.get(key))
            if resolved and not listing_url_is_structural(resolved, page_url):
                return resolved
    return None


def extract_structured_listing(
    payloads: list[dict[str, Any]],
    page_url: str,
    surface: str,
    *,
    max_records: int,
    listing_min_items: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    allow_standalone_typed = _allow_standalone_typed_listing_payloads(
        payloads,
        listing_min_items=listing_min_items,
    )
    for payload in payloads:
        for item in _structured_listing_items(
            payload,
            allow_standalone_typed=allow_standalone_typed,
        ):
            record = _structured_listing_record(item, page_url, surface)
            url = str(record.get("url") or "")
            if not url or url in seen_urls or url == page_url:
                continue
            if not same_host(page_url, url):
                continue
            seen_urls.add(url)
            records.append(record)
    return records


def _structured_listing_items(
    payload: dict[str, Any],
    *,
    allow_standalone_typed: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in _listing_payload_candidates(payload):
        if not isinstance(candidate, dict):
            continue
        raw_type = candidate.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        ).lower()
        if "itemlist" in normalized_type:
            item_list = candidate.get("itemListElement")
            for item in item_list or []:
                entry = item.get("item") if isinstance(item, dict) else None
                if isinstance(entry, dict):
                    items.append(entry)
                elif isinstance(item, dict):
                    items.append(item)
            continue
        is_typed_listing_node = any(
            token in normalized_type
            for token in (
                "product",
                "jobposting",
                "article",
                "newsarticle",
                "blogposting",
            )
        )
        if allow_standalone_typed and is_typed_listing_node:
            items.append(candidate)
            continue
        if is_typed_listing_node:
            continue
        if _looks_like_untyped_listing_payload(candidate):
            items.append(candidate)
    return items


def _listing_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [payload]
    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        candidates.append(main_entity)
    elif isinstance(main_entity, list):
        candidates.extend(item for item in main_entity if isinstance(item, dict))
    return candidates


def _normalized_payload_type(payload: dict[str, Any]) -> str:
    raw_type = payload.get("@type")
    return (
        " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
    ).lower()


def _typed_listing_payloads(payloads: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for payload in payloads:
        for candidate in _listing_payload_candidates(payload):
            if not isinstance(candidate, dict):
                continue
            normalized_type = _normalized_payload_type(candidate)
            if any(
                token in normalized_type
                for token in (
                    "product",
                    "jobposting",
                    "article",
                    "newsarticle",
                    "blogposting",
                )
            ):
                yield candidate


def _allow_standalone_typed_listing_payloads(
    payloads: list[dict[str, Any]],
    *,
    listing_min_items: int,
) -> bool:
    typed_candidates = 0
    threshold = max(2, int(listing_min_items))
    for candidate in _typed_listing_payloads(payloads):
        title = coerce_text(candidate.get("name") or candidate.get("title"))
        url = candidate.get("url") or candidate.get("link") or candidate.get("href")
        if title and url:
            typed_candidates += 1
            if typed_candidates >= threshold:
                return True
    return False


def allow_embedded_json_listing_payloads(
    payloads: list[dict[str, Any]],
    *,
    listing_min_items: int,
) -> bool:
    listing_like = 0
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        normalized_type = _normalized_payload_type(payload)
        if "itemlist" in normalized_type:
            return True
        item_list = payload.get("itemListElement")
        if isinstance(item_list, list) and item_list:
            return True
        if _looks_like_untyped_listing_payload(payload):
            listing_like += 1
        main_entity = payload.get("mainEntity")
        if not isinstance(main_entity, dict):
            continue
        normalized_main_entity_type = _normalized_payload_type(main_entity)
        if "itemlist" in normalized_main_entity_type:
            return True
        main_item_list = main_entity.get("itemListElement")
        if isinstance(main_item_list, list) and main_item_list:
            return True
    threshold = max(2, int(listing_min_items))
    return listing_like >= threshold


def _looks_like_untyped_listing_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False

    title = coerce_text(payload.get("name") or payload.get("title"))
    if not title:
        return False

    if title.lower() in LISTING_NAVIGATION_TITLE_HINTS:
        return False

    has_url = any(payload.get(key) for key in ("url", "link", "href"))
    has_price = bool(
        payload.get("price") or payload.get("offers") or payload.get("sale_price")
    )
    has_image = bool(
        payload.get("image") or payload.get("image_url") or payload.get("thumbnail")
    )
    has_job_data = bool(
        payload.get("salary") or payload.get("company") or payload.get("location")
    )

    return has_url and (has_price or has_image or has_job_data)


def _title_from_url(url: str) -> str | None:
    path = str(urlsplit(str(url or "")).path or "").strip("/")
    if not path:
        return None
    terminal = path.rsplit("/", 1)[-1]
    terminal = re.sub(r"\.(html?|htm)$", "", terminal, flags=re.I)
    if not terminal:
        return None
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if not title or title.isdigit():
        return None
    return title
