from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

import jmespath
from bs4 import BeautifulSoup
from glom import GlomError, glom  # type: ignore[import-untyped]

from app.services.config.js_state_field_specs import (
    JS_STATE_PRODUCT_PAYLOAD_LIMIT,
    JS_STATE_LIST_ITERATION_LIMIT,
    JS_STATE_PRODUCT_FIELD_SPEC,
    JS_STATE_PRODUCT_VARIANT_LIST_KEYS,
    JS_STATE_VARIANT_FIELD_SPEC,
    VARIANT_AXIS_KEYS,
)
from app.services.config.extraction_rules import ECOMMERCE_DESCRIPTION_BLOCK_LIMIT
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_policy import normalize_field_key
from app.services.dom.selector_engine import dedupe_image_urls, extract_feature_rows
from app.services.extract.shared_variant_logic import (
    merge_variant_rows,
    resolve_variants,
)
from app.services.shared.field_coerce import (
    clean_text,
    extract_urls,
    surface_alias_lookup,
    text_or_none,
)
from app.services.js_state.marketplace_choice_mapper import (
    extract_marketplace_choice_products,
)
from app.services.js_state.variant_options import (
    option_value_labels,
    variant_axis_value,
    variant_option_values,
    variant_selection_values,
)
from app.services.js_state_helpers import (
    availability_value,
    compact_dict,
    normalize_price,
    select_variant,
    stock_quantity,
    variant_attribute,
    variant_axes,
)
from app.services.platform_policy import JSStateExtractorConfig, platform_js_state_extractors

logger = logging.getLogger(__name__)
PRODUCT_FIELD_SPEC = JS_STATE_PRODUCT_FIELD_SPEC
_VARIANT_FIELD_SPEC = JS_STATE_VARIANT_FIELD_SPEC

def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _product_variant_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in JS_STATE_PRODUCT_VARIANT_LIST_KEYS:
        raw_rows = _as_list(product.get(key))
        if not raw_rows:
            continue
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if key != "variants":
                _backfill_nested_variant_context(row, product)
            rows.append(row)
    return rows


def _backfill_nested_variant_context(
    variant: dict[str, Any],
    product: dict[str, Any],
) -> None:
    for target_key, product_keys in {
        "color": ("color", "colour"),
        "currencyCode": ("currencyCode", "currency", "priceCurrency"),
        "compareAtPrice": ("compareAtPrice", "compare_at_price"),
        "featuredImage": ("featuredMedia", "featured_image", "image"),
        "url": (
            "url",
            "href",
            "onlineStoreUrl",
            "online_store_url",
            "productUrl",
            "product_url",
            "canonicalUrl",
            "canonical_url",
        ),
    }.items():
        if variant.get(target_key) not in (None, "", [], {}):
            continue
        for product_key in product_keys:
            value = product.get(product_key)
            if value not in (None, "", [], {}):
                variant[target_key] = value
                break

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
        return _map_job_detail_state(js_state_objects)
    if normalized_surface == "ecommerce_detail":
        return _map_ecommerce_detail_state(js_state_objects, page_url=page_url)
    logger.warning(
        "Unsupported JS-state surface: surface=%s page_url=%s",
        normalized_surface,
        page_url,
    )
    return {}

def _map_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    mapped = _map_platform_job_detail_state(js_state_objects)
    if not mapped:
        return {}
    description_html = str(mapped.pop("description_html", "") or "").strip()
    if description_html:
        mapped.update(extract_job_sections(description_html))
        if "description" not in mapped:
            mapped["description"] = html_to_text(description_html)
    if mapped.get("apply_url") and not mapped.get("url"):
        mapped["url"] = mapped["apply_url"]
    return mapped

def _map_platform_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    for state_key, payload in js_state_objects.items():
        if not isinstance(payload, dict):
            continue
        extractors = platform_js_state_extractors(
            surface="job_detail",
            state_key=state_key,
        )
        for extractor in extractors:
            mapped = _map_configured_state_payload(
                payload,
                root_paths=extractor.root_paths.get(state_key, []),
                field_paths=extractor.field_paths,
            )
            if mapped:
                return mapped
    return {}

