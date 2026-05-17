from __future__ import annotations

import json
import logging
import math
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

from app.services.acquisition.runtime import classify_blocked_page
from app.services.config.extraction_rules import JSON_RECORD_LIST_KEYS
from app.services.extract.detail_materializer import (
    extract_detail_records,
    repair_ecommerce_detail_record_quality,
)
from app.services.extract.detail_price_extractor import (
    drop_low_signal_zero_detail_price,
)
from app.services.extract.detail_identity import (
    listing_detail_like_path,
    listing_url_is_structural,
)
from app.services.extract.listing_record_finalizer import finalize_listing_price_fields
from app.services.extract.network_listing_mapper import (
    backfill_listing_rows_from_network,
    extract_listing_rows_from_network,
    listing_identity_from_url,
)
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    coerce_text,
    direct_record_to_surface_fields,
    finalize_record,
    is_title_noise,
    surface_alias_lookup,
    surface_fields,
)
from app.services.extract.field_candidates import (
    collect_structured_candidates,
    finalize_candidate_value,
)
from app.services.field_policy import (
    canonical_fields_for_surface,
    normalize_field_key,
)
from app.services.extract.listing_candidate_ranking import best_listing_candidate_set
from app.services.listing_extractor import (
    apply_listing_integrity_gate,
    extract_listing_records,
)
from app.services.extract.content_listing_handler import validate_table_rows_quality
from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)


def _propagate_listing_integrity_to_diagnostics(
    artifacts: dict[str, object] | None,
    browser_diagnostics: dict[str, object] | None,
) -> None:
    """Thread the IntegrityDecision from artifacts onto browser_diagnostics.

    On a retry that produces a new decision, the prior decision is moved to
    ``listing_integrity.previous`` so both are auditable.  The decision is
    attached at the set level (browser_diagnostics), never on individual records
    (INVARIANTS Rule 8).
    """
    if browser_diagnostics is None or artifacts is None:
        return
    decision_payload = artifacts.get("listing_integrity")
    if not isinstance(decision_payload, dict):
        return

    # Always shallow-copy to avoid mutating the original artifacts entry.
    decision_copy = dict(decision_payload)

    existing = browser_diagnostics.get("listing_integrity")
    if isinstance(existing, dict):
        # Retry produced a new decision — preserve the prior one.
        decision_copy["previous"] = existing

    browser_diagnostics["listing_integrity"] = decision_copy


