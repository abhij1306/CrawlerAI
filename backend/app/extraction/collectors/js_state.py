from __future__ import annotations

from typing import Literal
from app.core.config.field_mappings import (
    ECOMMERCE_IMAGE_SOURCE_KEYS,
    ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS,
    ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES,
)
from app.core.config.extraction_rules import (
    ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS,
    VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS,
)
from app.core.config import variant_policy
from app.core.records.html_helpers import bounded_json_objects, embedded_state_payloads
from app.extraction.collectors._helpers import evidence, html_doc, json_objects
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.ids import stable_id


class JsStateCollector:
    collector_id = "js_state"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        out: list[Evidence] = []
        for artifact_id, root_path, data in _state_payloads(bundle, artifacts):
            objects = (
                json_objects(data)
                if not root_path
                else bounded_json_objects(
                    data,
                    max_depth=variant_policy.EMBEDDED_STATE_MAX_DEPTH,
                    max_nodes=variant_policy.EMBEDDED_STATE_MAX_NODES,
                    max_list_items=variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS,
                )
            )
            for path, obj in objects:
                if isinstance(obj, dict):
                    out.extend(
                        network_row(bundle, artifact_id, f"{root_path}{path}", obj)
                    )
        return tuple(out)


def _state_payloads(bundle: CaptureBundle, artifacts):
    for ref in bundle.artifacts:
        if ref.artifact_type == "js_state":
            yield ref.artifact_id, "", artifacts.read_json(ref)
    _, document = html_doc(bundle, artifacts)
    for root_path, data in embedded_state_payloads(
        document,
        selector=variant_policy.EMBEDDED_STATE_SCRIPT_SELECTOR,
        global_keys=variant_policy.EMBEDDED_STATE_GLOBAL_KEYS,
        max_scripts=variant_policy.EMBEDDED_STATE_MAX_SCRIPTS,
        max_script_chars=variant_policy.EMBEDDED_STATE_MAX_SCRIPT_CHARS,
    ):
        yield document.artifact_id, root_path, data


def network_row(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    *,
    collector_id: str = "js_state",
) -> list[Evidence]:
    out: list[Evidence] = []
    if _path_tokens(path) & ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS:
        return out
    if _looks_like_variant(obj, path=path):
        return _variant_row(bundle, artifact_id, path, obj, collector_id=collector_id)
    mapped_keys = tuple(
        key for key in ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES if key in obj
    )
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
            entity_type: Literal["offer", "asset", "product"] = (
                "offer"
                if fact.startswith("offer.")
                else "asset"
                if fact.startswith("asset.")
                else "product"
            )
            hint = EntityHint(
                entity_type=entity_type, sku=str(obj.get("sku") or "").strip() or None
            )
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
                    parent_subject_id=product_subject
                    if fact.startswith(("offer.", "asset."))
                    else None,
                )
            )
    return out


def _path_tokens(path: str) -> set[str]:
    normalized = str(path).replace("[", "/").replace("]", "/").replace(".", "/")
    return {token.casefold() for token in normalized.split("/") if token}


def _has_product_context(path: str, obj: dict) -> bool:
    keys = set(obj)
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = _path_tokens(path)
    product_keys = keys & ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
    complete_offer = "price" in keys and bool(keys & {"currency", "currencyCode"})
    return (
        "product" in type_name
        or bool(path_tokens & {"product", "products"})
        or len(product_keys) >= 2
        or (bool(product_keys & {"name", "productName", "title"}) and complete_offer)
    )


def _has_offer_context(path: str, obj: dict, *, product_context: bool) -> bool:
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = _path_tokens(path)
    return (
        product_context
        or "offer" in type_name
        or bool(path_tokens & ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS)
    )


def _source_values(key: str, value: object) -> tuple[object, ...]:
    if key in ECOMMERCE_IMAGE_SOURCE_KEYS and isinstance(value, list):
        return tuple(_scalar_value(item) for item in value)
    return (_scalar_value(value),)


