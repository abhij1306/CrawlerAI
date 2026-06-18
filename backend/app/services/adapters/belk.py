from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.config.extraction_rules import (
    BELK_BRAND_SELECTORS,
    BELK_CARD_TITLE_ATTRS,
    BELK_COLOR_MAP_KEY,
    BELK_COLOR_NAME_KEYS,
    BELK_IMAGE_SELECTORS,
    BELK_PRODUCT_BARCODE_KEYS,
    BELK_PRICE_SELECTORS,
    BELK_PRODUCT_BRAND_KEYS,
    BELK_PRODUCT_CARD_SELECTORS,
    BELK_PRODUCT_ID_KEYS,
    BELK_PRODUCT_IMAGE_KEYS,
    BELK_PRODUCT_ORIGINAL_PRICE_KEYS,
    BELK_PRODUCT_PRICE_KEYS,
    BELK_PRODUCT_TITLE_KEYS,
    BELK_PRODUCT_URL_KEYS,
    BELK_SKU_ARRAY_ID_KEY,
    BELK_SKU_ARRAY_IMAGE_KEY,
    BELK_SKU_ARRAY_INVENTORY_KEY,
    BELK_SKU_ARRAY_ORIGINAL_PRICE_KEY,
    BELK_SKU_ARRAY_OUT_OF_STOCK_KEY,
    BELK_SKU_ARRAY_PRICE_KEY,
    BELK_SKU_ARRAY_UPC_KEY,
    BELK_TITLE_MAX_CHARS,
    BELK_TITLE_MIN_CHARS,
    BELK_TITLE_SELECTORS,
    BELK_VARIANT_ID_KEYS,
    LISTING_BRAND_MAX_WORDS,
)
from app.services.extract.listing_candidate_ranking import looks_like_utility_title
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_normalization.contract import (
    flatten_variants_for_public_output,
)
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_price_text,
    finalize_record,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
)
from app.services.js_state.helpers import compact_dict, normalize_price
from app.services.structured_sources import harvest_js_state_objects

_BELK_PRODUCT_TITLE_KEY_SET = frozenset(BELK_PRODUCT_TITLE_KEYS)
_BELK_PRODUCT_URL_KEY_SET = frozenset(BELK_PRODUCT_URL_KEYS)
_BELK_PRODUCT_SIGNAL_KEY_SET = frozenset(
    (*BELK_PRODUCT_BRAND_KEYS, *BELK_PRODUCT_PRICE_KEYS, *BELK_PRODUCT_IMAGE_KEYS)
)
_BELK_VARIANT_ID_KEY_SET = frozenset(BELK_VARIANT_ID_KEYS)