def extract_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
    requested_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
    content_type: str | None = None,
    browser_diagnostics: dict[str, object] | None = None,
) -> list[dict]:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface or normalized_surface == "auto":
        raise ValueError(f"Surface must be explicit, got: {surface!r}")
    xml_records = _extract_xml_sitemap_records(
        html,
        page_url,
        normalized_surface,
        max_records=max_records,
        content_type=content_type,
    )
    if xml_records:
        return xml_records
    raw_json_surface_field_overlap_absolute = int(
        crawler_runtime_settings.raw_json_surface_field_overlap_absolute
    )
    raw_json_surface_field_overlap_ratio = float(
        crawler_runtime_settings.raw_json_surface_field_overlap_ratio
    )
    json_records = _extract_raw_json_records(
        html,
        page_url,
        normalized_surface,
        max_records=max_records,
        requested_fields=requested_fields,
        content_type=content_type,
        raw_json_surface_field_overlap_absolute=(
            raw_json_surface_field_overlap_absolute
        ),
        raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
    )
    if json_records:
        if "listing" in normalized_surface:
            return json_records
        return _postprocess_detail_records(
            json_records[:max_records],
            html=html,
            page_url=page_url,
            requested_page_url=requested_page_url,
        )
    if _html_is_blocked_extraction_shell(html):
        return []
    if "listing" in normalized_surface:
        adapter_rows: list[dict[str, Any]] = []
        if adapter_records:
            for record in list(adapter_records or []):
                if not isinstance(record, dict):
                    continue
                shaped = direct_record_to_surface_fields(
                    record,
                    surface=normalized_surface,
                    page_url=page_url,
                    requested_fields=requested_fields,
                    base_fields={
                        "source_url": page_url,
                        "_source": str(record.get("_source") or "adapter"),
                    },
                )
                if shaped.get("title") and shaped.get("url"):
                    adapter_rows.append(shaped)
        listing_rows = extract_listing_records(
            html,
            page_url,
            normalized_surface,
            max_records=max_records,
            artifacts=artifacts,
            selector_rules=selector_rules,
            network_payloads=network_payloads,
        )
        network_rows = extract_listing_rows_from_network(
            network_payloads,
            page_url=page_url,
            surface=normalized_surface,
            max_records=max_records,
        )
        backfill_listing_rows_from_network(
            adapter_rows,
            network_payloads=network_payloads,
        )
        backfill_listing_rows_from_network(
            listing_rows,
            network_payloads=network_payloads,
        )
        adapter_rows = _finalize_listing_rows(adapter_rows)
        listing_rows = _finalize_listing_rows(listing_rows)
        network_rows = _finalize_listing_rows(network_rows)
        if (
            normalized_surface == "content_listing"
            and listing_rows
            and all(row.get("_extraction_mode") == "table_rows" for row in listing_rows)
            and validate_table_rows_quality(listing_rows)
        ):
            return listing_rows[:max_records]
        _backfill_listing_rows_from_adapter(
            listing_rows,
            adapter_rows=adapter_rows,
        )
        candidate_sets: list[tuple[str, list[dict[str, Any]]]] = []
        if adapter_rows:
            candidate_sets.append(("adapter", adapter_rows))
        if listing_rows:
            candidate_sets.append(("generic", listing_rows))
        if network_rows:
            candidate_sets.append(("network", network_rows))
        combined_rows = [*listing_rows, *adapter_rows, *network_rows]
        if len(candidate_sets) >= 2 and combined_rows:
            candidate_sets.append(("combined", combined_rows))
        if candidate_sets:
            candidate_rows = best_listing_candidate_set(
                candidate_sets,
                page_url=page_url,
                surface=normalized_surface,
                max_records=max_records,
                title_is_noise=is_title_noise,
                url_is_structural=listing_url_is_structural,
                detail_like_url=lambda candidate_url: listing_detail_like_path(
                    candidate_url,
                    is_job=str(normalized_surface or "").startswith("job_"),
                ),
            )[:max_records]
            gated_rows = apply_listing_integrity_gate(
                candidate_rows,
                page_url=page_url,
                surface=normalized_surface,
                artifacts=artifacts,
            )
            _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
            return gated_rows
        _propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
        return []
    detail_rows = _postprocess_detail_records(
        extract_detail_records(
            html,
            page_url,
            normalized_surface,
            requested_page_url=requested_page_url,
            requested_fields=requested_fields,
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            selector_rules=selector_rules,
            extraction_runtime_snapshot=extraction_runtime_snapshot,
        )[:max_records],
        html=html,
        page_url=page_url,
        requested_page_url=requested_page_url,
        repair_quality=False,
    )
    return detail_rows


def _html_is_blocked_extraction_shell(html: str) -> bool:
    if not str(html or "").strip():
        return False
    classification = classify_blocked_page(html, 0)
    if classification.blocked:
        return True
    return bool(
        (classification.active_provider_hits or classification.challenge_element_hits)
        and (
            classification.strong_hits
            or classification.weak_hits
            or classification.title_matches
        )
    )


def _finalize_listing_rows(rows: list[dict]) -> list[dict[str, Any]]:
    return [
        finalize_listing_price_fields(dict(row))
        for row in rows
        if isinstance(row, dict)
    ]


