from __future__ import annotations

__all__ = (
    "existing_variant_cluster_has_transport_signal",
    "primary_dom_context",
    "record_has_rich_existing_variants",
    "extract_variants_from_dom",
    "backfill_variants_from_dom_if_missing",
)

import logging
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
    DOM_VARIANT_GROUP_LIMIT,
    LIVE_MARKETPLACE_HOSTS,
)
from app.services.shared.field_coerce import (
    clean_text,
    object_dict as _object_dict,
    object_list as _object_list,
    text_or_none,
)
from app.services.extract.detail.variants.dom_record_assembly import (
    assemble_dom_variant_record,
)
from app.services.extract.detail.variants.dom_option_groups import (
    collect_dom_variant_candidate_groups,
)
from app.services.extract.detail.variants.dom_merge import (
    dom_rows_have_combination_identity as _dom_rows_have_combination_identity,
    dom_variants_add_missing_existing_axis as _dom_variants_add_missing_existing_axis,
    expand_existing_variants_with_dom_axes as _expand_existing_variants_with_dom_axes,
)
from app.services.extract.variant_group_validator import (
    VariantGroupValidator,
)
from app.services.extract.variant_choice_traversal import (
    variant_dom_cues_present,
)
from app.services.extract.variant_identity_merge import merge_variant_pair
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
)
from app.services.extract.detail.assembly import (
    dom_section_targets as _detail_dom_section_targets,
)
from app.services.extract.detail.variants import dom_coercion as _variant_coercion

existing_variant_cluster_has_transport_signal = (
    _detail_dom_section_targets.existing_variant_cluster_has_transport_signal
)
primary_dom_context = _detail_dom_section_targets.primary_dom_context
record_has_rich_existing_variants = (
    _detail_dom_section_targets.record_has_rich_existing_variants
)

logger = logging.getLogger(__name__)
_DOM_VARIANT_CACHE_ATTR = "_crawler_dom_variant_extraction_cache"


def _safe_int_config(value: object, default: int, name: str) -> int:
    try:
        if not isinstance(value, (int, float, str)):
            raise TypeError
        return max(1, int(value))
    except (TypeError, ValueError) as exc:
        logger.warning(
            f"Invalid {name}; using {default}",
            extra={"value": value},
            exc_info=exc,
        )
        return default


_expand_compound_option_group = _variant_coercion._expand_compound_option_group


# skipcq: PY-R1000
def extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    # TODO: profile cache-key cost if callers start mutating soup before reuse.
    cache_key = (str(page_url or ""), id(js_state_objects), id(soup))
    cached = _cached_dom_variant_record(soup, cache_key)
    if cached is not None:
        return cached
    candidate_groups = collect_dom_variant_candidate_groups(
        soup,
        page_url=page_url,
        safe_int_config=_safe_int_config,
    )

    validator = VariantGroupValidator()
    option_groups = [
        group.as_option_group()
        for group in candidate_groups
        if validator.validate(group, page_url=page_url)
    ]
    expanded_option_groups: list[dict[str, object]] = []
    for group in option_groups:
        compound_groups = _expand_compound_option_group(group)
        if compound_groups:
            expanded_option_groups.extend(compound_groups)
            continue
        expanded_option_groups.append(group)

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in expanded_option_groups:
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(
            axis_key, {"name": name or axis_key, "values": [], "entries": {}}
        )
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        existing_values = _object_list(merged.get("values"))
        merged["values"] = list(dict.fromkeys([*existing_values, *values]))
        merged_entries = merged.setdefault("entries", {})
        if not isinstance(merged_entries, dict):
            merged_entries = {}
            merged["entries"] = merged_entries
        for group_entry in _object_list(group.get("entries")):
            if not isinstance(group_entry, dict):
                continue
            value = clean_text(group_entry.get("value"))
            if not value:
                continue
            existing = _object_dict(merged_entries.get(value, {"value": value}))
            availability = text_or_none(group_entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if group_entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = group_entry.get("stock_quantity")
            if group_entry.get("style") not in (None, "", [], {}) and existing.get(
                "style"
            ) in (None, "", [], {}):
                existing["style"] = group_entry.get("style")
            if group_entry.get("selected"):
                existing["selected"] = True
            if group_entry.get("url") not in (None, "", [], {}) and existing.get(
                "url"
            ) in (None, "", [], {}):
                existing["url"] = group_entry.get("url")
            if group_entry.get("variant_id") not in (None, "", [], {}) and existing.get(
                "variant_id"
            ) in (None, "", [], {}):
                existing["variant_id"] = group_entry.get("variant_id")
            if group_entry.get("image_url") not in (None, "", [], {}) and existing.get(
                "image_url"
            ) in (None, "", [], {}):
                existing["image_url"] = group_entry.get("image_url")
            merged_entries[value] = existing
    group_limit = _safe_int_config(
        DOM_VARIANT_GROUP_LIMIT,
        1,
        "DOM_VARIANT_GROUP_LIMIT",
    )
    for group in merged_groups.values():
        values = [
            clean_text(value)
            for value in _object_list(group.get("values"))
            if clean_text(value)
        ]
        if len(values) < 2:
            continue
        merged_entries = _object_dict(group.get("entries"))
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list(merged_entries.values()),
            }
        )
        if len(deduped_groups) >= group_limit:
            break

    if not deduped_groups:
        return _cache_dom_variant_record(soup, cache_key, {})

    record = assemble_dom_variant_record(
        deduped_groups=deduped_groups,
        js_state_objects=js_state_objects,
        page_url=page_url,
        cartesian_combo_limit=DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
        safe_int_config=_safe_int_config,
    )
    return _cache_dom_variant_record(soup, cache_key, record)


