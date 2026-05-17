from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.services.config.extraction_rules import (
    DETAIL_BREADCRUMB_ROOT_LABELS,
    DETAIL_BREADCRUMB_SEPARATOR_LABELS,
    DETAIL_GENDER_TERMS,
    STRUCTURED_CANDIDATE_LIST_SLICE,
    STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT,
)
from app.services.extract.shared_variant_logic import resolve_variants
from app.services.field_policy import normalize_field_key, normalize_requested_field
from app.services.shared.field_coerce import (
    STRUCTURED_MULTI_FIELDS,
    absolute_url,
    coerce_field_value,
    coerce_text,
    extract_urls,
    text_or_none,
)

from .collection import add_candidate
from .structured_values import (
    _coerce_structured_candidate_value,
    _structured_alias_allowed,
    _structured_alias_value_allowed,
)
from .variant_rows import (
    _structured_offer_variant_rows,
    _structured_variant_rows,
    _structured_variants_from_product_payload,
    _variant_axes_from_rows,
)

logger = logging.getLogger(__name__)
_structured_candidate_list_slice = int(STRUCTURED_CANDIDATE_LIST_SLICE)
_structured_candidate_traversal_limit = int(STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT)


def _normalized_text_token(value: object) -> str:
    return " ".join(str(value or "").replace("&", " ").split()).strip().lower()


def _gender_from_text(value: object) -> str | None:
    text = _normalized_text_token(value)
    if not text:
        return None
    padded = f" {text.replace('-', ' ')} "
    matches: list[str] = []
    for canonical, terms in DETAIL_GENDER_TERMS.items():
        if any(f" {str(term).lower().replace('-', ' ')} " in padded for term in terms):
            matches.append(str(canonical))
    return matches[0] if len(set(matches)) == 1 else None


def _breadcrumb_item_name(item: object) -> str | None:
    if isinstance(item, str):
        return text_or_none(item)
    if not isinstance(item, dict):
        return None
    source = item.get("item")
    if isinstance(source, dict):
        name = source.get("name") or source.get("title")
        if name not in (None, "", [], {}):
            return text_or_none(name)
    return text_or_none(item.get("name") or item.get("title"))


