from __future__ import annotations

from typing import Literal
from app.core.config.field_mappings import (
    ECOMMERCE_IMAGE_SOURCE_KEYS,
    ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS,
    ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES,
)
from app.core.config.extraction_rules import VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS
from app.core.config.variant_policy import AXIS_NAME_ALIASES
from app.extraction.collectors._helpers import evidence, json_objects
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.ids import stable_id


class JsStateCollector:
    collector_id = "js_state"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        payloads = [ref for ref in bundle.artifacts if ref.artifact_type == "js_state"]
        out: list[Evidence] = []
        for ref in payloads:
            data = artifacts.read_json(ref)
            for path, obj in json_objects(data):
                if isinstance(obj, dict):
                    out.extend(network_row(bundle, ref.artifact_id, path, obj))
        return tuple(out)


def network_row(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    *,
    collector_id: str = "js_state",
) -> list[Evidence]:
    out: list[Evidence] = []
    if _looks_like_variant(obj):
        return _variant_row(bundle, artifact_id, path, obj, collector_id=collector_id)
    mapped_keys = tuple(key for key in ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES if key in obj)
    if not mapped_keys:
        return out
    product_context = _has_product_context(path, obj)
    offer_context = _has_offer_context(path, obj, product_context=product_context)
    if not product_context and not offer_context:
        return out
    group = f"offer:{artifact_id}:{path}" if offer_context else None
    product_subject = evidence(
        bundle,
        "url",
        "url",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="url_component", value="url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        directness="inferred",
        confidence=0.0,
    ).subject_id
    for key in mapped_keys:
        fact = ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES[key]
        if fact.startswith("product.") and not product_context:
            continue
        if fact.startswith("offer.") and not offer_context:
            continue
        for index, value in enumerate(_source_values(key, obj.get(key))):
            if value in (None, "", [], {}):
                continue
            entity_type: Literal["offer", "asset", "product"] = "offer" if fact.startswith("offer.") else "asset" if fact.startswith("asset.") else "product"
            hint = EntityHint(entity_type=entity_type, sku=str(obj.get("sku") or "").strip() or None)
            suffix = f"/{index}" if key in ECOMMERCE_IMAGE_SOURCE_KEYS else ""
            out.append(
                evidence(
                    bundle,
                    artifact_id,
                    collector_id,
                    fact,
                    value,
                    SourceLocator(kind="script_path", value=f"{path}/{key}{suffix}"),
                    group_id=group if fact.startswith("offer.") else None,
                    hint=hint,
                    directness="embedded",
                    confidence=0.8,
                    parent_subject_id=product_subject if fact.startswith(("offer.", "asset.")) else None,
                )
            )
    return out


def _has_product_context(path: str, obj: dict) -> bool:
    keys = set(obj)
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = {token.casefold() for token in str(path).replace("[", "/").split("/") if token}
    product_keys = keys & ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
    complete_offer = "price" in keys and bool(keys & {"currency", "currencyCode"})
    return "product" in type_name or bool(path_tokens & {"product", "products"}) or len(product_keys) >= 2 or (bool(product_keys & {"name", "productName", "title"}) and complete_offer)


def _has_offer_context(path: str, obj: dict, *, product_context: bool) -> bool:
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = {token.casefold() for token in str(path).replace("[", "/").split("/") if token}
    return product_context or "offer" in type_name or bool(path_tokens & ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS)


def _source_values(key: str, value: object) -> tuple[object, ...]:
    if key in ECOMMERCE_IMAGE_SOURCE_KEYS and isinstance(value, list):
        return tuple(_scalar_value(item) for item in value)
    return (_scalar_value(value),)


def _variant_row(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    *,
    collector_id: str,
) -> list[Evidence]:
    if not _looks_like_variant(obj):
        return []
    variant_id = _variant_identity_value(obj)
    sku = str(_scalar_value(obj.get("sku") or obj.get("skuId") or obj.get("sku_id") or "") or "").strip()
    hint = EntityHint(
        entity_type="variant",
        variant_id=variant_id,
        sku=sku or None,
        selected=bool(obj.get("selected") or obj.get("isSelected")) if "selected" in obj or "isSelected" in obj else None,
    )
    group = f"variant:{artifact_id}:{path}"
    subject_id = stable_id(
        "subject",
        bundle.bundle_id,
        artifact_id,
        "variant",
        hint.variant_id or sku or group,
    )
    product_subject = evidence(
        bundle,
        "url",
        "url",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="url_component", value="url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        directness="inferred",
        confidence=0.0,
    ).subject_id
    fields = _variant_fields(obj)
    out = [
        evidence(
            bundle,
            artifact_id,
            collector_id,
            fact,
            value,
            SourceLocator(kind="script_path", value=f"{path}/{name}"),
            group_id=group,
            hint=hint,
            directness="embedded",
            confidence=0.82,
            subject_id=subject_id,
            parent_subject_id=product_subject,
        )
        for name, fact, value in fields
        if value not in (None, "", [], {})
    ]
    out.extend(_variant_offer(bundle, artifact_id, path, obj, hint, subject_id, collector_id=collector_id))
    return out