def _map_configured_state_payload(
    payload: dict[str, Any],
    *,
    root_paths: list[list[str]],
    field_paths: dict[str, list[list[str]]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for root_path in root_paths:
        candidate = _path_value(payload, root_path)
        if not isinstance(candidate, dict):
            continue
        mapped = compact_dict(
            {
                field_name: _first_path_value(candidate, paths)
                for field_name, paths in field_paths.items()
            }
        )
        for field_name, value in mapped.items():
            if merged.get(field_name) in (None, "", [], {}) and value not in (
                None,
                "",
                [],
                {},
            ):
                merged[field_name] = value
    return compact_dict(merged)

def _first_path_value(payload: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        value = _path_value(payload, path)
        if value not in (None, "", [], {}):
            return value
    return None

def _path_value(payload: Any, path: list[str]) -> Any:
    current = payload
    for segment in path:
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list):
            try:
                current = current[int(segment)]
            except (TypeError, ValueError, IndexError):
                return None
            continue
        return None
    return current


map_configured_state_payload = _map_configured_state_payload

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
                elif _mapped_product_identity_matches(base_record, mapped, page_url=page_url):
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
            candidate = _path_value(normalized_payload, root_path)
            if _looks_like_product_payload(candidate):
                products.append((dict(candidate), extractor))
    products.extend(
        (product, None)
        for product in extract_marketplace_choice_products(normalized_payload)
    )
    products.extend((product, None) for product in _find_product_payloads(normalized_payload))
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


def _merge_same_product_record(
    base_record: dict[str, Any],
    incoming: dict[str, Any],
    *,
    page_url: str,
) -> dict[str, Any]:
    merged = dict(base_record)
    for field_name, field_value in incoming.items():
        if field_name in {"variants", "variant_count"}:
            continue
        if (
            field_name in {"availability", "stock_quantity", "original_price"}
            and field_value not in (None, "", [], {})
        ):
            merged[field_name] = field_value
            continue
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value

    merged_variants = merge_variant_rows(
        base_record.get("variants"),
        incoming.get("variants"),
        [] if base_record.get("variants") else [_scalar_variant_row(base_record)],
        [] if incoming.get("variants") else [_scalar_variant_row(incoming)],
    )
    if merged_variants:
        merged["variants"] = merged_variants
        merged["variant_count"] = len(merged_variants)
    return compact_dict(merged)


def _merge_variant_fields(
    base_record: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(base_record)
    merged_variants = merge_variant_rows(
        base_record.get("variants"), incoming.get("variants")
    )
    if merged_variants:
        merged["variants"] = merged_variants
        merged["variant_count"] = len(merged_variants)
    return compact_dict(merged)


def _scalar_variant_row(record: dict[str, Any]) -> dict[str, Any]:
    axes = {
        field_name: record.get(field_name)
        for field_name in VARIANT_AXIS_KEYS
        if record.get(field_name) not in (None, "", [], {})
    }
    if not axes:
        return {}
    row: dict[str, Any] = dict(axes)
    for field_name in (
        "sku",
        "barcode",
        "url",
        "image_url",
        "availability",
        "stock_quantity",
        "price",
        "original_price",
        "currency",
        "product_id",
    ):
        if record.get(field_name) not in (None, "", [], {}):
            row[field_name] = record[field_name]
    return row


def _mapped_product_identity_matches(
    base_record: dict[str, Any],
    mapped: dict[str, Any],
    *,
    page_url: str,
) -> bool:
    for field_name in ("product_id", "sku", "handle"):
        base_value = text_or_none(base_record.get(field_name))
        mapped_value = text_or_none(mapped.get(field_name))
        if base_value and mapped_value:
            if base_value == mapped_value:
                return True
    base_url = text_or_none(base_record.get("url"))
    mapped_url = text_or_none(mapped.get("url"))
    if base_url and mapped_url and base_url == mapped_url:
        return True
    if _mapped_record_matches_page_url(
        mapped, page_url
    ) and _mapped_product_family_matches(base_record, mapped):
        return True
    base_title = text_or_none(base_record.get("title"))
    mapped_title = text_or_none(mapped.get("title"))
    if base_title and mapped_title and base_title == mapped_title:
        return True
    return _mapped_product_family_matches(base_record, mapped)


def _mapped_record_matches_page_url(record: dict[str, Any], page_url: str) -> bool:
    page_path = urlsplit(page_url).path.rstrip("/").lower()
    for field_name in ("url", "handle"):
        value = text_or_none(record.get(field_name))
        if value and urlsplit(value).path.rstrip("/").lower() == page_path:
            return True
        if value and f"/{value.strip('/').lower()}" in page_path:
            return True
    return False


def _mapped_product_family_matches(
    base_record: dict[str, Any],
    mapped: dict[str, Any],
) -> bool:
    base_family_tokens = _family_title_tokens(base_record)
    mapped_family_tokens = _family_title_tokens(mapped)
    if not _family_title_tokens_match(base_family_tokens, mapped_family_tokens):
        return False
    base_brand = _normalized_party_name(base_record.get("brand") or base_record.get("vendor"))
    mapped_brand = _normalized_party_name(mapped.get("brand") or mapped.get("vendor"))
    if base_brand and mapped_brand and base_brand != mapped_brand:
        return False
    return _record_has_variant_family_signal(base_record) or _record_has_variant_family_signal(
        mapped
    )


def _family_title_tokens(record: dict[str, Any]) -> list[str]:
    title = clean_text(record.get("title"))
    if not title:
        return []
    drop_tokens = set()
    for raw_value in (
        record.get("brand"),
        record.get("vendor"),
        record.get("color"),
        record.get("size"),
        record.get("style"),
        record.get("material"),
        record.get("finish"),
        record.get("pattern"),
        record.get("scent"),
        record.get("flavor"),
        record.get("capacity"),
        record.get("length"),
        record.get("width"),
    ):
        drop_tokens.update(_title_tokens(raw_value))
    return [token for token in _title_tokens(title) if token not in drop_tokens]


def _normalized_party_name(value: object) -> str:
    tokens = _title_tokens(value)
    return " ".join(tokens)


def _title_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(value).lower())
        if token and (len(token) >= 2 or token.isdigit())
    ]


def _family_title_tokens_match(
    base_tokens: list[str],
    mapped_tokens: list[str],
) -> bool:
    if len(base_tokens) < 2 or len(mapped_tokens) < 2:
        return False
    if base_tokens == mapped_tokens:
        return True
    shorter, longer = (
        (base_tokens, mapped_tokens)
        if len(base_tokens) <= len(mapped_tokens)
        else (mapped_tokens, base_tokens)
    )
    if len(longer) - len(shorter) > 1:
        return False
    return longer[: len(shorter)] == shorter or longer[-len(shorter) :] == shorter


def _record_has_variant_family_signal(record: dict[str, Any]) -> bool:
    variants = record.get("variants")
    if isinstance(variants, list) and variants:
        return True
    return any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in ("color", "size", "style", "material", "variant_count")
    )