def _variant_row(
    bundle: CaptureBundle, artifact_id: str, path: str, obj: dict, *, collector_id: str
) -> list[Evidence]:
    if not _looks_like_variant(obj, path=path):
        return []
    variant_id = _variant_identity_value(obj)
    sku = str(
        _scalar_value(_first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS)) or ""
    ).strip()
    hint = EntityHint(
        entity_type="variant",
        variant_id=variant_id,
        sku=sku or None,
        selected=bool(obj.get("selected") or obj.get("isSelected"))
        if "selected" in obj or "isSelected" in obj
        else None,
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
    out.extend(
        _variant_offer(
            bundle, artifact_id, path, obj, hint, subject_id, collector_id=collector_id
        )
    )
    return out


def _looks_like_variant(obj: dict, *, path: str = "") -> bool:
    sku = _scalar_value(_first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS))
    identity = _variant_identity_value(obj) is not None or sku not in (None, "", [], {})
    option_count = len(_variant_options(obj))
    variant_specific_identity = any(
        _scalar_value(obj.get(key)) not in (None, "", [], {})
        for key in ("variantId", "variant_id", "skuId", "sku_id")
    )
    commercial = any(
        _scalar_value(_first(obj, *keys)) not in (None, "", [], {})
        for keys in (
            variant_policy.VARIANT_OFFER_PRICE_KEYS,
            variant_policy.VARIANT_OFFER_CURRENCY_KEYS,
            variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS,
            variant_policy.VARIANT_OFFER_STOCK_KEYS,
        )
    )
    type_name = str(obj.get("type") or obj.get("__typename") or "").lower()
    if any(
        token in type_name for token in VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS
    ):
        return False
    typed = "variant" in type_name
    variant_path = bool(
        _path_tokens(path) & variant_policy.VARIANT_STRUCTURED_PATH_TOKENS
    )
    return (
        identity
        and (
            option_count > 0
            or variant_specific_identity
            or (commercial and (typed or variant_path))
            or (variant_path and sku not in (None, "", [], {}))
        )
        or (typed and option_count >= 2)
    )


def _variant_fields(obj: dict) -> list[tuple[str, str, object]]:
    selected = (
        bool(obj.get("selected") or obj.get("isSelected"))
        if "selected" in obj or "isSelected" in obj
        else None
    )
    raw = [
        ("id", "variant.id", _variant_identity_value(obj)),
        ("sku", "variant.sku", _first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS)),
        ("url", "variant.url", obj.get("url")),
        ("selected", "variant.selected", selected),
    ]
    raw.extend(
        (name, f"variant.option.{axis}", value)
        for name, axis, value in _variant_options(obj)
    )
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
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_PRICE_KEYS) or "price",
            "offer.price",
            _first(obj, *variant_policy.VARIANT_OFFER_PRICE_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_ORIGINAL_PRICE_KEYS)
            or "original_price",
            "offer.original_price",
            _first(obj, *variant_policy.VARIANT_OFFER_ORIGINAL_PRICE_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_CURRENCY_KEYS) or "currency",
            "offer.currency",
            _first(obj, *variant_policy.VARIANT_OFFER_CURRENCY_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS)
            or "availability",
            "offer.availability",
            _first(obj, *variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_STOCK_KEYS)
            or "stock_quantity",
            "offer.stock_quantity",
            _first(obj, *variant_policy.VARIANT_OFFER_STOCK_KEYS),
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
        for key in variant_policy.VARIANT_SCALAR_VALUE_KEYS:
            if value.get(key) not in (None, "", [], {}):
                return _scalar_value(value.get(key))
        return ""
    if isinstance(value, list):
        return " ".join(
            str(_scalar_value(item)) for item in value if _scalar_value(item)
        ).strip()
    return value


def _first(obj: dict, *keys: str, depth: int = 0):
    if depth >= variant_policy.EMBEDDED_STATE_MAX_DEPTH:
        return None
    for key in keys:
        if (value := obj.get(key)) not in (None, "", [], {}):
            return value
    for source in obj.values():
        if isinstance(source, dict) and (
            value := _first(source, *keys, depth=depth + 1)
        ) not in (
            None,
            "",
            [],
            {},
        ):
            return value
    return None


def _first_key(obj: dict, *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            return _first_key(value, *keys) or key
        return key
    for source in obj.values():
        if not isinstance(source, dict):
            continue
        nested_key = _first_key(source, *keys)
        if nested_key:
            return nested_key
    return None


def _variant_identity_value(obj: dict) -> str | None:
    for key in ("variantId", "variant_id", "skuId", "sku_id", "id"):
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            return str(value).strip()
    return None


def _variant_options(obj: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    for key, axis in variant_policy.VARIANT_DIRECT_OPTION_FIELD_AXES.items():
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            rows.append((key, axis, value))

    for key in variant_policy.VARIANT_OPTION_CONTAINER_KEYS:
        rows.extend(_option_rows_from_value(key, obj.get(key)))
    if "variationType" in obj:
        rows.extend(_option_rows_from_value("variation", [obj]))
    return _dedupe_options(rows)


def _option_rows_from_value(
    prefix: str, value: object
) -> list[tuple[str, str, object]]:
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
            raw_axis = _first(item, *variant_policy.VARIANT_OPTION_AXIS_KEYS)
            axis = _canonical_axis(raw_axis)
            option_value = _first(item, *variant_policy.VARIANT_OPTION_VALUE_KEYS)
            if axis and option_value not in (None, "", [], {}):
                rows.append((f"{prefix}/{index}", axis, _scalar_value(option_value)))
        return rows
    return []


def _canonical_axis(value: object) -> str | None:
    text = str(_scalar_value(value) or "").strip()
    if not text:
        return None
    normalized = "_".join(text.lower().replace("&", " ").replace("-", " ").split())
    axis = variant_policy.AXIS_NAME_ALIASES.get(normalized, normalized)
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