def _looks_like_variant(obj: dict) -> bool:
    identity = _variant_identity_value(obj) is not None or _scalar_value(obj.get("sku")) not in (
        None,
        "",
        [],
        {},
    )
    option_count = len(_variant_options(obj))
    variant_specific_identity = any(_scalar_value(obj.get(key)) not in (None, "", [], {}) for key in ("variantId", "variant_id", "skuId", "sku_id"))
    commercial = any(
        _scalar_value(obj.get(key)) not in (None, "", [], {})
        for key in (
            "price",
            "currentPrice",
            "salePrice",
            "currency",
            "currencyCode",
            "availability",
            "available",
            "inStock",
            "isAvailable",
        )
    )
    type_name = str(obj.get("type") or obj.get("__typename") or "").lower()
    if any(token in type_name for token in VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS):
        return False
    typed = "variant" in type_name
    return (identity and (option_count > 0 or variant_specific_identity or (commercial and typed))) or (typed and option_count >= 2)


def _variant_fields(obj: dict) -> list[tuple[str, str, object]]:
    selected = bool(obj.get("selected") or obj.get("isSelected")) if "selected" in obj or "isSelected" in obj else None
    raw = [
        ("id", "variant.id", _variant_identity_value(obj)),
        ("sku", "variant.sku", obj.get("sku")),
        ("url", "variant.url", obj.get("url")),
        ("selected", "variant.selected", selected),
    ]
    raw.extend((name, f"variant.option.{axis}", value) for name, axis, value in _variant_options(obj))
    return [(name, fact, _scalar_value(value)) for name, fact, value in raw]


def _variant_offer(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    hint: EntityHint,
    variant_subject_id: str,
    *,
    collector_id: str,
) -> list[Evidence]:
    group = f"offer:{artifact_id}:{path}"
    rows = [
        ("price", "offer.price", _first(obj, "price", "currentPrice", "salePrice")),
        (
            "original_price",
            "offer.original_price",
            _first(obj, "originalPrice", "regularPrice", "listPrice", "compareAtPrice"),
        ),
        ("currency", "offer.currency", _first(obj, "currency", "currencyCode")),
        (
            "availability",
            "offer.availability",
            _availability_value(_first(obj, "availability", "available", "inStock", "isAvailable")),
        ),
        (
            "stock_quantity",
            "offer.stock_quantity",
            _first(obj, "stock_quantity", "stockQuantity", "inventory", "inventoryQuantity"),
        ),
    ]
    return [
        evidence(
            bundle,
            artifact_id,
            collector_id,
            fact,
            _scalar_value(value),
            SourceLocator(kind="script_path", value=f"{path}/{name}"),
            group_id=group,
            hint=hint,
            directness="embedded",
            confidence=0.82,
            parent_subject_id=variant_subject_id,
        )
        for name, fact, value in rows
        if _scalar_value(value) not in (None, "", [], {})
    ]


def _scalar_value(value):
    if isinstance(value, dict):
        for key in ("value", "text", "name", "amount", "currentPrice", "price"):
            if value.get(key) not in (None, "", [], {}):
                return _scalar_value(value.get(key))
        return ""
    if isinstance(value, list):
        return " ".join(str(_scalar_value(item)) for item in value if _scalar_value(item)).strip()
    return value


def _first(obj: dict, *keys: str):
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _variant_identity_value(obj: dict) -> str | None:
    for key in ("variantId", "variant_id", "skuId", "sku_id", "id"):
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            return str(value).strip()
    return None


def _availability_value(value: object) -> object:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    return value


def _variant_options(obj: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    direct_axes = {
        "size": "size",
        "color": "color",
        "colour": "color",
        "width": "width",
        "length": "length",
        "material": "material",
        "style": "style",
        "capacity": "capacity",
        "quantity": "quantity",
    }
    for key, axis in direct_axes.items():
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            rows.append((key, axis, value))

    for key in (
        "attributes",
        "variationValues",
        "variationAttributes",
        "selectedOptions",
        "options",
        "productOptions",
        "dimensions",
    ):
        rows.extend(_option_rows_from_value(key, obj.get(key)))
    return _dedupe_options(rows)


def _option_rows_from_value(prefix: str, value: object) -> list[tuple[str, str, object]]:
    if isinstance(value, dict):
        rows: list[tuple[str, str, object]] = []
        for raw_axis, raw_value in value.items():
            axis = _canonical_axis(raw_axis)
            option_value = _scalar_value(raw_value)
            if axis and option_value not in (None, "", [], {}):
                rows.append((f"{prefix}/{raw_axis}", axis, option_value))
        return rows
    if isinstance(value, list):
        rows = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            raw_axis = _first(
                item,
                "name",
                "label",
                "displayName",
                "attributeName",
                "optionName",
                "type",
            )
            axis = _canonical_axis(raw_axis)
            option_value = _first(
                item,
                "value",
                "displayValue",
                "optionValue",
                "selectedValue",
                "name",
                "label",
            )
            if axis and option_value not in (None, "", [], {}):
                rows.append((f"{prefix}/{index}", axis, _scalar_value(option_value)))
        return rows
    return []


def _canonical_axis(value: object) -> str | None:
    text = str(_scalar_value(value) or "").strip()
    if not text:
        return None
    normalized = "_".join(text.lower().replace("&", " ").replace("-", " ").split())
    axis = AXIS_NAME_ALIASES.get(normalized, normalized)
    if axis in {"colour"}:
        return "color"
    if axis in {
        "size",
        "color",
        "width",
        "length",
        "material",
        "style",
        "capacity",
        "quantity",
    }:
        return axis
    return None


def _dedupe_options(
    rows: list[tuple[str, str, object]],
) -> list[tuple[str, str, object]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, object]] = []
    for name, axis, value in rows:
        key = (axis, str(value).strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append((name, axis, value))
    return out