def _normalized_state_payload(state_key: str, payload: Any) -> Any:
    if state_key == "__NUXT_DATA__":
        revived = _revive_nuxt_data_array(payload)
        if revived is not None:
            return revived
    return payload

def _revive_nuxt_data_array(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return payload if isinstance(payload, dict) else None
    data_rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("state"), dict):
            state.update(item.get("state") or {})
        if isinstance(item.get("data"), dict):
            data_rows.append(item["data"])
        elif "product" in item and isinstance(item.get("product"), dict):
            data_rows.append({"product": item["product"]})
    revived: dict[str, Any] = {}
    if data_rows:
        revived["data"] = data_rows
    if state:
        revived["state"] = state
    return revived or None

def _looks_like_product_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    has_title = any(key in value for key in ("title", "name", "pn")) or bool(
        text_or_none(
            ((value.get("item") or {}).get("product_description") or {}).get("title")
        )
        if isinstance(value.get("item"), dict)
        else None
    )
    if not has_title:
        return False
    return any(
        key in value
        for key in (
            "variants",
            "availableSizes",
            "variation_hierarchy",
            "options",
            "colors",
            "sizes",
            "prices",
            "representative",
            "product_type",
            "productType",
            "vendor",
            "brand",
            "handle",
            "price",
            "sku",
            "availability",
            "category",
            "type",
            "mrp",
            "Img",
            "offers",
            "images",
            "image",
            "media",
            "featuredImage",
            "featuredMedia",
            "description",
            "body_html",
            "onlineStoreUrl",
        )
    )

