from __future__ import annotations
# ruff: noqa: F401,F403,F405

import logging
from typing import Any

from ._common import *
from ._identity import (
    _mapped_product_family_matches,
    _mapped_product_identity_matches,
    _mapped_record_matches_page_url,
    _merge_same_product_record,
    _merge_variant_fields,
)
from ._payloads import (
    _find_product_payloads,
    _looks_like_product_payload,
    _normalized_state_payload,
)
from ._product_mapping import _map_product_payload

logger = logging.getLogger(__name__)


def map_js_state_to_fields(
    js_state_objects: dict[str, Any],
    *,
    surface: str,
    page_url: str,
) -> dict[str, Any]:
    normalized_surface = str(surface or "").strip().lower()
    if not js_state_objects:
        return {}
    if normalized_surface == "job_detail":
        return map_job_detail_state(js_state_objects)
    if normalized_surface == "ecommerce_detail":
        return _map_ecommerce_detail_state(js_state_objects, page_url=page_url)
    logger.warning(
        "Unsupported JS-state surface: surface=%s page_url=%s",
        normalized_surface,
        page_url,
    )
    return {}


def _map_ecommerce_detail_state(
    js_state_objects: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    base_record: dict[str, Any] = {}
    for state_key, payload in js_state_objects.items():
        normalized_payload = _normalized_state_payload(state_key, payload)
        product_payloads = _extract_product_payloads_from_normalized(
            state_key,
            normalized_payload,
        )
        for product, extractor in product_payloads:
            if not isinstance(product, dict):
                continue
            mapped = _map_product_payload(
                product,
                page_url=page_url,
                category_fallback_from_type=(state_key == "__NUXT_DATA__"),
                field_jmespaths=(
                    extractor.field_jmespaths if extractor is not None else None
                ),
            )
            if mapped:
                if not base_record:
                    base_record = mapped
                elif (
                    _mapped_product_family_matches(base_record, mapped)
                    and _mapped_record_matches_page_url(mapped, page_url)
                    and not _mapped_record_matches_page_url(base_record, page_url)
                ):
                    base_record = _merge_same_product_record(
                        mapped,
                        base_record,
                        page_url=page_url,
                    )
                    if mapped.get("variants"):
                        for field_name in VARIANT_AXIS_KEYS:
                            if mapped.get(field_name) in (None, "", [], {}):
                                base_record.pop(field_name, None)
                elif _mapped_product_identity_matches(
                    base_record, mapped, page_url=page_url
                ):
                    base_record = _merge_same_product_record(
                        base_record,
                        mapped,
                        page_url=page_url,
                    )
                elif (
                    not base_record.get("variants")
                    and mapped.get("variants")
                    and _mapped_record_matches_page_url(mapped, page_url)
                ):
                    base_record = _merge_variant_fields(base_record, mapped)
    return base_record


def _extract_product_payloads_from_normalized(
    state_key: str,
    normalized_payload: Any,
) -> list[tuple[dict[str, Any], JSStateExtractorConfig | None]]:
    products: list[tuple[dict[str, Any], JSStateExtractorConfig | None]] = []
    for extractor in platform_js_state_extractors(
        surface="ecommerce_detail",
        state_key=state_key,
    ):
        for root_path in extractor.root_paths.get(state_key, []):
            candidate = path_value(normalized_payload, root_path)
            if _looks_like_product_payload(candidate):
                products.append((dict(candidate), extractor))
                continue
            products.extend(
                (product, extractor) for product in _find_product_payloads(candidate)
            )
    try:
        marketplace_choice_products = extract_marketplace_choice_products(
            normalized_payload
        )
    except (AttributeError, TypeError, ValueError):
        logger.debug("Marketplace choice extraction failed", exc_info=True)
        marketplace_choice_products = []
    products.extend((product, None) for product in marketplace_choice_products)
    products.extend(
        (product, None) for product in _find_product_payloads(normalized_payload)
    )
    if products:
        return _dedupe_product_payloads(products)
    return []


def _dedupe_product_payloads(
    products: list[tuple[dict[str, Any], JSStateExtractorConfig | None]],
) -> list[tuple[dict[str, Any], JSStateExtractorConfig | None]]:
    deduped: list[tuple[dict[str, Any], JSStateExtractorConfig | None]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for product, extractor in products:
        key = tuple(
            sorted(
                (field_name, str(product.get(field_name)))
                for field_name in (
                    "id",
                    "product_id",
                    "productId",
                    "pid",
                    "sku",
                    "handle",
                    "title",
                    "name",
                    "pn",
                )
                if product.get(field_name) not in (None, "", [], {})
            )
        ) + (("__keys__", ",".join(sorted(str(key) for key in product))),)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((product, extractor))
    return deduped[: int(JS_STATE_PRODUCT_PAYLOAD_LIMIT)]


__all__ = ["map_js_state_to_fields"]
