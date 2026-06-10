from __future__ import annotations

import json
import logging
import math
from typing import Any

from app.services.config.extraction_rules import JSON_RECORD_LIST_KEYS
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.field_candidates import (
    collect_structured_candidates,
    finalize_candidate_fields,
)
from app.services.extract.listing_record_finalizer import finalize_listing_price_fields
from app.services.field_policy import canonical_fields_for_surface, normalize_field_key
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    coerce_text,
    finalize_record,
    surface_alias_lookup,
    surface_fields,
)

logger = logging.getLogger(__name__)

def extract_raw_json_records(
    text: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_fields: list[str] | None,
    content_type: str | None,
    raw_json_surface_field_overlap_absolute: int,
    raw_json_surface_field_overlap_ratio: float,
) -> list[dict[str, Any]]:
    payload = _parse_raw_json_payload(text, content_type=content_type)
    if payload is None:
        return []
    items = _raw_json_items(
        payload,
        surface=surface,
        raw_json_surface_field_overlap_absolute=(
            raw_json_surface_field_overlap_absolute
        ),
        raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
    )
    if not items:
        return []
    records: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    limit = max(0, int(max_records or 0))
    for index, item in enumerate(items, start=1):
        if limit and len(records) >= limit:
            break
        record = _raw_json_record(
            item,
            page_url,
            surface,
            requested_fields=requested_fields,
            fallback_index=index,
        )
        if not record:
            continue
        dedupe_key = (
            str(record.get("url") or ""),
            str(record.get("title") or record.get("description") or ""),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        records.append(record)
    return records


def _parse_raw_json_payload(text: str, *, content_type: str | None) -> object | None:
    raw = str(text or "").lstrip("\ufeff").strip()
    lowered_content_type = str(content_type or "").strip().lower()
    if not raw:
        return None
    if "json" not in lowered_content_type and not raw.startswith(("{", "[")):
        return None
    if raw.startswith("<"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _has_surface_field_overlap(
    items: list[object],
    *,
    surface: str,
    raw_json_surface_field_overlap_absolute: int | None = None,
    raw_json_surface_field_overlap_ratio: float | None = None,
) -> bool:
    canonical = set(canonical_fields_for_surface(surface))
    if not canonical:
        return True
    dict_items = [item for item in items[:20] if isinstance(item, dict) and item]
    if not dict_items:
        return True
    required_matches = max(
        int(
            raw_json_surface_field_overlap_absolute
            if raw_json_surface_field_overlap_absolute is not None
            else crawler_runtime_settings.raw_json_surface_field_overlap_absolute
        ),
        int(
            math.ceil(
                len(dict_items)
                * float(
                    raw_json_surface_field_overlap_ratio
                    if raw_json_surface_field_overlap_ratio is not None
                    else crawler_runtime_settings.raw_json_surface_field_overlap_ratio
                )
            )
        ),
    )
    matching = 0
    overlap_cache: dict[int, bool] = {}
    total_items = len(dict_items)
    for index, item in enumerate(dict_items):
        if _payload_has_surface_field_overlap(
            item,
            canonical,
            overlap_cache=overlap_cache,
        ):
            matching += 1
            if matching >= required_matches:
                return True
        remaining = total_items - index - 1
        if matching + remaining < required_matches:
            return False
    return matching >= required_matches


def _has_surface_field_overlap_for_runtime(
    items: list[object],
    *,
    surface: str,
    raw_json_surface_field_overlap_absolute: int | None,
    raw_json_surface_field_overlap_ratio: float | None,
) -> bool:
    if (
        raw_json_surface_field_overlap_absolute is None
        and raw_json_surface_field_overlap_ratio is None
    ):
        return _has_surface_field_overlap(items, surface=surface)
    return _has_surface_field_overlap(
        items,
        surface=surface,
        raw_json_surface_field_overlap_absolute=raw_json_surface_field_overlap_absolute,
        raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
    )


def _payload_has_surface_field_overlap(
    payload: dict[str, object],
    canonical: set[str],
    *,
    overlap_cache: dict[int, bool] | None = None,
) -> bool:
    cache_key = id(payload)
    if overlap_cache is not None and cache_key in overlap_cache:
        return overlap_cache[cache_key]
    for key in payload:
        if key and normalize_field_key(key) in canonical:
            if overlap_cache is not None:
                overlap_cache[cache_key] = True
            return True
    for value in payload.values():
        if not isinstance(value, dict) or not value:
            continue
        for key in value:
            if key and normalize_field_key(key) in canonical:
                if overlap_cache is not None:
                    overlap_cache[cache_key] = True
                return True
    if overlap_cache is not None:
        overlap_cache[cache_key] = False
    return False


def _raw_json_items(
    payload: object,
    *,
    surface: str,
    raw_json_surface_field_overlap_absolute: int,
    raw_json_surface_field_overlap_ratio: float,
) -> list[object]:
    is_listing_surface = "listing" in str(surface or "").lower()
    if isinstance(payload, list):
        if is_listing_surface and not _has_surface_field_overlap_for_runtime(
            payload,
            surface=surface,
            raw_json_surface_field_overlap_absolute=(
                raw_json_surface_field_overlap_absolute
            ),
            raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
        ):
            _log_raw_json_overlap_warning(
                payload,
                surface=surface,
                location="root_list",
            )
            return []
        return list(payload)
    if not isinstance(payload, dict):
        return [] if is_listing_surface else [payload]
    for key in JSON_RECORD_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and value:
            if is_listing_surface and not _has_surface_field_overlap_for_runtime(
                value,
                surface=surface,
                raw_json_surface_field_overlap_absolute=(
                    raw_json_surface_field_overlap_absolute
                ),
                raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
            ):
                _log_raw_json_overlap_warning(
                    value,
                    surface=surface,
                    location=f"record_list_key:{key}",
                )
                continue
            return value
    if is_listing_surface:
        return _best_nested_listing_items(
            payload,
            surface=surface,
            raw_json_surface_field_overlap_absolute=(
                raw_json_surface_field_overlap_absolute
            ),
            raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
        )
    return [payload]


def _best_nested_listing_items(
    payload: object,
    *,
    depth: int = 0,
    surface: str = "",
    raw_json_surface_field_overlap_absolute: int | None = None,
    raw_json_surface_field_overlap_ratio: float | None = None,
) -> list[object]:
    if depth > 6:
        return []
    candidates: list[tuple[int, list[object]]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list):
                score = _listing_items_score(key, value)
                if score > 0:
                    if surface and not _has_surface_field_overlap_for_runtime(
                        value,
                        surface=surface,
                        raw_json_surface_field_overlap_absolute=(
                            raw_json_surface_field_overlap_absolute
                        ),
                        raw_json_surface_field_overlap_ratio=(
                            raw_json_surface_field_overlap_ratio
                        ),
                    ):
                        _log_raw_json_overlap_warning(
                            value,
                            surface=surface,
                            location=f"nested_dict_key:{key}_depth:{depth}",
                        )
                        score = 0
                if score > 0:
                    candidates.append((score, value))
                if score > 0 and _list_candidate_owns_descendants(key):
                    continue
                for item in value[:10]:
                    nested = _best_nested_listing_items(
                        item,
                        depth=depth + 1,
                        surface=surface,
                        raw_json_surface_field_overlap_absolute=(
                            raw_json_surface_field_overlap_absolute
                        ),
                        raw_json_surface_field_overlap_ratio=(
                            raw_json_surface_field_overlap_ratio
                        ),
                    )
                    if nested:
                        candidates.append(
                            (_listing_items_score("nested", nested), nested)
                        )
            elif isinstance(value, dict):
                nested = _best_nested_listing_items(
                    value,
                    depth=depth + 1,
                    surface=surface,
                    raw_json_surface_field_overlap_absolute=(
                        raw_json_surface_field_overlap_absolute
                    ),
                    raw_json_surface_field_overlap_ratio=(
                        raw_json_surface_field_overlap_ratio
                    ),
                )
                if nested:
                    candidates.append((_listing_items_score(key, nested), nested))
    elif isinstance(payload, list):
        score = _listing_items_score("list", payload)
        if score > 0:
            if surface and not _has_surface_field_overlap_for_runtime(
                payload,
                surface=surface,
                raw_json_surface_field_overlap_absolute=(
                    raw_json_surface_field_overlap_absolute
                ),
                raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
            ):
                _log_raw_json_overlap_warning(
                    payload,
                    surface=surface,
                    location=f"nested_list_depth:{depth}",
                )
                score = 0
        if score > 0:
            candidates.append((score, payload))
        for item in payload[:10]:
            nested = _best_nested_listing_items(
                item,
                depth=depth + 1,
                surface=surface,
                raw_json_surface_field_overlap_absolute=(
                    raw_json_surface_field_overlap_absolute
                ),
                raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
            )
            if nested:
                candidates.append((_listing_items_score("nested", nested), nested))
    if not candidates:
        return []
    return max(candidates, key=lambda row: (row[0], len(row[1])))[1]


def _list_candidate_owns_descendants(key: str) -> bool:
    lowered_key = str(key or "").strip().lower()
    return lowered_key in JSON_RECORD_LIST_KEYS or lowered_key in {"edges", "nodes"}


def _listing_items_score(key: str, items: list[object]) -> int:
    if not items:
        return 0
    dict_like_count = sum(1 for item in items[:20] if isinstance(item, dict) and item)
    if dict_like_count == 0:
        return 0
    lowered_key = str(key or "").strip().lower()
    score = dict_like_count
    if lowered_key in JSON_RECORD_LIST_KEYS:
        score += 20
    if lowered_key in {"edges", "nodes"}:
        score += 10
    if any(
        isinstance(item, dict)
        and any(token in item for token in ("node", "url", "title", "name"))
        for item in items[:10]
    ):
        score += 5
    return score


def _log_raw_json_overlap_warning(
    items: list[object],
    *,
    surface: str,
    location: str,
) -> None:
    logger.warning(
        "raw_json_surface_field_overlap_failed surface=%s location=%s item_count=%d skipping_items",
        surface,
        location,
        len(items),
    )


def _raw_json_record(
    payload: object,
    page_url: str,
    surface: str,
    *,
    requested_fields: list[str] | None,
    fallback_index: int,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        alias_lookup = surface_alias_lookup(surface, requested_fields)
        candidates: dict[str, list[object]] = {}
        collect_structured_candidates(payload, alias_lookup, page_url, candidates)
        record: dict[str, Any] = {"source_url": page_url, "_source": "raw_json"}
        record.update(
            finalize_candidate_fields(
                candidates,
                surface_fields(surface, requested_fields),
            )
        )
        preferred_title = coerce_text(
            payload.get("title") or payload.get("name") or payload.get("label")
        )
        if preferred_title:
            record["title"] = preferred_title
        if not record.get("description"):
            description = coerce_text(payload.get("description") or payload.get("body"))
            if description:
                record["description"] = description
        if not record.get("url"):
            record["url"] = _raw_json_url(
                payload, page_url, fallback_index=fallback_index
            )
        cleaned = finalize_record(record, surface=surface)
        if "listing" in surface:
            cleaned = finalize_listing_price_fields(cleaned)
        return cleaned if len(cleaned) > 2 else {}
    title = coerce_text(payload)
    if not title:
        return {}
    return finalize_record(
        {
            "source_url": page_url,
            "_source": "raw_json",
            "title": title,
            "url": f"{page_url.split('#', 1)[0]}#item-{fallback_index}",
        },
        surface=surface,
    )


def _raw_json_url(
    payload: dict[str, Any],
    page_url: str,
    *,
    fallback_index: int,
) -> str:
    for key in ("url", "link", "href", "permalink"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            resolved = absolute_url(page_url, value)
            if resolved:
                return resolved
    author = payload.get("author")
    if isinstance(author, dict):
        author_url = author.get("url") or author.get("link")
        resolved = absolute_url(page_url, author_url)
        if resolved:
            return resolved
    identifier = clean_text(
        payload.get("id") or payload.get("slug") or payload.get("handle")
    )
    base_url = page_url.split("#", 1)[0]
    if identifier:
        return f"{base_url}#item-{identifier}"
    return f"{base_url}#item-{fallback_index}"