def _find_product_payloads(
    value: Any,
    *,
    depth: int = 0,
    limit: int = int(JS_STATE_PRODUCT_PAYLOAD_LIMIT),
) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    payloads: list[dict[str, Any]] = []
    if _looks_like_product_payload(value):
        payloads.append(dict(value))
    if isinstance(value, dict):
        for item in value.values():
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    elif isinstance(value, list):
        for item in value[: int(JS_STATE_LIST_ITERATION_LIMIT)]:
            payloads.extend(_find_product_payloads(item, depth=depth + 1, limit=limit))
    payloads.sort(key=_product_payload_score, reverse=True)
    return payloads[: int(JS_STATE_PRODUCT_PAYLOAD_LIMIT)]

def _product_payload_score(product: dict[str, Any]) -> tuple[int, ...]:
    raw_variants = _product_variant_rows(product)
    raw_options = _as_list(product.get("options"))
    raw_colors = _as_list(product.get("colors"))
    raw_sizes = _as_list(product.get("sizes"))
    product_keys = set(product)
    strong_product_keys = {
        "variants",
        "options",
        "variation_hierarchy",
        "colors",
        "sizes",
        "prices",
        "representative",
        "product_type",
        "productType",
        "vendor",
        "brand",
        "handle",
        "price",
        "sku",
        "availability",
        "category",
        "type",
        "productId",
        "product_id",
        "id",
        "pid",
        "mrp",
        "Img",
        "offers",
        "images",
        "image",
    }
    axis_signal_count = sum(
        1
        for variant in raw_variants
        if isinstance(variant, dict)
        and any(key in variant for key in VARIANT_AXIS_KEYS)
    )
    product_identifier_count = sum(
        1
        for key in ("productId", "product_id", "id", "sku", "handle")
        if product.get(key) not in (None, "", [], {})
    )
    price_signal_count = sum(
        1
        for key in ("price", "prices", "offers")
        if product.get(key) not in (None, "", [], {})
    )
    return (
        len(raw_variants),
        len(raw_options),
        len(raw_colors) + len(raw_sizes),
        axis_signal_count,
        product_identifier_count,
        price_signal_count,
        1 if product.get("images") not in (None, "", [], {}) or product.get("image") not in (None, "", [], {}) else 0,
        len(product_keys & strong_product_keys),
        len(product_keys),
    )