class BelkAdapter(BaseAdapter):
    name = "belk"
    platform_family = "belk"

    async def can_handle(self, url: str, html: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return host == "belk.com" or host.endswith(".belk.com")

    async def extract(self, url: str, html: str, surface: str, proxy: str | None = None) -> AdapterResult:
        normalized_surface = str(surface or "").strip().lower()
        records: list[dict[str, Any]] = []
        if normalized_surface == "ecommerce_listing":
            records.extend(_extract_listing_records(url, html))
        elif normalized_surface == "ecommerce_detail":
            record = _extract_detail_record(url, html)
            if record:
                records.append(record)
        return self._result(records)


def _extract_listing_records(page_url: str, html: str) -> list[dict[str, Any]]:
    product_limit = max(0, int(adapter_runtime_settings.belk_max_products))
    if product_limit <= 0:
        return []
    state_index = _state_product_index(page_url, html)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    state_by_identity = {
        identity: record
        for record in state_index.values()
        if (identity := _belk_record_identity(record))
    }
    for record in _dom_listing_records(page_url, html):
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        state_record = state_index.get(url)
        if state_record is None:
            identity = _belk_record_identity(record)
            if identity:
                state_record = state_by_identity.get(identity)
        if state_record:
            merged = dict(state_record)
            merged.update({key: value for key, value in record.items() if value not in (None, "", [], {})})
            record = merged
        finalized = _finalize_adapter_record(record, surface="ecommerce_listing")
        final_url = str(finalized.get("url") or "")
        if not final_url or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        records.append(finalized)
        if len(records) >= product_limit:
            return records
    for url, record in state_index.items():
        if url in seen_urls:
            continue
        finalized = _finalize_adapter_record(record, surface="ecommerce_listing")
        final_url = str(finalized.get("url") or "")
        if not final_url or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        records.append(finalized)
        if len(records) >= product_limit:
            break
    return records[:product_limit]


def _extract_detail_record(page_url: str, html: str) -> dict[str, Any] | None:
    page_path = (urlparse(page_url).path or "").rstrip("/").lower()
    for record in _state_product_records(page_url, html, target_path=page_path):
        record_url = str(record.get("url") or "")
        if (urlparse(record_url).path or "").rstrip("/").lower() == page_path:
            return _finalize_adapter_record(record, surface="ecommerce_detail")
    dom_records = _dom_listing_records(page_url, html)
    if len(dom_records) == 1:
        return _finalize_adapter_record(dom_records[0], surface="ecommerce_detail")
    return None


def _state_product_index(page_url: str, html: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in _state_product_records(page_url, html):
        url = str(record.get("url") or "")
        if url:
            index[url] = record
        if len(index) >= adapter_runtime_settings.belk_max_products:
            return index
    return index


def _state_product_records(
    page_url: str,
    html: str,
    *,
    target_path: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root in _belk_state_roots(html):
        parts = _collect_state_payload_parts(root)
        variant_objects_by_id = _variant_objects_by_id(parts.variant_objects)
        for product in parts.products:
            record = _record_from_payload(
                product,
                page_url=page_url,
                variant_objects_by_id=variant_objects_by_id,
                color_name_by_code=parts.color_name_by_code,
            )
            if target_path and _record_path(record) == target_path:
                return [record]
            records.append(record)
            if len(records) >= adapter_runtime_settings.belk_max_products:
                return records
    return records


def _record_path(record: dict[str, Any]) -> str:
    return (urlparse(str(record.get("url") or "")).path or "").rstrip("/").lower()


def _belk_state_roots(html: str) -> list[Any]:
    raw = str(html or "").strip()
    roots: list[Any] = []
    if raw and raw[0] in "[{":
        try:
            roots.append(json.loads(raw))
        except json.JSONDecodeError:
            # Not a raw JSON document; fall back to JS-state harvesting below.
            pass
    roots.extend(harvest_js_state_objects(None, html).values())
    return roots


@dataclass(slots=True)
class _BelkStatePayloadParts:
    products: list[dict[str, Any]]
    variant_objects: list[dict[str, Any]]
    color_name_by_code: dict[str, str]


def _collect_state_payload_parts(root: object) -> _BelkStatePayloadParts:
    products: list[dict[str, Any]] = []
    variant_objects: list[dict[str, Any]] = []
    color_name_by_code: dict[str, str] = {}
    product_limit = adapter_runtime_settings.belk_max_products

    def visit(node: object, depth: int) -> None:
        if depth > 60:
            return
        if isinstance(node, dict):
            color_map = node.get(BELK_COLOR_MAP_KEY)
            if isinstance(color_map, dict):
                for code, value in color_map.items():
                    code_text = clean_text(code)
                    if not code_text or code_text in color_name_by_code:
                        continue
                    name = _color_name_from_entry(value)
                    if name:
                        color_name_by_code[code_text] = name

            keys = {str(k) for k in node.keys()}
            if (
                len(variant_objects) < product_limit
                and (keys & _BELK_VARIANT_ID_KEY_SET)
                and "size" in keys
            ):
                variant_objects.append(node)
            if (
                len(products) < product_limit
                and _looks_like_product_payload(node)
            ):
                products.append(node)

            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
            return
        if isinstance(node, list):
            for child in node:
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)

    visit(root, 0)
    return _BelkStatePayloadParts(
        products=products,
        variant_objects=variant_objects,
        color_name_by_code=color_name_by_code,
    )


def _color_name_from_entry(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in BELK_COLOR_NAME_KEYS:
        name = clean_text(value.get(key))
        if name:
            return name
    return None


def _looks_like_product_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload)
    if not (
        keys & _BELK_PRODUCT_TITLE_KEY_SET
        and keys & _BELK_PRODUCT_URL_KEY_SET
        and keys & _BELK_PRODUCT_SIGNAL_KEY_SET
    ):
        return False
    return bool(
        _first_payload_field(payload, field_name="title", page_url="", keys=BELK_PRODUCT_TITLE_KEYS)
        and _first_payload_field(payload, field_name="url", page_url="", keys=BELK_PRODUCT_URL_KEYS)
        and (
            _first_payload_field(payload, field_name="brand", page_url="", keys=BELK_PRODUCT_BRAND_KEYS)
            or _first_payload_field(payload, field_name="price", page_url="", keys=BELK_PRODUCT_PRICE_KEYS)
            or _first_payload_field(payload, field_name="image_url", page_url="", keys=BELK_PRODUCT_IMAGE_KEYS)
        )
    )


def _record_from_payload(
    product: dict[str, Any],
    *,
    page_url: str,
    variant_objects: list[dict[str, Any]] | None = None,
    variant_objects_by_id: dict[str, dict[str, Any]] | None = None,
    color_name_by_code: dict[str, str] | None = None,
) -> dict[str, Any]:
    title = _first_payload_field(product, field_name="title", page_url=page_url, keys=BELK_PRODUCT_TITLE_KEYS)
    brand = _first_payload_field(product, field_name="brand", page_url=page_url, keys=BELK_PRODUCT_BRAND_KEYS)
    price_value = _first_payload_field(product, field_name="price", page_url=page_url, keys=BELK_PRODUCT_PRICE_KEYS)
    original_price_value = _first_payload_field(
        product,
        field_name="original_price",
        page_url=page_url,
        keys=BELK_PRODUCT_ORIGINAL_PRICE_KEYS,
    )
    image = _first_payload_field(product, field_name="image_url", page_url=page_url, keys=BELK_PRODUCT_IMAGE_KEYS)
    url = _first_payload_field(product, field_name="url", page_url=page_url, keys=BELK_PRODUCT_URL_KEYS)
    # Belk's React PDP `utag_data` exposes per-SKU parallel arrays (sku_id[i] <-> sku_upc[i] <-> ...).
    # Build variant rows from those arrays joined to the variant objects, and take the
    # product-level barcode from the selected/first in-stock variant UPC.
    sku_variants = _variants_from_sku_arrays(
        product,
        page_url=page_url,
        variant_objects=variant_objects or [],
        variant_objects_by_id=variant_objects_by_id,
        color_name_by_code=color_name_by_code or {},
    )
    if sku_variants:
        barcode = _primary_variant_barcode(sku_variants)
    else:
        barcode = _first_nested_payload_field(
            product,
            field_name="barcode",
            page_url=page_url,
            keys=BELK_PRODUCT_BARCODE_KEYS,
        )
    if brand in (None, "", [], {}):
        brand = _infer_belk_brand_from_url(url=str(url or ""), title=title)
    currency = coerce_field_value("currency", product, page_url)
    if currency in (None, "", [], {}):
        for key in (*BELK_PRODUCT_PRICE_KEYS, *BELK_PRODUCT_ORIGINAL_PRICE_KEYS):
            nested_value = product.get(key)
            if not isinstance(nested_value, dict):
                continue
            currency = coerce_field_value("currency", nested_value, page_url)
            if currency not in (None, "", [], {}):
                break
    variants = sku_variants or _variants_from_payload(
        product,
        page_url=page_url,
        product_url=str(url or page_url or ""),
        currency=currency,
    )
    return compact_dict(
        {
            "title": title,
            "brand": brand,
            "price": normalize_price(price_value, interpret_integral_as_cents=False),
            "original_price": normalize_price(original_price_value, interpret_integral_as_cents=False),
            "currency": currency,
            "image_url": image,
            "sku_upc": barcode,
            "barcode": barcode,
            "product_id": _first_payload_field(product, field_name="product_id", page_url=page_url, keys=BELK_PRODUCT_ID_KEYS),
            "url": url,
            "variants": variants,
            "variant_count": len(variants or []) or None,
        }
    )


def _variants_from_payload(
    product: dict[str, Any],
    *,
    page_url: str,
    product_url: str,
    currency: object,
) -> list[dict[str, object]] | None:
    raw_variants = product.get("variants")
    if not isinstance(raw_variants, list):
        return None
    option_names = _option_names(product.get("options"))
    variants: list[dict[str, object]] = []
    for raw_variant in raw_variants:
        if not isinstance(raw_variant, dict):
            continue
        variant = _variant_from_payload(
            raw_variant,
            option_names=option_names,
            page_url=page_url,
            currency=currency,
        )
        if variant:
            variants.append(variant)
    return flatten_variants_for_public_output(variants, page_url=product_url or page_url)


def _option_names(raw_options: object) -> list[str]:
    names: list[str] = []
    if not isinstance(raw_options, list):
        return names
    for option in raw_options:
        label: object
        if isinstance(option, str):
            label = option
        elif isinstance(option, dict):
            label = option.get("name") or option.get("title") or option.get("label")
        else:
            label = None
        cleaned = clean_text(label)
        if cleaned:
            names.append(cleaned)
    return names


def _variant_from_payload(
    variant: dict[str, Any],
    *,
    option_names: list[str],
    page_url: str,
    currency: object,
) -> dict[str, object] | None:
    row: dict[str, object] = {}
    sku = clean_text(
        variant.get("sku")
        or variant.get("skuId")
        or variant.get("sku_id")
        or variant.get("id")
        or variant.get("variantId")
        or variant.get("variant_id")
    )
    if sku:
        row["sku"] = sku
    price = normalize_price(
        variant.get("price") or variant.get("salePrice") or variant.get("sellingPrice"),
        interpret_integral_as_cents=False,
    )
    if price is not None:
        row["price"] = price
    variant_currency = coerce_field_value("currency", variant, page_url) or currency
    if variant_currency not in (None, "", [], {}):
        row["currency"] = str(variant_currency)
    availability = _variant_availability(variant)
    if availability:
        row["availability"] = availability
    stock_quantity = _variant_stock_quantity(variant)
    if stock_quantity is not None:
        row["stock_quantity"] = stock_quantity
    image_url = _variant_image_url(variant, page_url=page_url)
    if image_url:
        row["image_url"] = image_url
    option_values = _variant_option_values(variant, option_names=option_names)
    if option_values:
        row["option_values"] = option_values
        for axis_key in ("color", "size"):
            if option_values.get(axis_key):
                row[axis_key] = option_values[axis_key]
    if not any(row.get(axis_key) for axis_key in ("color", "size")):
        for axis_key in ("color", "size"):
            value = clean_text(variant.get(axis_key))
            if value:
                row[axis_key] = value
    return row or None


def _variant_option_values(
    variant: dict[str, Any],
    *,
    option_names: list[str],
) -> dict[str, str]:
    option_values: dict[str, str] = {}
    raw_options = variant.get("options")
    variant_options = raw_options if isinstance(raw_options, list) else []
    max_options = max(len(option_names), len(variant_options), 3)
    for index in range(1, max_options + 1):
        axis_name = option_names[index - 1] if index - 1 < len(option_names) else f"option_{index}"
        axis_key = normalized_variant_axis_key(axis_name)
        if not axis_key:
            continue
        value = variant.get(f"option{index}")
        if value in (None, "", [], {}) and index - 1 < len(variant_options):
            value = variant_options[index - 1]
        cleaned = clean_text(value)
        if cleaned:
            option_values[axis_key] = cleaned
    return option_values


def _variant_availability(variant: dict[str, Any]) -> str | None:
    value = variant.get("availability")
    coerced = coerce_field_value("availability", value, "")
    if coerced:
        return str(coerced)
    available = variant.get("available")
    if isinstance(available, bool):
        return "in_stock" if available else "out_of_stock"
    if isinstance(available, (int, float)):
        return "in_stock" if available else "out_of_stock"
    if isinstance(available, str):
        lowered = available.strip().lower()
        if lowered in {"true", "1", "yes", "available", "in stock", "instock"}:
            return "in_stock"
        if lowered in {"false", "0", "no", "sold out", "out of stock", "outofstock"}:
            return "out_of_stock"
    return None


def _variant_stock_quantity(variant: dict[str, Any]) -> int | None:
    for key in ("stock_quantity", "stockQuantity", "inventory_quantity", "inventoryQuantity"):
        value = variant.get(key)
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _variant_image_url(variant: dict[str, Any], *, page_url: str) -> str | None:
    image = variant.get("image") or variant.get("featured_image") or variant.get("featuredImage")
    if isinstance(image, dict):
        image = image.get("url") or image.get("src")
    cleaned = clean_text(image)
    return absolute_url(page_url, cleaned) if cleaned else None


def _dom_listing_records(page_url: str, html: str) -> list[dict[str, Any]]:
    parser = LexborHTMLParser(html)
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for node in _product_card_nodes(parser):
        record = _record_from_card(node, page_url=page_url)
        url = str(record.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        records.append(record)
        if len(records) >= adapter_runtime_settings.belk_max_products:
            break
    return records


def _product_card_nodes(parser: LexborHTMLParser) -> list[Any]:
    nodes: list[Any] = []
    seen: set[str] = set()
    for selector in BELK_PRODUCT_CARD_SELECTORS:
        try:
            matches = parser.css(str(selector))
        except Exception:
            matches = []
        for node in matches:
            key = str(getattr(node, "html", "") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            nodes.append(node)
    return nodes


def _record_from_card(node: Any, *, page_url: str) -> dict[str, Any]:
    anchor = node.css_first("a[href]")
    href = _attr(anchor, "href") if anchor is not None else ""
    image = _first_selector_attr(node, BELK_IMAGE_SELECTORS, ("src", "data-src", "srcset"))
    image_title = _first_selector_attr(
        node,
        BELK_IMAGE_SELECTORS,
        ("alt", "title", "aria-label"),
    )
    title = (
        _first_belk_title(node)
        or _first_node_attr(node, BELK_CARD_TITLE_ATTRS)
        or image_title
    )
    url = absolute_url(page_url, href)
    brand = (
        _first_selector_text(node, BELK_BRAND_SELECTORS)
        or infer_brand_from_title_marker(title)
        or _infer_belk_brand_from_url(url=url, title=title)
    )
    return compact_dict(
        {
            "title": title,
            "brand": brand,
            "price": normalize_price(
                _first_selector_text(node, BELK_PRICE_SELECTORS)
                or extract_price_text(node.text(separator=" ", strip=True), prefer_last=False),
                interpret_integral_as_cents=False,
            ),
            "image_url": absolute_url(page_url, _srcset_first(image)) if image else None,
            "product_id": _attr(node, "data-cnstrc-item-id")
            or _attr(node, "data-tile-pid"),
            "url": url,
        }
    )


def _finalize_adapter_record(record: dict[str, Any], *, surface: str) -> dict[str, Any]:
    shaped = dict(record)
    shaped["_source"] = "belk_adapter"
    return finalize_record(shaped, surface=surface)


def _unwrap_single_element(value: Any) -> Any:
    """Unwrap single-element-list values used by Belk's `utag_data` analytics payload.

    Belk PDPs expose product fields (including the UPC under `sku_upc`) inside a
    Tealium `utag_data` object where every scalar is wrapped in a one-item list,
    e.g. ``"sku_upc": ["0655772019097"]``. Coercion does not unwrap these, so the
    UPC was dropped and titles leaked as ``"['...']"``. Unwrap only the exact
    single-scalar-list shape; leave dicts and multi-element lists untouched.
    """
    if isinstance(value, list) and len(value) == 1 and not isinstance(value[0], (dict, list)):
        return value[0]
    return value


def _first_payload_field(
    payload: dict[str, Any],
    *,
    field_name: str,
    page_url: str,
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = coerce_field_value(field_name, _unwrap_single_element(payload.get(key)), page_url)
        if value:
            return str(value)
    return None


_BARCODE_SEARCH_MAX_DEPTH = 5


def _looks_like_barcode(value: str) -> bool:
    """Validate a coerced value looks like a barcode (8-14 digits)."""
    normalized = str(value or "").strip()
    return normalized.isdigit() and 8 <= len(normalized) <= 14


def _first_nested_payload_field(
    payload: dict[str, Any],
    *,
    field_name: str,
    page_url: str,
    keys: tuple[str, ...],
) -> str | None:
    direct = _first_payload_field(payload, field_name=field_name, page_url=page_url, keys=keys)
    if direct:
        return direct
    normalized_keys = {str(key).casefold() for key in keys}
    stack: list[tuple[object, int]] = [(payload, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _BARCODE_SEARCH_MAX_DEPTH:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).casefold() in normalized_keys:
                    coerced = coerce_field_value(
                        field_name, _unwrap_single_element(value), page_url
                    )
                    if coerced and _looks_like_barcode(str(coerced)):
                        return str(coerced)
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
            continue
        if isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
    return None


def _infer_belk_brand_from_url(*, url: str, title: object) -> str | None:
    return infer_brand_from_product_url(url=url, title=title) or _infer_belk_brand_from_slug_prefix(
        url=url,
        title=title,
    )


def _infer_belk_brand_from_slug_prefix(*, url: str, title: object) -> str | None:
    title_tokens = _belk_slug_tokens(title)
    if len(title_tokens) < 2:
        return None
    path_parts = [
        part.split(".", 1)[0]
        for part in (urlparse(str(url or "")).path or "").split("/")
        if part
    ]
    slug = ""
    for index, part in enumerate(path_parts):
        if part.lower() == "p" and index + 1 < len(path_parts):
            slug = path_parts[index + 1]
            break
    if not slug and path_parts:
        slug = path_parts[-1]
    path_tokens = _belk_slug_tokens(slug)
    if len(path_tokens) < 2:
        return None
    min_match = min(3, len(title_tokens))
    for start in range(1, len(path_tokens)):
        if path_tokens[start] != title_tokens[0]:
            continue
        matched = 0
        while (
            matched < len(title_tokens)
            and start + matched < len(path_tokens)
            and path_tokens[start + matched] == title_tokens[matched]
        ):
            matched += 1
        if matched < min_match:
            continue
        brand_tokens = path_tokens[:start]
        if not brand_tokens or len(brand_tokens) > LISTING_BRAND_MAX_WORDS:
            continue
        return " ".join(token.capitalize() for token in brand_tokens)
    return None


def _belk_slug_tokens(value: object) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if token
    ]


def _belk_record_identity(record: dict[str, Any]) -> str:
    product_id = clean_text(record.get("product_id") or record.get("productId") or record.get("sku"))
    if product_id:
        return product_id.lower()
    return _belk_identity_from_url(str(record.get("url") or ""))


def _belk_identity_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path
    match = re.search(r"/([^/?#]+)/?$", path)
    segment = str(match.group(1) if match is not None else "").strip().lower()
    if not segment:
        return ""
    return re.sub(r"\.(?:html?|php|aspx?)$", "", segment)


def _first_node_attr(node: Any, attrs: tuple[str, ...]) -> str | None:
    for attr in attrs:
        value = clean_text(_attr(node, str(attr)))
        if _valid_belk_title(value):
            return value
    return None


def _first_selector_text(node: Any, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        try:
            match = node.css_first(str(selector))
        except Exception:
            match = None
        if match is None:
            continue
        value = clean_text(match.text(strip=True)) or _attr(match, "title") or _attr(match, "aria-label")
        if value:
            return value
    return None


def _first_belk_title(node: Any) -> str | None:
    for selector in BELK_TITLE_SELECTORS:
        try:
            match = node.css_first(str(selector))
        except Exception:
            match = None
        if match is None:
            continue
        value = clean_text(match.text(strip=True)) or _attr(match, "title") or _attr(match, "aria-label")
        if _valid_belk_title(value):
            return value
    return None


def _valid_belk_title(value: object) -> bool:
    text = clean_text(str(value or ""))
    if len(text) < BELK_TITLE_MIN_CHARS or len(text) > BELK_TITLE_MAX_CHARS:
        return False
    return not looks_like_utility_title(text)


def _first_selector_attr(node: Any, selectors: tuple[str, ...], attrs: tuple[str, ...]) -> str | None:
    for selector in selectors:
        try:
            matches = node.css(str(selector))
        except Exception:
            matches = []
        for match in matches:
            for attr in attrs:
                value = _attr(match, attr)
                if value:
                    return value
    return None


def _attr(node: Any, name: str) -> str:
    attrs = getattr(node, "attributes", {}) or {}
    return str(attrs.get(name) or "").strip()


def _srcset_first(value: object) -> str:
    return str(value or "").split(",", 1)[0].strip().split(" ", 1)[0].strip()


def _sku_array(product: dict[str, Any], key: str) -> list[Any]:
    value = product.get(key)
    return value if isinstance(value, list) else []


def _variant_objects_by_id(variant_objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for obj in variant_objects:
        if not isinstance(obj, dict):
            continue
        for key in BELK_VARIANT_ID_KEYS:
            vid = clean_text(obj.get(key))
            if vid:
                index.setdefault(vid, obj)
                break
    return index


def _variant_size_label(obj: dict[str, Any]) -> str | None:
    size = obj.get("size")
    if isinstance(size, dict):
        label = clean_text(size.get("sizeName") or size.get("label") or size.get("name"))
        if label:
            return label
    return clean_text(obj.get("size")) if not isinstance(obj.get("size"), dict) else None


def _variant_color_label(
    obj: dict[str, Any],
    color_name_by_code: dict[str, str],
) -> str | None:
    """Resolve a variant object's color to its display name.

    The variant object's ``color`` is Belk's numeric color code; the human name
    lives in the RSC ``colors`` map. Fall back to a non-numeric ``color`` value
    if one is already a label, but never leak a raw numeric code.
    """
    raw_color = obj.get("color")
    if isinstance(raw_color, dict):
        label = clean_text(
            raw_color.get("name") or raw_color.get("label") or raw_color.get("colorName")
        )
        return label or None
    code = clean_text(raw_color)
    if not code:
        return None
    mapped = clean_text(color_name_by_code.get(code))
    if mapped:
        return mapped
    # A bare numeric code with no map entry is not a usable colorway label.
    return None if code.isdigit() else code


def _variants_from_sku_arrays(
    product: dict[str, Any],
    *,
    page_url: str,
    variant_objects: list[dict[str, Any]],
    variant_objects_by_id: dict[str, dict[str, Any]] | None = None,
    color_name_by_code: dict[str, str] | None = None,
) -> list[dict[str, object]] | None:
    """Build variant rows from Belk's per-SKU parallel `utag_data` arrays.

    Each array index is one sellable SKU; arrays are positionally aligned. Each
    variant row gets its own UPC (`barcode`), price, availability, and image. Size
    and color labels are joined from the variant objects via `variantId == sku_id`.
    Each variant object carries a numeric color code that resolves to a display
    name via `color_name_by_code` (the RSC `colors` map), so multi-colorway PDPs
    keep each variant's own colorway.
    """
    sku_ids = _sku_array(product, BELK_SKU_ARRAY_ID_KEY)
    sku_upcs = _sku_array(product, BELK_SKU_ARRAY_UPC_KEY)
    if not sku_ids or not sku_upcs:
        return None
    prices = _sku_array(product, BELK_SKU_ARRAY_PRICE_KEY)
    original_prices = _sku_array(product, BELK_SKU_ARRAY_ORIGINAL_PRICE_KEY)
    inventories = _sku_array(product, BELK_SKU_ARRAY_INVENTORY_KEY)
    out_of_stock = _sku_array(product, BELK_SKU_ARRAY_OUT_OF_STOCK_KEY)
    images = _sku_array(product, BELK_SKU_ARRAY_IMAGE_KEY)
    objects_by_id = variant_objects_by_id or _variant_objects_by_id(variant_objects)

    def at(seq: list[Any], i: int) -> Any:
        return seq[i] if i < len(seq) else None

    rows: list[dict[str, object]] = []
    for index, sku_id in enumerate(sku_ids):
        sku_id_text = clean_text(sku_id)
        upc = clean_text(at(sku_upcs, index))
        if not upc or not _looks_like_barcode(upc):
            continue
        row: dict[str, object] = {"barcode": upc}
        if sku_id_text:
            row["sku"] = sku_id_text
        price = normalize_price(at(prices, index), interpret_integral_as_cents=False)
        if price is not None:
            row["price"] = price
        original_price = normalize_price(at(original_prices, index), interpret_integral_as_cents=False)
        if original_price is not None:
            row["original_price"] = original_price
        oos = at(out_of_stock, index)
        if isinstance(oos, bool):
            row["availability"] = "out_of_stock" if oos else "in_stock"
        inv = at(inventories, index)
        try:
            inv_int = int(str(inv).strip())
            row["stock_quantity"] = inv_int
            row.setdefault("availability", "in_stock" if inv_int > 0 else "out_of_stock")
        except (TypeError, ValueError):
            # Inventory value missing or non-numeric; leave stock fields unset.
            pass
        image_value = clean_text(at(images, index))
        if image_value:
            row["image_url"] = absolute_url(page_url, image_value)
        obj = objects_by_id.get(sku_id_text) if sku_id_text else None
        if isinstance(obj, dict):
            size_label = _variant_size_label(obj)
            if size_label:
                row["size"] = size_label
            color_label = _variant_color_label(obj, color_name_by_code or {})
            if color_label:
                row["color"] = color_label
        rows.append(row)
    if not rows:
        return None
    return flatten_variants_for_public_output(rows, page_url=page_url)


def _primary_variant_barcode(variants: list[dict[str, object]]) -> str | None:
    """Pick the product-level UPC: first in-stock variant, else first variant."""
    for variant in variants:
        if str(variant.get("availability") or "").strip() == "in_stock":
            barcode = clean_text(variant.get("barcode"))
            if barcode:
                return barcode
    for variant in variants:
        barcode = clean_text(variant.get("barcode"))
        if barcode:
            return barcode
    return None