def _postprocess_detail_records(
    records: list[dict],
    *,
    html: str,
    page_url: str,
    requested_page_url: str | None,
    repair_quality: bool = True,
) -> list[dict]:
    rows: list[dict] = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        if repair_quality:
            repair_ecommerce_detail_record_quality(
                record,
                html=html,
                page_url=page_url,
                requested_page_url=requested_page_url,
            )
        drop_low_signal_zero_detail_price(record)
        rows.append(finalize_record(record, surface="ecommerce_detail"))
    return rows


def _backfill_listing_rows_from_adapter(
    rows: list[dict],
    *,
    adapter_rows: list[dict[str, Any]],
) -> None:
    if not rows or not adapter_rows:
        return
    adapter_by_url = {
        str(row.get("url") or "").strip(): row
        for row in adapter_rows
        if isinstance(row, dict) and str(row.get("url") or "").strip()
    }
    adapter_by_identity = {
        identity: row
        for row in adapter_rows
        if isinstance(row, dict) and (identity := _listing_row_identity(row))
    }
    if not adapter_by_url and not adapter_by_identity:
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        adapter_row = adapter_by_url.get(str(row.get("url") or "").strip())
        if adapter_row is None:
            row_identity = _listing_row_identity(row)
            if row_identity:
                adapter_row = adapter_by_identity.get(row_identity)
        if not isinstance(adapter_row, dict):
            continue
        for field_name, value in adapter_row.items():
            if str(field_name).startswith("_") or value in (None, "", [], {}):
                continue
            if row.get(field_name) in (None, "", [], {}):
                row[field_name] = value


def _listing_row_identity(row: dict[str, Any]) -> str:
    product_id = clean_text(
        row.get("product_id") or row.get("productId") or row.get("sku")
    )
    if product_id:
        return product_id.lower()
    return listing_identity_from_url(str(row.get("url") or ""))


def _extract_xml_sitemap_records(
    text: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    content_type: str | None,
) -> list[dict[str, Any]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    raw = str(text or "").lstrip("\ufeff").strip()
    lowered_content_type = str(content_type or "").strip().lower()
    if not _looks_like_xml_document(raw, content_type=lowered_content_type):
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    limit = max(0, int(max_records or 0))
    for loc_text in _xml_sitemap_locations(root):
        if limit and len(records) >= limit:
            break
        url = absolute_url(page_url, loc_text)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = _xml_listing_title(url)
        if not title:
            continue
        records.append(
            finalize_record(
                {
                    "source_url": page_url,
                    "_source": "xml_sitemap",
                    "title": title,
                    "url": url,
                },
                surface=surface,
            )
        )
    return records


def _looks_like_xml_document(text: str, *, content_type: str) -> bool:
    if not text:
        return False
    if any(token in content_type for token in ("xml", "rss", "atom")):
        return True
    return (
        text.startswith("<?xml")
        or text.startswith("<urlset")
        or text.startswith("<sitemapindex")
        or text.startswith("<rss")
        or text.startswith("<feed")
    )


def _xml_sitemap_locations(root: ET.Element) -> list[str]:
    locations: list[str] = []
    for node in root.iter():
        tag_name = str(node.tag or "")
        local_tag_name = tag_name.rsplit("}", 1)[-1]
        if local_tag_name == "loc":
            value = " ".join(str(node.text or "").split()).strip()
        elif local_tag_name == "link":
            value = " ".join(str(node.get("href") or node.text or "").split()).strip()
        else:
            continue
        if value:
            locations.append(value)
    return locations


def _xml_listing_title(url: str) -> str:
    path = str(urlsplit(url).path or "").strip("/")
    if not path:
        return ""
    terminal = unquote(path.rsplit("/", 1)[-1])
    terminal = re.sub(r"\.(html?|xml)$", "", terminal, flags=re.I)
    if not terminal:
        return ""
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if title:
        return title
    return clean_text(path.rsplit("/", 1)[-1])


def _extract_raw_json_records(
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
        for field_name in surface_fields(surface, requested_fields):
            finalized = finalize_candidate_value(
                field_name, candidates.get(field_name, [])
            )
            if finalized not in (None, "", [], {}):
                record[field_name] = finalized
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