def _breadcrumb_names(payload: dict[str, object], page_url: str = "") -> list[str]:
    raw_items = payload.get("itemListElement")
    if not isinstance(raw_items, list):
        return []

    def _get_position(item: Any) -> float:
        if not isinstance(item, dict):
            return 0.0
        try:
            return float(item.get("position", 0))
        except (ValueError, TypeError):
            return 0.0

    try:
        if all(isinstance(x, dict) and _get_position(x) > 0 for x in raw_items):
            raw_items = sorted(raw_items, key=_get_position)
    except Exception:
        logger.exception("Failed to sort breadcrumb itemListElement by position")

    names: list[str] = []
    strip_chars = " \t\n\r" + "".join(DETAIL_BREADCRUMB_SEPARATOR_LABELS)
    for item in raw_items:
        name = _breadcrumb_item_name(item)
        if name:
            clean_name = name.strip(strip_chars)
            if clean_name and clean_name not in DETAIL_BREADCRUMB_SEPARATOR_LABELS:
                names.append(clean_name)
    if not names:
        return []

    def _is_root_label(text: str) -> bool:
        lowered = text.strip().lower()
        if lowered in DETAIL_BREADCRUMB_ROOT_LABELS:
            return True
        if page_url:
            host = urlparse(page_url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            host_parts = [part for part in host.split(".") if part]
            second_level_domain = host_parts[-2] if len(host_parts) >= 2 else host
            if host and (lowered == host or lowered == second_level_domain):
                return True
        return False

    if len(names) > 1 and _is_root_label(names[-1]) and not _is_root_label(names[0]):
        names.reverse()

    if _is_root_label(names[0]):
        names = names[1:]
    return [name for name in names if name]


def _breadcrumb_category_path(
    payload: dict[str, object], page_url: str = ""
) -> str | None:
    names = _breadcrumb_names(payload, page_url)
    return " > ".join(names) if names else None


def _structured_feature_rows(payload: dict[str, object], page_url: str) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()

    def _add(value: object) -> None:
        coerced = coerce_field_value("features", value, page_url)
        values = coerced if isinstance(coerced, list) else [coerced]
        for item in values:
            text = text_or_none(item)
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            rows.append(text)

    for key in ("feature", "features"):
        raw_value = payload.get(key)
        if raw_value not in (None, "", [], {}):
            _add(raw_value)

    additional_properties = payload.get("additionalProperty")
    if isinstance(additional_properties, list):
        for item in additional_properties[: _structured_candidate_list_slice]:
            if not isinstance(item, dict):
                continue
            name = text_or_none(item.get("name") or item.get("label"))
            value = text_or_none(item.get("value") or item.get("description"))
            if name and value:
                _add(f"{name}: {value}")
            elif value:
                _add(value)
    return rows


def collect_structured_candidates(
    payload: object,
    alias_lookup: dict[str, str],
    page_url: str,
    candidates: dict[str, list[object]],
    *,
    depth: int = 0,
    limit: int = _structured_candidate_traversal_limit,
    in_variant_context: bool = False,
) -> None:
    if depth > limit:
        return
    if isinstance(payload, dict):
        raw_type = payload.get("@type")
        normalized_type = (
            " ".join(raw_type) if isinstance(raw_type, list) else str(raw_type or "")
        )
        normalized_type = normalized_type.lower()
        breadcrumb_list = "breadcrumblist" in normalized_type
        list_item_wrapper = "listitem" in normalized_type and (
            "position" in payload or "item" in payload
        )
        review_like = any(
            token in normalized_type for token in ("review", "reviewrating")
        )
        additional_properties = payload.get("additionalProperty")
        if isinstance(additional_properties, list):
            for item in additional_properties[: _structured_candidate_list_slice]:
                if not isinstance(item, dict):
                    continue
                label = normalize_requested_field(
                    item.get("name")
                ) or normalize_field_key(item.get("name"))
                canonical = alias_lookup.get(label)
                if canonical:
                    add_candidate(
                        candidates,
                        canonical,
                        coerce_field_value(canonical, item.get("value"), page_url),
                    )
        if breadcrumb_list:
            category_path = _breadcrumb_category_path(payload, page_url)
            if category_path:
                add_candidate(candidates, "category", category_path)
                gender = _gender_from_text(category_path)
                if gender:
                    add_candidate(candidates, "gender", gender)
        if {normalize_field_key(str(key or "")) for key in payload.keys()} & {
            "field_name",
            "field_value",
            "field_values",
        }:
            label = normalize_requested_field(
                payload.get("FieldName")
                or payload.get("fieldName")
                or payload.get("field_name")
            ) or normalize_field_key(
                payload.get("FieldName")
                or payload.get("fieldName")
                or payload.get("field_name")
            )
            canonical = alias_lookup.get(label)
            if canonical:
                raw_value = (
                    payload.get("FieldValues")
                    or payload.get("fieldValues")
                    or payload.get("field_values")
                    or payload.get("FieldValue")
                    or payload.get("fieldValue")
                    or payload.get("field_value")
                )
                if isinstance(raw_value, list):
                    if canonical in STRUCTURED_MULTI_FIELDS:
                        coerced_value: object = raw_value
                    else:
                        coerced_value = " ".join(
                            text for item in raw_value if (text := text_or_none(item))
                        )
                else:
                    coerced_value = raw_value
                add_candidate(
                    candidates,
                    canonical,
                    coerce_field_value(canonical, coerced_value, page_url),
                )
        for key, value in payload.items():
            if str(key).startswith("@"):
                collect_structured_candidates(
                    value,
                    alias_lookup,
                    page_url,
                    candidates,
                    depth=depth + 1,
                    limit=limit,
                    in_variant_context=in_variant_context,
                )
                continue
            normalized_key = normalize_field_key(key)
            if (
                breadcrumb_list
                and normalized_key
                in {"item_list_element", "item", "name", "title", "position"}
            ) or (
                list_item_wrapper
                and normalized_key in {"item", "name", "title", "position"}
            ):
                continue
            if "productgroup" in normalized_type and normalized_key in {
                "has_variant",
                "hasvariant",
            }:
                continue
            child_in_variant_context = in_variant_context or normalized_key in {
                "has_variant",
                "hasvariant",
                "variants",
            }
            canonical = alias_lookup.get(normalized_key)
            if (
                canonical
                and not in_variant_context
                and not (
                    review_like
                    and canonical
                    in {"title", "description", "image_url", "additional_images"}
                )
                and _structured_alias_allowed(
                    canonical=canonical,
                    normalized_key=normalized_key,
                    payload=payload,
                )
                and _structured_alias_value_allowed(
                    canonical=canonical,
                    normalized_key=normalized_key,
                    payload=payload,
                    value=value,
                )
            ):
                add_candidate(
                    candidates,
                    canonical,
                    _coerce_structured_candidate_value(
                        canonical,
                        value,
                        page_url=page_url,
                        payload=payload,
                        source_key=normalized_key,
                    ),
                )
            collect_structured_candidates(
                value,
                alias_lookup,
                page_url,
                candidates,
                depth=depth + 1,
                limit=limit,
                in_variant_context=child_in_variant_context,
            )
        if not in_variant_context and (
            "product" in normalized_type or "productgroup" in normalized_type
        ):
            offer = payload.get("offers")
            offer = offer[0] if isinstance(offer, list) and offer else offer
            aggregate = payload.get("aggregateRating")
            brand = payload.get("brand")
            images = extract_urls(payload.get("image"), page_url)
            add_candidate(
                candidates,
                "title",
                coerce_text(payload.get("name") or payload.get("title")),
            )
            raw_id = payload.get("@id")
            # Ignore blank-node identifiers or non-URL @id values
            id_fallback = (
                raw_id
                if isinstance(raw_id, str)
                and raw_id
                and not raw_id.startswith("_:")
                and ("/" in raw_id or ":" in raw_id)
                else None
            )
            add_candidate(
                candidates,
                "url",
                absolute_url(
                    page_url,
                    payload.get("url") or id_fallback or page_url,
                ),
            )
            add_candidate(
                candidates, "description", coerce_text(payload.get("description"))
            )
            add_candidate(
                candidates, "brand", coerce_field_value("brand", brand, page_url)
            )
            add_candidate(candidates, "sku", coerce_text(payload.get("sku")))
            add_candidate(candidates, "part_number", coerce_text(payload.get("mpn")))
            add_candidate(
                candidates,
                "barcode",
                coerce_text(
                    payload.get("gtin13")
                    or payload.get("gtin")
                    or payload.get("gtin14")
                ),
            )
            add_candidate(
                candidates,
                "price",
                coerce_field_value("price", offer or payload, page_url),
            )
            add_candidate(
                candidates,
                "currency",
                coerce_field_value("currency", offer or payload, page_url),
            )
            add_candidate(
                candidates,
                "availability",
                coerce_field_value("availability", offer or payload, page_url),
            )
            add_candidate(
                candidates, "rating", coerce_field_value("rating", aggregate, page_url)
            )
            add_candidate(
                candidates,
                "review_count",
                coerce_field_value("review_count", aggregate, page_url),
            )
            add_candidate(candidates, "category", coerce_text(payload.get("category")))
            add_candidate(
                candidates,
                "gender",
                coerce_field_value("gender", payload.get("gender"), page_url),
            )
            add_candidate(
                candidates,
                "color",
                coerce_field_value("color", payload.get("color"), page_url),
            )
            add_candidate(
                candidates,
                "size",
                coerce_field_value("size", payload.get("size"), page_url),
            )
            add_candidate(candidates, "materials", coerce_text(payload.get("material")))
            feature_rows = _structured_feature_rows(payload, page_url)
            if feature_rows:
                add_candidate(candidates, "features", feature_rows)
            if images:
                add_candidate(candidates, "image_url", images[0])
                add_candidate(candidates, "additional_images", images[1:])
            variants = _structured_variant_rows(payload.get("hasVariant"), page_url)
            offer_variants = _structured_offer_variant_rows(
                payload.get("offers"), page_url
            )
            if offer_variants:
                variants.extend(offer_variants)
            product_variants = _structured_variants_from_product_payload(
                payload, page_url
            )
            if product_variants:
                variants.extend(product_variants)
            if variants:
                axes = _variant_axes_from_rows(variants)
                if axes:
                    variants = resolve_variants(axes, variants)
                add_candidate(candidates, "variants", variants)
                add_candidate(candidates, "variant_count", len(variants))
        if "jobposting" in normalized_type:
            organization = payload.get("hiringOrganization")
            remote_hint = coerce_text(payload.get("jobLocationType"))
            add_candidate(
                candidates,
                "title",
                coerce_text(payload.get("title") or payload.get("name")),
            )
            add_candidate(
                candidates,
                "url",
                absolute_url(page_url, payload.get("url") or page_url),
            )
            add_candidate(
                candidates,
                "apply_url",
                absolute_url(page_url, payload.get("url") or page_url),
            )
            add_candidate(
                candidates,
                "company",
                coerce_field_value("company", organization, page_url),
            )
            add_candidate(
                candidates,
                "location",
                coerce_field_value("location", payload.get("jobLocation"), page_url),
            )
            add_candidate(
                candidates, "posted_date", coerce_text(payload.get("datePosted"))
            )
            add_candidate(
                candidates, "job_type", coerce_text(payload.get("employmentType"))
            )
            add_candidate(
                candidates,
                "salary",
                coerce_field_value("salary", payload.get("baseSalary"), page_url),
            )
            add_candidate(
                candidates, "description", coerce_text(payload.get("description"))
            )
            if remote_hint:
                add_candidate(candidates, "remote", remote_hint)
    elif isinstance(payload, list):
        for item in payload[: _structured_candidate_list_slice]:
            collect_structured_candidates(
                item,
                alias_lookup,
                page_url,
                candidates,
                depth=depth + 1,
                limit=limit,
                in_variant_context=in_variant_context,
            )