def _cached_dom_variant_record(
    soup: BeautifulSoup,
    cache_key: tuple[str, int, int],
) -> dict[str, object] | None:
    cache = getattr(soup, _DOM_VARIANT_CACHE_ATTR, None)
    if not isinstance(cache, dict):
        return None
    cached = cache.get(cache_key)
    return deepcopy(cached) if isinstance(cached, dict) else None


def _cache_dom_variant_record(
    soup: BeautifulSoup,
    cache_key: tuple[str, int, int],
    record: dict[str, object],
) -> dict[str, object]:
    cache = getattr(soup, _DOM_VARIANT_CACHE_ATTR, None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            setattr(soup, _DOM_VARIANT_CACHE_ATTR, cache)
        except Exception:
            return record
    cache[cache_key] = deepcopy(record)
    return record


def backfill_variants_from_dom_if_missing(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> None:
    existing_variants = [
        row for row in record.get("variants") or [] if isinstance(row, dict)
    ]
    if not variant_dom_cues_present(soup):
        return
    dom_variants = extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    dom_variant_rows = [
        row
        for row in _object_list(dom_variants.get("variants"))
        if isinstance(row, dict)
    ]
    if not dom_variant_rows:
        return
    existing_variants_are_rich = (
        record_has_rich_existing_variants(record)
        or existing_variant_cluster_has_transport_signal(existing_variants)
    )
    if existing_variants_are_rich and not _dom_variants_add_missing_existing_axis(
        existing_variants, dom_variant_rows
    ):
        return
    if dom_variant_rows:
        expanded_rows = _expand_existing_variants_with_dom_axes(
            existing_variants,
            dom_variant_rows,
        )
        if expanded_rows:
            record["variants"] = expanded_rows
            record["variant_count"] = len(expanded_rows)
        elif existing_variants_are_rich and not _dom_rows_have_combination_identity(
            dom_variant_rows
        ):
            if _dom_rows_are_richer_axis_grid(existing_variants, dom_variant_rows):
                if _existing_variants_have_multiple_colors(existing_variants):
                    record["_disable_variant_parent_color_inheritance"] = True
                record["variants"] = dom_variant_rows
                record["variant_count"] = len(dom_variant_rows)
            else:
                return
        else:
            existing_by_key: dict[str, dict[str, Any]] = {}
            for row in existing_variants:
                row_key = text_or_none(row.get("variant_id")) or text_or_none(
                    row.get("url")
                )
                if row_key:
                    # Preserve the first occurrence so duplicate variant_id/url
                    # keys cannot overwrite earlier rows and merge unrelated variants.
                    existing_by_key.setdefault(row_key, row)
            merged_rows: list[dict[str, Any]] = []
            for dom_row in dom_variant_rows:
                dom_key = text_or_none(dom_row.get("variant_id")) or text_or_none(
                    dom_row.get("url")
                )
                existing_row = existing_by_key.get(dom_key or "") if dom_key else None
                merged_rows.append(
                    merge_variant_pair(existing_row, dom_row)
                    if isinstance(existing_row, dict)
                    else dom_row
                )
            record["variants"] = merged_rows
            record["variant_count"] = len(merged_rows)
    currency = text_or_none(record.get("currency"))
    price = text_or_none(record.get("price"))
    parent_availability = text_or_none(record.get("availability"))
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    any_variant_has_price = any(
        isinstance(variant, dict) and variant.get("price") not in (None, "", [], {})
        for variant in variants
    )
    # On live-marketplace sites (StockX, Back Market, GOAT, eBay, etc.)
    # each variant has a unique, dynamic price. Broadcasting the parent
    # price into missing variant rows turns every size/condition into
    # the same number ($50 on StockX, $411 on Back Market) — a tell-tale
    # sign of a failed per-variant price capture. Skip the price/currency
    # broadcast so the missing-price row surfaces as "no price" rather
    # than a wrong uniform value. Availability is independent of price —
    # even a marketplace usually has the same in-stock signal for every
    # variant of one product, so broadcast it unless the row already
    # carries its own availability/stock evidence.
    is_live_marketplace = _page_url_is_live_marketplace(page_url)
    broadcast_price = bool(price) and not is_live_marketplace
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if (
            parent_availability == "in_stock"
            and variant.get("availability") in (None, "", [], {})
            and variant.get("stock_quantity") in (None, "", [], {})
        ):
            variant["availability"] = parent_availability
        if not broadcast_price or any_variant_has_price:
            continue
        if price:
            variant["price"] = price
        if currency and variant.get("currency") in (None, "", [], {}):
            variant["currency"] = currency


def _page_url_is_live_marketplace(page_url: str) -> bool:
    if not page_url:
        return False
    try:
        host = (urlparse(str(page_url)).hostname or "").lower()
    except (TypeError, ValueError):
        return False
    return host in LIVE_MARKETPLACE_HOSTS or any(
        host.endswith(f".{marketplace_host}")
        for marketplace_host in LIVE_MARKETPLACE_HOSTS
    )


def _dom_rows_are_richer_axis_grid(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> bool:
    if not existing_variants or not dom_variant_rows:
        return False
    existing_axis_count = max((_axis_count(row) for row in existing_variants), default=0)
    dom_axis_count = max((_axis_count(row) for row in dom_variant_rows), default=0)
    return dom_axis_count >= 2 and dom_axis_count > existing_axis_count


def _existing_variants_have_multiple_colors(
    existing_variants: list[dict[str, Any]],
) -> bool:
    colors = {
        clean_text(row.get("color")).casefold()
        for row in existing_variants
        if clean_text(row.get("color"))
    }
    return len(colors) > 1


def _axis_count(row: dict[str, Any]) -> int:
    return sum(
        1
        for axis in ("color", "size", "width", "storage", "condition", "screen_size", "resolution")
        if text_or_none(row.get(axis))
    )