def _map_product_payload(
    product: dict[str, Any],
    *,
    page_url: str,
    category_fallback_from_type: bool,
    field_jmespaths: dict[str, str | list[str]] | None = None,
) -> dict[str, Any]:
    base = _product_base_fields(product, field_jmespaths=field_jmespaths)
    images = _extract_product_images(product, page_url=page_url)
    description_fields = _extract_ecommerce_description_fields(base.get("description"))
    shopify_like = _looks_like_shopify_product(product)
    option_names = _option_names(product.get("options"))
    option_value_labels_by_axis = option_value_labels(product)
    raw_variants = _product_variant_rows(product)
    normalized_variants = [
        normalized
        for variant in raw_variants
        if isinstance(variant, dict)
        if (
            normalized := _normalize_variant(
                variant,
                option_names=option_names,
                option_value_labels=option_value_labels_by_axis,
                page_url=page_url,
                interpret_integral_as_cents=shopify_like,
            )
        )
    ]
    axes = variant_axes(normalized_variants)
    variants = resolve_variants(axes, normalized_variants) if axes else normalized_variants
    active_variant = select_variant(variants, page_url=page_url)
    price = variant_attribute(active_variant, "price")
    if price in (None, "", [], {}):
        raw_current_price = _raw_current_price_value(
            product,
            interpret_integral_as_cents=shopify_like,
        )
        if raw_current_price is not None:
            price = raw_current_price
        else:
            price = normalize_price(
                base.get("price"),
                interpret_integral_as_cents=shopify_like,
            )
    if price in (None, "", [], {}):
        price = _discounted_percentage_price(product)
    original_price = variant_attribute(
        active_variant,
        "original_price",
    )
    if original_price in (None, "", [], {}):
        raw_original_price = _raw_original_price_value(
            product,
            interpret_integral_as_cents=shopify_like,
        )
        original_price = raw_original_price if raw_original_price is not None else normalize_price(
            base.get("original_price"),
            interpret_integral_as_cents=shopify_like,
        )
    currency = (
        variant_attribute(active_variant, "currency")
        or text_or_none(base.get("currency"))
    )
    availability = (
        availability_value(active_variant)
        or availability_value(product)
    )
    product_stock = stock_quantity(active_variant)
    if product_stock is None:
        product_stock = stock_quantity(product)
    color = variant_attribute(active_variant, "color")
    if color in (None, "", [], {}):
        color = variant_axis_value(
            "color",
            product.get("color") or product.get("colour"),
            page_url=page_url,
        )
    size = variant_attribute(active_variant, "size")
    if size in (None, "", [], {}):
        size = variant_axis_value(
            "size",
            product.get("size") or product.get("sz"),
            page_url=page_url,
        )

    # Resolve brand/vendor: dict values need name extraction
    brand_raw = base.get("brand")
    vendor_raw = base.get("vendor")
    brand = _name_or_value(brand_raw) if isinstance(brand_raw, dict) else brand_raw
    vendor = _name_or_value(vendor_raw) if isinstance(vendor_raw, dict) else vendor_raw

    # Category fallback from product_type when flag is set
    category = base.get("category")
    if not category and category_fallback_from_type:
        category = base.get("product_type")

    record = compact_dict(
        {
            "title": base.get("title"),
            "brand": brand,
            "vendor": vendor,
            "url": base.get("url"),
            "handle": base.get("handle"),
            "description": description_fields.get("description"),
            "product_id": base.get("product_id"),
            "category": category,
            "product_type": base.get("product_type"),
            "price": price,
            "original_price": original_price,
            "currency": currency,
            "availability": availability,
            "stock_quantity": product_stock,
            "sku": variant_attribute(active_variant, "sku") or base.get("sku"),
            "barcode": variant_attribute(active_variant, "barcode") or base.get("barcode"),
            "color": color,
            "size": size,
            "image_url": (
                variant_attribute(active_variant, "image_url")
                or (images[0] if images else None)
            ),
            "additional_images": images[1:] if len(images) > 1 else None,
            "image_count": len(images) or None,
            "features": description_fields.get("features"),
            "variants": variants or None,
            "variant_count": len(variants) if variants else None,
            "tags": base.get("tags") if isinstance(base.get("tags"), list) else None,
            "created_at": base.get("created_at"),
            "updated_at": base.get("updated_at"),
            "published_at": base.get("published_at"),
        }
    )
    return record


def _extract_ecommerce_description_fields(value: object) -> dict[str, object]:
    description_html = str(value or "").strip()
    if not description_html:
        return {}
    if "<" not in description_html and "&" not in description_html:
        text = text_or_none(description_html)
        return {"description": text} if text else {}

    soup = BeautifulSoup(description_html, "html.parser")
    for node in soup.select("script, style, iframe, svg, img, picture, source, video"):
        node.decompose()

    features = extract_feature_rows(soup)
    blocks: list[tuple[str, str]] = []
    alias_lookup = surface_alias_lookup("ecommerce_detail", None)
    for node in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p"],
        limit=ECOMMERCE_DESCRIPTION_BLOCK_LIMIT,
    ):
        text = text_or_none(node.get_text(" ", strip=True))
        if text:
            blocks.append((str(node.name).lower(), text))

    lead_parts: list[str] = []
    seen: set[str] = set()
    for tag_name, text in blocks:
        normalized_text = normalize_field_key(text)
        canonical = alias_lookup.get(normalized_text)
        if lead_parts and canonical and canonical != "description":
            break
        lowered = text.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        lead_parts.append(text)

    lead_description = clean_text(" ".join(lead_parts))
    description = text_or_none(lead_description) or text_or_none(
        html_to_text(description_html)
    )
    result: dict[str, object] = {}
    if description:
        result["description"] = description
    if features:
        result["features"] = features
    return result


def _raw_current_price_value(
    product: dict[str, Any],
    *,
    interpret_integral_as_cents: bool,
) -> str | None:
    return _contextual_numeric_value(
        product,
        (
            ("prices", "currentPrice"),
            ("currentPrice",),
            ("pricing_information", "currentPrice"),
            ("pricing_information", "standard_price"),
        ),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )


def _raw_original_price_value(
    product: dict[str, Any],
    *,
    interpret_integral_as_cents: bool,
) -> str | None:
    return _contextual_numeric_value(
        product,
        (
            ("prices", "initialPrice"),
            ("fullPrice",),
            ("pricing_information", "listPrice"),
            ("mrp",),
        ),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )


def _discounted_percentage_price(product: dict[str, Any]) -> str | None:
    list_price = _raw_numeric_value(product, (("mrp",),))
    discount_percent = _raw_numeric_value(product, (("Dis",),))
    if list_price is None or discount_percent is None:
        return None
    try:
        discounted = float(list_price) * (100.0 - float(discount_percent)) / 100.0
    except (TypeError, ValueError):
        return None
    if discounted <= 0:
        return None
    return f"{discounted:.2f}".rstrip("0").rstrip(".") or None

def _contextual_numeric_value(
    product: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
    *,
    interpret_integral_as_cents: bool,
) -> str | None:
    currency = _raw_currency_value(product)
    if not currency:
        return None
    value = _raw_numeric_value(product, paths)
    if value is None:
        return None
    normalized = normalize_price(
        value,
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if normalized is None:
        return None
    if interpret_integral_as_cents:
        try:
            normalized = format(Decimal(normalized).quantize(Decimal("0.01")), "f")
        except (InvalidOperation, ValueError):
            return None
    if normalized.startswith(f"{currency} "):
        return normalized
    return f"{currency} {normalized}"

def _raw_numeric_value(
    product: dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> int | float | None:
    for path in paths:
        current: Any = product
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            return current
    return None

def _raw_currency_value(product: dict[str, Any]) -> str | None:
    for path in (
        ("prices", "currency"),
        ("pricing_information", "currency"),
        ("currency",),
        ("currencyCode",),
        ("priceCurrency",),
    ):
        current: Any = product
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return None

def _product_base_fields(
    product: dict[str, Any],
    *,
    field_jmespaths: dict[str, str | list[str]] | None,
) -> dict[str, Any]:
    base = _glom_product_base_fields(product)
    mapped = _map_jmespath_fields(product, field_jmespaths=field_jmespaths)
    if not mapped:
        return base
    merged = dict(mapped)
    for field_name, value in base.items():
        if field_name not in merged or merged[field_name] in (None, "", [], {}):
            merged[field_name] = value
    return compact_dict(merged)

def _glom_product_base_fields(product: dict[str, Any]) -> dict[str, Any]:
    try:
        base = glom(product, JS_STATE_PRODUCT_FIELD_SPEC, default=None)
    except (GlomError, RuntimeError, TypeError):
        logger.debug("Failed to glom JS-state product payload", exc_info=True)
        base = {}
    if not isinstance(base, dict):
        return {}
    return compact_dict(base)

def _map_jmespath_fields(
    product: dict[str, Any],
    *,
    field_jmespaths: dict[str, str | list[str]] | None,
) -> dict[str, Any]:
    if not isinstance(field_jmespaths, dict) or not field_jmespaths:
        return {}
    mapped: dict[str, Any] = {}
    for field_name, expressions in field_jmespaths.items():
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        value = _first_non_empty_jmespath(product, expressions)
        if value not in (None, "", [], {}):
            mapped[field_name] = value
    return compact_dict(mapped)

def _first_non_empty_jmespath(
    payload: dict[str, Any],
    expressions: str | list[str],
) -> Any:
    candidates = [expressions] if isinstance(expressions, str) else expressions
    if not isinstance(candidates, list):
        return None
    for expression in candidates:
        if not isinstance(expression, str) or not expression.strip():
            continue
        value = jmespath.search(expression, payload)
        if value not in (None, "", [], {}):
            return value
    return None

def _extract_product_images(product: dict[str, Any], *, page_url: str) -> list[str]:
    values = extract_urls(product.get("images"), page_url)
    values.extend(extract_urls(_connection_nodes(product.get("images")), page_url))
    values.extend(_extract_nested_image_urls(product.get("images"), page_url=page_url))
    values.extend(extract_urls(product.get("image"), page_url))
    values.extend(extract_urls(product.get("featuredImage"), page_url))
    values.extend(extract_urls(product.get("featured_image"), page_url))
    values.extend(extract_urls(_connection_nodes(product.get("media")), page_url))
    return dedupe_image_urls(values)

def _extract_nested_image_urls(value: Any, *, page_url: str, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    urls = extract_urls(value, page_url)
    if urls:
        return urls
    nested: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            nested.extend(
                _extract_nested_image_urls(item, page_url=page_url, depth=depth + 1)
            )
    elif isinstance(value, list):
        for item in value[: int(JS_STATE_LIST_ITERATION_LIMIT)]:
            nested.extend(
                _extract_nested_image_urls(item, page_url=page_url, depth=depth + 1)
            )
    return dedupe_image_urls(nested)

def _looks_like_shopify_product(product: dict[str, Any]) -> bool:
    raw_variants = _product_variant_rows(product)
    return any(
        key in product
        for key in (
            "handle",
            "compare_at_price",
            "product_type",
            "body_html",
        )
    ) or any(
        isinstance(variant, dict)
        and any(
            field in variant
            for field in ("option1", "compare_at_price", "inventory_quantity")
        )
        for variant in raw_variants
    )

def _option_names(raw_options: object) -> list[str]:
    names: list[str] = []
    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, str):
                names.append(option)
            elif isinstance(option, dict):
                label = option.get("name") or option.get("title")
                if label:
                    names.append(str(label))
    return names

def _normalize_variant(
    variant: dict[str, Any],
    *,
    option_names: list[str],
    option_value_labels: dict[str, dict[str, str]] | None = None,
    page_url: str,
    interpret_integral_as_cents: bool,
) -> dict[str, Any] | None:
    row: dict[str, Any] = {}
    variant_id = text_or_none(
        variant.get("id") or variant.get("variantId") or variant.get("variant_id")
    )
    explicit_url: str | None = None
    if variant_id:
        row["variant_id"] = variant_id
    try:
        base = glom(variant, JS_STATE_VARIANT_FIELD_SPEC, default=None)
    except (GlomError, RuntimeError, TypeError):
        logger.debug("Failed to glom JS-state variant payload", exc_info=True)
        base = {}
    if not isinstance(base, dict):
        base = {}
    explicit_url = text_or_none(base.get("url"))
    if explicit_url:
        row["url"] = explicit_url
    elif variant_id:
        row["url"] = _variant_url(page_url, variant_id)
    sku = text_or_none(base.get("sku"))
    if sku:
        row["sku"] = sku
    barcode = text_or_none(base.get("barcode"))
    if barcode:
        row["barcode"] = barcode
    price = normalize_price(
        base.get("price"),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if price is not None:
        row["price"] = price
    original_price = normalize_price(
        base.get("original_price"),
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    if original_price is not None:
        row["original_price"] = original_price
    currency = text_or_none(base.get("currency"))
    if currency:
        row["currency"] = currency
    availability = availability_value(variant)
    if availability:
        row["availability"] = availability
    variant_stock = stock_quantity(variant)
    if variant_stock is not None:
        row["stock_quantity"] = variant_stock
    image_url = next(
        iter(
            extract_urls(
                variant.get("featured_image") or variant.get("featuredImage") or variant.get("image"),
                page_url,
            )
        ),
        None,
    )
    if image_url:
        row["image_url"] = image_url
    selection_values = variant_selection_values(
        variant,
        option_names=option_names,
    )
    if selection_values:
        row["_selection_values"] = selection_values
    option_values = variant_option_values(
        variant,
        option_names=option_names,
        option_value_labels=option_value_labels,
    )
    if option_values:
        row["option_values"] = option_values
        if option_values.get("color"):
            row["color"] = option_values["color"]
        if option_values.get("size"):
            row["size"] = option_values["size"]
    for field_name in ("title", "name", "color", "size"):
        raw_value = variant.get(field_name)
        value = (
            variant_axis_value(field_name, raw_value, page_url=page_url)
            if field_name in {"color", "size"}
            else text_or_none(raw_value)
        )
        if value and field_name not in row:
            row["title" if field_name == "name" else field_name] = value
    return row or None


def _variant_url(page_url: str, variant_id: str) -> str:
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "variant"
    ]
    query_pairs.append(("variant", variant_id))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))

def _connection_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [node for node in nodes if isinstance(node, dict)]
        edges = value.get("edges")
        if isinstance(edges, list):
            return [
                node
                for edge in edges
                if isinstance(edge, dict)
                for node in [edge.get("node")]
                if isinstance(node, dict)
            ]
    return []

def _name_or_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("value")
    return value
