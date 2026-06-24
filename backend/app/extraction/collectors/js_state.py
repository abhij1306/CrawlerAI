from __future__ import annotations

import re
from typing import Literal
from app.core.config.field_mappings import (
    ECOMMERCE_IMAGE_SOURCE_KEYS,
    ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS,
    ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS,
    ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES,
)
from app.core.config.extraction_rules import (
    ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS,
    ECOMMERCE_EMBEDDED_STATE_NOISE_SCOPE_TOKENS,
    VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS,
)
from app.core.config import variant_policy
from app.core.records.html_helpers import bounded_json_objects, embedded_state_payloads
from app.core.records.url_identity import (
    detail_identity_codes_from_url,
    detail_title_from_url,
    detail_urls_conflict,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce import (
    sanitize_option_scalar,
    variant_option_value_is_opaque_numeric,
)
from app.core.shared.url_utils import extract_urls
from app.extraction.collectors._helpers import evidence, html_doc, json_objects
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.ids import stable_id


class JsStateCollector:
    collector_id = "js_state"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        out: list[Evidence] = []
        for artifact_id, root_path, data in _state_payloads(bundle, artifacts):
            objects = tuple(
                json_objects(data)
                if not root_path
                else bounded_json_objects(
                    data,
                    max_depth=variant_policy.EMBEDDED_STATE_MAX_DEPTH,
                    max_nodes=variant_policy.EMBEDDED_STATE_MAX_NODES,
                    max_list_items=variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS,
                )
            )
            axis_hints = _variant_axis_hints(objects)
            for path, obj in objects:
                if isinstance(obj, dict):
                    enriched = _with_parent_variant_axes(obj, axis_hints.get(path, ()))
                    out.extend(
                        network_row(
                            bundle,
                            artifact_id,
                            f"{root_path}{path}",
                            enriched,
                        )
                    )
        return tuple(out)


def _state_payloads(bundle: CaptureBundle, artifacts):
    for ref in bundle.artifacts:
        if ref.artifact_type == "js_state":
            yield ref.artifact_id, "", artifacts.read_json(ref)
    _, document = html_doc(bundle, artifacts)
    payloads = tuple(
        embedded_state_payloads(
            document,
            selector=variant_policy.EMBEDDED_STATE_SCRIPT_SELECTOR,
            global_keys=variant_policy.EMBEDDED_STATE_GLOBAL_KEYS,
            max_scripts=variant_policy.EMBEDDED_STATE_MAX_SCRIPTS,
            max_script_chars=variant_policy.EMBEDDED_STATE_MAX_SCRIPT_CHARS,
            exclude_node=_embedded_state_node_is_noise,
        )
    )
    meta_segment = f"/{variant_policy.EMBEDDED_STATE_PRODUCT_META_KEY}/"
    richer_variant_ids = {
        variant_id
        for root_path, data in payloads
        if meta_segment not in root_path
        for variant_id in _payload_variant_ids(data)
    }
    for root_path, data in payloads:
        if _is_unrelated_meta_payload(
            root_path,
            data,
            richer_variant_ids=richer_variant_ids,
        ):
            continue
        yield document.artifact_id, root_path, data


def _embedded_state_node_is_noise(node: object) -> bool:
    scoped_nodes = (node, *getattr(node, "ancestors")())
    for scoped_node in scoped_nodes:
        attribute = getattr(scoped_node, "attribute")
        scope = " ".join(
            str(attribute(name) or "")
            for name in (
                "class",
                "id",
                "data-section-type",
                "data-testid",
                "aria-label",
            )
        )
        normalized = "".join(char for char in scope.casefold() if char.isalnum())
        if any(
            token in normalized
            for token in ECOMMERCE_EMBEDDED_STATE_NOISE_SCOPE_TOKENS
        ):
            return True
    return False


def _is_unrelated_meta_payload(
    root_path: str,
    data: object,
    *,
    richer_variant_ids: set[str],
) -> bool:
    meta_segment = f"/{variant_policy.EMBEDDED_STATE_PRODUCT_META_KEY}/"
    if meta_segment not in root_path:
        return False
    if not isinstance(data, dict):
        return True
    product = data.get(variant_policy.EMBEDDED_STATE_PRODUCT_META_CONTAINER_KEY)
    if not (
        isinstance(product, dict)
        and isinstance(
            product.get(variant_policy.EMBEDDED_STATE_PRODUCT_META_VARIANTS_KEY), list
        )
    ):
        return True
    compact_ids = set(_payload_variant_ids(product))
    return bool(compact_ids and compact_ids <= richer_variant_ids)


def _payload_variant_ids(data: object) -> tuple[str, ...]:
    rows = bounded_json_objects(
        data,
        max_depth=variant_policy.EMBEDDED_STATE_MAX_DEPTH,
        max_nodes=variant_policy.EMBEDDED_STATE_MAX_NODES,
        max_list_items=variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS,
    )
    return tuple(
        variant_id
        for path, obj in rows
        if isinstance(obj, dict)
        and _path_tokens(path) & variant_policy.VARIANT_STRUCTURED_PATH_TOKENS
        for variant_id in [_variant_identity_value(obj)]
        if variant_id
    )


def _variant_axis_hints(
    objects: tuple[tuple[str, object], ...],
) -> dict[str, tuple[str, ...]]:
    hints: dict[str, tuple[str, ...]] = {}
    for parent_path, parent in objects:
        if not isinstance(parent, dict):
            continue
        axes = _parent_option_axes(parent)
        if not axes:
            continue
        for child_key in variant_policy.VARIANT_PARENT_OPTION_CHILD_KEYS:
            children = parent.get(child_key)
            if not isinstance(children, list):
                continue
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    hints[f"{parent_path}/{child_key}/{index}"] = axes
    return hints


def _parent_option_axes(obj: dict) -> tuple[str, ...]:
    raw_options = obj.get("options")
    if not isinstance(raw_options, list) or not raw_options:
        return ()
    axes: list[str] = []
    for raw_option in raw_options:
        raw_axis = (
            _first(raw_option, *variant_policy.VARIANT_OPTION_AXIS_KEYS)
            if isinstance(raw_option, dict)
            else raw_option
        )
        axis = _canonical_axis(raw_axis)
        if axis is None:
            return ()
        axes.append(axis)
    return tuple(axes)


def _with_parent_variant_axes(obj: dict, axes: tuple[str, ...]) -> dict:
    if not axes or obj.get("selectedOptions"):
        return obj
    values = [
        _scalar_value(obj.get(key))
        for key in variant_policy.VARIANT_POSITIONAL_OPTION_KEYS
    ]
    if not any(value not in (None, "", [], {}) for value in values):
        raw_options = obj.get("options")
        values = list(raw_options) if isinstance(raw_options, list) else []
    selected = [
        {"name": axis, "value": value}
        for axis, value in zip(axes, values, strict=False)
        if value not in (None, "", [], {}) and not isinstance(value, dict)
    ]
    return {**obj, "selectedOptions": selected} if selected else obj


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
    if _path_product_identity_conflicts(bundle.final_url, path):
        return out
    if _has_only_opaque_numeric_options(obj):
        return out
    if _looks_like_variant(obj, path=path):
        if _variant_url_conflicts(bundle.final_url, obj) or _variant_title_conflicts(
            bundle.final_url, obj
        ):
            return out
        return _variant_row(bundle, artifact_id, path, obj, collector_id=collector_id)
    mapped_keys = tuple(
        key for key in ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES if key in obj
    )
    if not mapped_keys:
        return out
    if _product_url_conflicts(bundle.final_url, obj):
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
            product_identity = next(
                (
                    str(obj.get(identity_key) or "").strip()
                    for identity_key in ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS
                    if str(obj.get(identity_key) or "").strip()
                ),
                None,
            )
            hint = EntityHint(
                entity_type=entity_type,
                product_id=product_identity if entity_type == "product" else None,
                sku=str(obj.get("sku") or "").strip() or None,
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


def _variant_url_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _url_value(obj)
    return bool(candidate and detail_urls_conflict(page_url, candidate))


def _variant_title_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _scalar_value(
        _first(obj, "productName", "product_name", "productTitle", "product_title")
    )
    if not isinstance(candidate, str) or not candidate.strip():
        return False
    page_tokens = set(semantic_identity_tokens(detail_title_from_url(page_url)))
    candidate_tokens = set(semantic_identity_tokens(candidate))
    if len(page_tokens) < 2 or len(candidate_tokens) < 2:
        return False
    overlap = len(page_tokens & candidate_tokens)
    return overlap == 0


def _product_url_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _url_value(obj)
    return bool(candidate and detail_urls_conflict(page_url, candidate))


def _url_value(obj: dict) -> str:
    candidate = _first(obj, *variant_policy.VARIANT_URL_VALUE_KEYS)
    if isinstance(candidate, dict):
        candidate = _first(candidate, *variant_policy.VARIANT_NESTED_URL_VALUE_KEYS)
    scalar = _scalar_value(candidate)
    return scalar.strip() if isinstance(scalar, str) else ""


def _path_product_identity_conflicts(page_url: str, path: str) -> bool:
    parent_codes = set(detail_identity_codes_from_url(page_url))
    if not parent_codes:
        return False
    parts = tuple(
        part
        for part in str(path).replace("[", "/").replace("]", "/").split("/")
        if part
    )
    for index, part in enumerate(parts[:-1]):
        if part.casefold() not in variant_policy.VARIANT_PRODUCT_MAP_PATH_TOKENS:
            continue
        candidate = parts[index + 1]
        normalized = "".join(char for char in candidate if char.isalnum()).upper()
        if (
            len(normalized) < variant_policy.VARIANT_PRODUCT_MAP_KEY_MIN_LENGTH
            or not any(char.isalpha() for char in normalized)
            or not any(char.isdigit() for char in normalized)
        ):
            continue
        if not any(
            left == normalized or left in normalized or normalized in left
            for left in parent_codes
        ):
            return True
    return False


def _has_product_context(path: str, obj: dict) -> bool:
    keys = set(obj)
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = _path_tokens(path)
    path_parts = tuple(token for token in str(path).replace(".", "/").split("/") if token)
    direct_product_path = bool(path_parts and path_parts[-1].casefold() in {"product", "products"})
    product_keys = keys & ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
    complete_offer = "price" in keys and bool(keys & {"currency", "currencyCode"})
    if (
        "config" in path_tokens
        and not direct_product_path
        and not complete_offer
        and not bool(keys & {"sku", "url", "productUrl", "product_url"})
    ):
        return False
    return (
        "product" in type_name
        or direct_product_path
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
    if key in ECOMMERCE_IMAGE_SOURCE_KEYS:
        return tuple(extract_urls(value, ""))
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
    if _has_variant_children(obj):
        return False
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
            (
                option_count > 0
                and (
                    typed
                    or variant_path
                    or variant_specific_identity
                    or commercial
                    or sku not in (None, "", [], {})
                )
            )
            or variant_specific_identity
            or (commercial and (typed or variant_path))
            or (variant_path and sku not in (None, "", [], {}))
        )
        or (typed and option_count >= 2)
    )


def _has_variant_children(obj: dict) -> bool:
    return any(
        isinstance(obj.get(key), list) and bool(obj.get(key))
        for key in variant_policy.VARIANT_CHILD_COLLECTION_KEYS
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
        (
            "url",
            "variant.url",
            _first(obj, *variant_policy.VARIANT_URL_VALUE_KEYS),
        ),
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
        *(
            (key, "offer.price", obj.get(key))
            for key in variant_policy.VARIANT_OFFER_DISPLAY_PRICE_KEYS
            if obj.get(key) not in (None, "", [], {})
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
    cleaned: list[tuple[str, str, object]] = []
    for name, axis, value in _raw_variant_options(obj):
        option_value = _clean_variant_option_value(axis, value)
        if option_value is not None:
            cleaned.append((name, axis, option_value))
    return _dedupe_options(cleaned)


def _raw_variant_options(obj: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    for key, axis in variant_policy.VARIANT_DIRECT_OPTION_FIELD_AXES.items():
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            rows.append((key, axis, value))
    for key in variant_policy.VARIANT_OPTION_CONTAINER_KEYS:
        rows.extend(_option_rows_from_value(key, obj.get(key)))
    if not any(axis == "size" for _name, axis, _value in rows):
        rows.extend(_merch_sku_size_rows(obj))
    if not any(axis == "size" for _name, axis, _value in rows):
        rows.extend(_positional_numeric_size_rows(obj))
    if not rows:
        rows.extend(_shopify_fallback_rows(obj))
    if "variationType" in obj:
        rows.extend(_option_rows_from_value("variation", [obj]))
    return rows


def _merch_sku_size_rows(obj: dict) -> list[tuple[str, str, object]]:
    if not any(
        _scalar_value(obj.get(key)) not in (None, "", [], {})
        for key in variant_policy.VARIANT_MERCH_SKU_ID_KEYS
    ):
        return []
    for key in variant_policy.VARIANT_MERCH_SKU_SIZE_KEYS:
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            return [(key, "size", value)]
    return []


def _shopify_fallback_rows(obj: dict) -> list[tuple[str, str, object]]:
    for key in variant_policy.VARIANT_SHOPIFY_SIZE_KEYS:
        value = _scalar_value(obj.get(key))
        text = str(value or "").strip()
        if text:
            axis = (
                "size"
                if re.fullmatch(
                    variant_policy.VARIANT_SIZE_LIKE_PATTERN,
                    text,
                    flags=re.IGNORECASE,
                )
                else "style"
            )
            return [(key, axis, value)]
    return []


def _positional_numeric_size_rows(obj: dict) -> list[tuple[str, str, object]]:
    for key in variant_policy.VARIANT_POSITIONAL_OPTION_KEYS:
        value = _scalar_value(obj.get(key))
        text = str(value or "").strip()
        if not text or text.count(".") > 1 or not text.replace(".", "", 1).isdigit():
            continue
        numeric = float(text)
        if (
            variant_policy.VARIANT_POSITIONAL_NUMERIC_SIZE_MIN
            <= numeric
            <= variant_policy.VARIANT_POSITIONAL_NUMERIC_SIZE_MAX
        ):
            return [(key, "size", value)]
    return []


def _clean_variant_option_value(axis: str, value: object) -> str | None:
    return sanitize_option_scalar(axis, _scalar_value(value))


def _has_only_opaque_numeric_options(obj: dict) -> bool:
    rows = [
        (axis, str(_scalar_value(value) or "").strip())
        for _name, axis, value in _raw_variant_options(obj)
        if str(_scalar_value(value) or "").strip()
    ]
    return len(rows) >= 2 and all(
        variant_option_value_is_opaque_numeric(axis, value)
        for axis, value in rows
    )


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
    if axis in variant_policy.PUBLIC_VARIANT_AXIS_FIELDS:
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
