from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.core.config.field_mappings import (
    ECOMMERCE_JSONLD_OFFER_FACT_TYPES,
    ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES,
    ECOMMERCE_JSONLD_VARIANT_FACT_TYPES,
    OFFER_CURRENCY_FACT_TYPE,
    OFFER_ORIGINAL_PRICE_FACT_TYPE,
    OFFER_PRICE_FACT_TYPE,
)
from app.core.config.extraction_price_rules import (
    DETAIL_JSONLD_CURRENCY_FIELDS,
    DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS,
)
from app.core.config.extraction_rules import (
    DETAIL_JSONLD_STRUCTURED_ATTRIBUTES,
    VARIANT_JSONLD_NAME_OPTION_SEPARATOR,
    VARIANT_SHADE_URL_QUERY_KEYS,
)
from app.core.config.variant_policy import canonical_variant_axis
from app.core.records.product_identity import target_offer_group_id
from app.core.records.normalizers import normalize_structured_offer_values
from app.extraction.collectors.jsonld_attributes import (
    product_attribute_evidence,
    product_fact_evidence,
    product_image_evidence,
)
from app.extraction.collectors._helpers import (
    evidence,
    html_doc,
    json_objects,
    loads_jsonish,
    text_value,
)
from app.extraction.collectors.js_state import (
    root_admits_path,
    select_product_roots,
)
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.core.records.url_identity import detail_url_resource_identity
from app.core.shared.ids import stable_id


_IS_VARIANT_OF_KEY = "is" + "VariantOf"
_JSONLD_ID_KEY = "@" + "id"


class JsonLdCollector:
    collector_id = "jsonld"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        payloads = _jsonld_payloads(doc)
        variant_subject_ids = _known_variant_subject_ids(
            bundle,
            (item for _artifact_id, objects in payloads for item in objects),
        )
        for artifact_id, objects in payloads:
            selection = select_product_roots(objects, bundle.final_url)
            for path, obj in objects:
                if not root_admits_path(selection, path) and not _is_standalone_variant(
                    obj
                ):
                    continue
                if not isinstance(obj, dict) or not _is_product(obj):
                    continue
                if "/hasVariant/" in path:
                    continue
                if _is_standalone_variant(obj):
                    out.extend(
                        _standalone_variant(
                            bundle,
                            artifact_id,
                            obj,
                            path,
                            variant_subject_ids,
                        )
                    )
                    continue
                out.extend(
                    _product(
                        bundle,
                        artifact_id,
                        obj,
                        path,
                        variant_subject_ids,
                    )
                )
        return tuple(out)


def _jsonld_payloads(doc) -> list[tuple[str, tuple[tuple[str, Any], ...]]]:
    payloads: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
    for index, tag in enumerate(doc.css('script[type*="ld+json"]')):
        data = loads_jsonish(tag.text())
        payloads.append((f"jsonld:{index}", tuple(json_objects(data))))
    attr_index = 0
    for attr_name in DETAIL_JSONLD_STRUCTURED_ATTRIBUTES:
        for node in doc.safe_css(f"[{attr_name}]"):
            raw = node.attribute(attr_name)
            if not raw:
                continue
            data = loads_jsonish(raw)
            objects = tuple(json_objects(data))
            if not objects:
                continue
            payloads.append((f"jsonld:attr:{attr_index}", objects))
            attr_index += 1
    return payloads


def _is_product(obj: dict[str, Any]) -> bool:
    types = obj.get("@type") or obj.get("type")
    values = types if isinstance(types, list) else [types]
    return any(str(item).lower() in {"product", "productgroup"} for item in values)


def _is_standalone_variant(obj: dict[str, Any]) -> bool:
    return isinstance(obj.get(_IS_VARIANT_OF_KEY), (dict, str))


def _standalone_variant(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    variant_subject_ids: frozenset[str],
) -> list[Evidence]:
    parent = row.get(_IS_VARIANT_OF_KEY)
    parent_url = (
        text_value(parent.get(_JSONLD_ID_KEY) or parent.get("url"))
        if isinstance(parent, dict)
        else text_value(parent)
    )
    product_subject = stable_id(
        "subject",
        bundle.bundle_id,
        "product",
        parent_url or bundle.final_url,
    )
    source_subject_ids = _source_subject_ids(bundle, row)
    out = [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES[key],
            text_value(row.get(key)),
            SourceLocator(kind="json_pointer", value=f"{path}/{key}"),
            hint=EntityHint(entity_type="product", url=parent_url or None),
            directness="embedded",
            confidence=0.9,
            subject_id=product_subject,
            subject_scope="product",
            source_subject_ids=source_subject_ids,
        )
        for key in ("brand", "manufacturer", "manufacturerName", "designer")
        if text_value(row.get(key))
    ]
    out.extend(
        _variant(
            bundle,
            artifact_id,
            row,
            path,
            product_subject,
            variant_subject_ids=variant_subject_ids,
        )
    )
    return out


def _product(
    bundle: CaptureBundle,
    artifact_id: str,
    obj: dict[str, Any],
    path: str,
    variant_subject_ids: frozenset[str],
) -> list[Evidence]:
    explicit_node_id = text_value(obj.get(_JSONLD_ID_KEY))
    node_path_identity = explicit_node_id or f"{artifact_id}:{path}"
    product_subject_identity = (
        explicit_node_id
        or text_value(obj.get("sku"))
        or text_value(obj.get("productGroupID"))
        or text_value(obj.get("productID"))
        or text_value(obj.get("productId"))
        or node_path_identity
    )
    source_subject_ids = _source_subject_ids(bundle, obj)
    hint = EntityHint(
        entity_type="product",
        product_id=text_value(obj.get("productGroupID")) or None,
        sku=text_value(obj.get("sku")) or None,
        url=text_value(obj.get("url")) or None,
    )
    product_subject = stable_id(
        "subject", bundle.bundle_id, "product", product_subject_identity
    )
    out = product_fact_evidence(
        bundle,
        artifact_id,
        obj,
        path,
        hint=hint,
        product_subject=product_subject,
        source_subject_ids=source_subject_ids,
        explicit_node_id=explicit_node_id,
    )
    out.extend(
        product_attribute_evidence(
            bundle,
            artifact_id,
            obj,
            path,
            hint=hint,
            product_subject=product_subject,
            source_subject_ids=source_subject_ids,
        )
    )
    out.extend(
        product_image_evidence(
            bundle, artifact_id, obj, path, product_subject=product_subject
        )
    )
    out.extend(
        _offers(
            bundle,
            artifact_id,
            obj.get("offers"),
            path,
            hint,
            product_subject,
            variant_subject_ids=variant_subject_ids,
        )
    )
    out.extend(
        _variants(
            bundle,
            artifact_id,
            obj.get("hasVariant"),
            path,
            text_value(obj.get("brand")),
            product_subject,
            variant_subject_ids,
            declared_axes=_declared_variant_axes(obj.get("variesBy")),
        )
    )
    return out


def _offers(
    bundle: CaptureBundle,
    artifact_id: str,
    offers: Any,
    path: str,
    hint: EntityHint,
    parent_subject_id: str | None = None,
    parent_scope: str = "product",
    variant_subject_ids: frozenset[str] = frozenset(),
) -> list[Evidence]:
    rows = offers if isinstance(offers, list) else [offers]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        offer_path = f"{path}/offers/{index}"
        offer_identity = _jsonld_identity(row) or offer_path
        offer_url = text_value(row.get("url"))
        target_group = target_offer_group_id(
            bundle.final_url, offer_url or hint.url or ""
        )
        source_subject_ids = _source_subject_ids(bundle, row, include_sku=True)
        child_parent_subject_id = parent_subject_id
        child_parent_scope = parent_scope
        item_offered = _item_offered_subject(bundle, row)
        if item_offered in variant_subject_ids:
            child_parent_subject_id = item_offered
            child_parent_scope = "variant"
        group = target_group if child_parent_scope == "product" else ""
        group = group or (
            f"offer:{artifact_id}:{child_parent_subject_id}:{offer_identity}"
            if child_parent_scope == "variant" and child_parent_subject_id
            else f"offer:{artifact_id}:{offer_identity}"
        )
        row_hint = hint.model_copy(
            update={
                "entity_type": "offer",
                "sku": text_value(row.get("sku")) or None,
                "url": offer_url or hint.url,
            }
        )
        out.extend(
            _offer_facts(
                bundle,
                artifact_id,
                row,
                offer_path,
                group,
                group,
                row_hint,
                child_parent_subject_id,
                child_parent_scope,
                source_subject_ids,
            )
        )
        for spec_key in DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS:
            out.extend(
                _price_specification_facts(
                    bundle,
                    artifact_id,
                    row.get(spec_key),
                    f"{offer_path}/{spec_key}",
                    group,
                    group,
                    row_hint,
                    child_parent_subject_id,
                    child_parent_scope,
                    source_subject_ids,
                )
            )
        out.extend(
            _offers(
                bundle,
                artifact_id,
                row.get("offers"),
                offer_path,
                hint,
                child_parent_subject_id,
                child_parent_scope,
                variant_subject_ids,
            )
        )
    return out


def _offer_facts(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    offer_path: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
) -> list[Evidence]:
    row = normalize_structured_offer_values(row)
    out: list[Evidence] = []
    for key, fact in ECOMMERCE_JSONLD_OFFER_FACT_TYPES.items():
        value = text_value(row.get(key))
        if value:
            out.append(
                _offer_evidence(
                    bundle,
                    artifact_id,
                    fact,
                    value,
                    f"{offer_path}/{key}",
                    group,
                    subject_id,
                    hint,
                    parent_subject_id,
                    parent_scope,
                    source_subject_ids,
                )
            )
    return out


def _price_specification_facts(
    bundle: CaptureBundle,
    artifact_id: str,
    specs: Any,
    path: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
) -> list[Evidence]:
    rows = specs if isinstance(specs, list) else [specs]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        spec_path = f"{path}/{index}"
        for key in DETAIL_JSONLD_PRICE_FIELDS:
            value = text_value(row.get(key))
            if value:
                out.append(
                    _offer_evidence(
                        bundle,
                        artifact_id,
                        OFFER_PRICE_FACT_TYPE,
                        value,
                        f"{spec_path}/{key}",
                        group,
                        subject_id,
                        hint,
                        parent_subject_id,
                        parent_scope,
                        source_subject_ids,
                    )
                )
        for key in DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS:
            value = text_value(row.get(key))
            if value:
                out.append(
                    _offer_evidence(
                        bundle,
                        artifact_id,
                        OFFER_ORIGINAL_PRICE_FACT_TYPE,
                        value,
                        f"{spec_path}/{key}",
                        group,
                        subject_id,
                        hint,
                        parent_subject_id,
                        parent_scope,
                        source_subject_ids,
                    )
                )
        for key in DETAIL_JSONLD_CURRENCY_FIELDS:
            value = text_value(row.get(key))
            if value:
                out.append(
                    _offer_evidence(
                        bundle,
                        artifact_id,
                        OFFER_CURRENCY_FACT_TYPE,
                        value,
                        f"{spec_path}/{key}",
                        group,
                        subject_id,
                        hint,
                        parent_subject_id,
                        parent_scope,
                        source_subject_ids,
                    )
                )
    return out


def _offer_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    fact: str,
    value: str,
    locator: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...] = (),
) -> Evidence:
    return evidence(
        bundle,
        artifact_id,
        "jsonld",
        fact,
        value,
        SourceLocator(kind="json_pointer", value=locator),
        group_id=group,
        hint=hint,
        directness="embedded",
        confidence=0.9,
        subject_id=subject_id,
        subject_scope="offer",
        parent_subject_id=parent_subject_id,
        parent_scope=parent_scope,
        source_subject_ids=source_subject_ids,
    )


def _variants(
    bundle: CaptureBundle,
    artifact_id: str,
    variants: Any,
    path: str,
    product_brand: str,
    product_subject: str,
    variant_subject_ids: frozenset[str],
    *,
    declared_axes: tuple[str, ...] = (),
) -> list[Evidence]:
    rows = variants if isinstance(variants, list) else [variants]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            out.extend(
                _variant(
                    bundle,
                    artifact_id,
                    row,
                    f"{path}/hasVariant/{index}",
                    product_subject,
                    product_brand=product_brand,
                    variant_subject_ids=variant_subject_ids,
                    declared_axes=declared_axes,
                )
            )
    return out


def _variant_fact_value(
    key: str,
    row: dict[str, Any],
    *,
    product_brand: str,
    guarded_offer_url: str | None,
    declared_axes: tuple[str, ...],
) -> str | None:
    if key == "color":
        return _variant_color(row, product_brand=product_brand)
    if key == "size":
        return _variant_size(row, infer_from_name="size" in declared_axes)
    return text_value(row.get(key)) or (guarded_offer_url if key == "url" else "")


def _variant_fact_locator(
    key: str,
    value: str,
    row: dict[str, Any],
    path: str,
    guarded_offer_url: str | None,
) -> str:
    if key == "url" and value == guarded_offer_url and not text_value(row.get(key)):
        return f"{path}/offers/url"
    return f"{path}/{key}"


def _variant_shared_kwargs(
    *,
    group: str,
    hint: EntityHint,
    product_subject: str,
    source_subject_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "group_id": group,
        "hint": hint,
        "directness": "embedded",
        "confidence": 0.88,
        "subject_id": group,
        "subject_scope": "variant",
        "parent_subject_id": product_subject,
        "parent_scope": "product",
        "relation_type": "product_variant",
        "source_subject_ids": source_subject_ids,
    }


def _variant_id_row(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    *,
    hint: EntityHint,
    shared: dict[str, Any],
) -> list[Evidence]:
    if not hint.variant_id or any(
        text_value(row.get(key)) for key in ("sku", "gtin", "url")
    ):
        return []
    return [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            "variant.id",
            hint.variant_id,
            SourceLocator(
                kind="json_pointer",
                value=(
                    f"{path}/{_JSONLD_ID_KEY}"
                    if text_value(row.get(_JSONLD_ID_KEY))
                    else f"{path}/offers/url"
                ),
            ),
            **shared,
        )
    ]


def _variant_fact_rows(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    *,
    product_brand: str,
    guarded_offer_url: str | None,
    declared_axes: tuple[str, ...],
    shared: dict[str, Any],
) -> tuple[list[Evidence], set[str]]:
    out: list[Evidence] = []
    emitted_axes: set[str] = set()
    for key, fact in ECOMMERCE_JSONLD_VARIANT_FACT_TYPES.items():
        value = _variant_fact_value(
            key,
            row,
            product_brand=product_brand,
            guarded_offer_url=guarded_offer_url,
            declared_axes=declared_axes,
        )
        if not value:
            continue
        if fact.startswith("variant.option."):
            emitted_axes.add(fact.rsplit(".", 1)[-1])
        out.append(
            evidence(
                bundle,
                artifact_id,
                "jsonld",
                fact,
                value,
                SourceLocator(
                    kind="json_pointer",
                    value=_variant_fact_locator(
                        key, value, row, path, guarded_offer_url
                    ),
                ),
                **shared,
            )
        )
    return out, emitted_axes


def _variant_option_rows(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    *,
    declared_axes: tuple[str, ...],
    emitted_axes: set[str],
    shared: dict[str, Any],
) -> list[Evidence]:
    out: list[Evidence] = []
    for locator_key, axis, value in _jsonld_variant_options(row, declared_axes):
        if axis in emitted_axes:
            continue
        emitted_axes.add(axis)
        out.append(
            evidence(
                bundle,
                artifact_id,
                "jsonld",
                f"variant.option.{axis}",
                value,
                SourceLocator(kind="json_pointer", value=f"{path}/{locator_key}"),
                **shared,
            )
        )
    return out


def _variant_image_rows(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    *,
    sku: str,
    subject_id: str,
) -> list[Evidence]:
    raw_image = row.get("image")
    images = raw_image if isinstance(raw_image, list) else [raw_image]
    return [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            "asset.image_url",
            url,
            SourceLocator(kind="json_pointer", value=f"{path}/image/{index}"),
            hint=EntityHint(entity_type="asset", sku=sku or None),
            directness="embedded",
            confidence=0.85,
            parent_subject_id=subject_id,
            parent_scope="variant",
            relation_type="variant_asset",
        )
        for index, url in enumerate(
            text_value(item) for item in images if text_value(item)
        )
    ]


def _variant(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    product_subject: str,
    *,
    product_brand: str = "",
    variant_subject_ids: frozenset[str] = frozenset(),
    declared_axes: tuple[str, ...] = (),
) -> list[Evidence]:
    sku = text_value(row.get("sku"))
    variant_url = text_value(row.get("url"))
    url_identity = detail_url_resource_identity(variant_url)
    target_identity = detail_url_resource_identity(bundle.final_url)
    guarded_offer_url = _guarded_standalone_offer_url(bundle, row)
    variant_identity = _jsonld_identity(row) or guarded_offer_url or path
    hint = EntityHint(
        entity_type="variant",
        product_id=text_value(row.get("productGroupID")) or None,
        variant_id=text_value(row.get(_JSONLD_ID_KEY)) or guarded_offer_url or None,
        sku=sku or None,
        url=variant_url or guarded_offer_url or None,
        selected=bool(url_identity and url_identity == target_identity),
    )
    group = f"variant:{artifact_id}:{variant_identity}"
    shared = _variant_shared_kwargs(
        group=group,
        hint=hint,
        product_subject=product_subject,
        source_subject_ids=_source_subject_ids(bundle, row, include_sku=True),
    )
    out = _variant_id_row(bundle, artifact_id, row, path, hint=hint, shared=shared)
    fact_rows, emitted_axes = _variant_fact_rows(
        bundle,
        artifact_id,
        row,
        path,
        product_brand=product_brand,
        guarded_offer_url=guarded_offer_url,
        declared_axes=declared_axes,
        shared=shared,
    )
    out.extend(fact_rows)
    out.extend(
        _variant_option_rows(
            bundle,
            artifact_id,
            row,
            path,
            declared_axes=declared_axes,
            emitted_axes=emitted_axes,
            shared=shared,
        )
    )
    out.extend(
        _variant_image_rows(bundle, artifact_id, row, path, sku=sku, subject_id=group)
    )
    out.extend(
        _offers(
            bundle,
            artifact_id,
            row.get("offers"),
            path,
            hint,
            group,
            "variant",
            variant_subject_ids,
        )
    )
    return out


def _guarded_standalone_offer_url(
    bundle: CaptureBundle, row: dict[str, Any]
) -> str | None:
    identified = any(text_value(row.get(key)) for key in ("sku", "gtin", "url"))
    if not _is_standalone_variant(row) or identified:
        return None
    if not (target_identity := detail_url_resource_identity(bundle.final_url)):
        return None
    offers = row.get("offers")
    offer_rows = offers if isinstance(offers, list) else [offers]
    offer_urls = {
        text_value(offer.get("url")) for offer in offer_rows if isinstance(offer, dict)
    }
    matches = [
        url
        for url in offer_urls
        if url and detail_url_resource_identity(url) == target_identity
    ]
    return matches[0] if len(matches) == 1 else None


def _declared_variant_axes(value: Any) -> tuple[str, ...]:
    rows = value if isinstance(value, list) else [value]
    return tuple(
        dict.fromkeys(
            axis
            for item in rows
            if (axis := canonical_variant_axis(text_value(item))) is not None
        )
    )


def _jsonld_variant_options(
    row: dict[str, Any], declared_axes: tuple[str, ...]
) -> list[tuple[str, str, str]]:
    declared = set(declared_axes)
    options = _declared_property_options(row, declared)
    options.extend(_additional_property_options(row, declared))
    return options


def _declared_property_options(
    row: dict[str, Any], declared: set[str]
) -> list[tuple[str, str, str]]:
    if not declared:
        return []
    return [
        (key, axis, value)
        for key, raw_value in row.items()
        if not str(key).startswith("@")
        if (axis := canonical_variant_axis(key)) is not None
        if (value := text_value(raw_value))
        if axis in declared
    ]


def _additional_property_options(
    row: dict[str, Any], declared: set[str]
) -> list[tuple[str, str, str]]:
    properties = row.get("additionalProperty")
    property_rows = properties if isinstance(properties, list) else [properties]
    options: list[tuple[str, str, str]] = []
    for index, item in enumerate(property_rows):
        if not isinstance(item, dict):
            continue
        axis = canonical_variant_axis(
            item.get("name") or item.get("propertyID") or item.get("propertyId")
        )
        value = text_value(item.get("value"))
        if axis and value and (not declared or axis in declared):
            options.append((f"additionalProperty/{index}/value", axis, value))
    return options


def _variant_size(row: dict[str, Any], *, infer_from_name: bool) -> str:
    if explicit := text_value(row.get("size")):
        return explicit
    name = text_value(row.get("name"))
    parts = name.rsplit(VARIANT_JSONLD_NAME_OPTION_SEPARATOR, 2)
    candidate = parts[-1].strip() if len(parts) >= 3 else ""
    if not candidate and infer_from_name:
        candidate = name.rsplit(",", 1)[-1].strip()
    return candidate if 0 < len(candidate) <= 40 else ""


def _variant_color(row: dict[str, Any], *, product_brand: str = "") -> str:
    shade = _shade_from_offer_url(row.get("offers")) or _shade_from_name(
        text_value(row.get("name"))
    )
    color = shade or text_value(row.get("color"))
    if color and product_brand and color.casefold() == product_brand.casefold():
        return ""
    return color


def _jsonld_identity(row: dict[str, Any]) -> str:
    return (
        text_value(row.get(_JSONLD_ID_KEY))
        or text_value(row.get("sku"))
        or text_value(row.get("productGroupID"))
        or text_value(row.get("productID"))
        or text_value(row.get("productId"))
        or text_value(row.get("url"))
    )


def _source_subject_ids(
    bundle: CaptureBundle, row: dict[str, Any], *, include_sku: bool = False
) -> tuple[str, ...]:
    values = tuple(
        dict.fromkeys(
            value
            for value in (
                text_value(row.get(_JSONLD_ID_KEY)),
                text_value(row.get("url")),
                text_value(row.get("productGroupID")),
                text_value(row.get("sku")) if include_sku else "",
            )
            if value
        )
    )
    return tuple(
        stable_id("subject", bundle.bundle_id, "product", value) for value in values
    )


def _known_variant_subject_ids(
    bundle: CaptureBundle, objects: Iterable[tuple[str, Any]]
) -> frozenset[str]:
    return frozenset(
        subject_id
        for path, row in objects
        if isinstance(row, dict)
        and _is_product(row)
        and ("/hasVariant/" in path or _is_standalone_variant(row))
        for subject_id in _source_subject_ids(bundle, row, include_sku=True)
    )


def _item_offered_subject(bundle: CaptureBundle, row: dict[str, Any]) -> str | None:
    item = row.get("itemOffered")
    if isinstance(item, dict):
        if not _is_product(item):
            return None
        value = _jsonld_identity(item)
    else:
        value = text_value(item)
        if not value and text_value(row.get("price")):
            value = text_value(row.get("url"))
    return stable_id("subject", bundle.bundle_id, "product", value) if value else None


def _shade_from_offer_url(offers: Any) -> str:
    rows = offers if isinstance(offers, list) else [offers]
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = parse_qs(urlsplit(text_value(row.get("url"))).query)
        for key in VARIANT_SHADE_URL_QUERY_KEYS:
            values = query.get(key)
            if values and str(values[0] or "").strip():
                return str(values[0]).strip()
    return ""


def _shade_from_name(name: str) -> str:
    parts = [item.strip() for item in name.split(VARIANT_JSONLD_NAME_OPTION_SEPARATOR)]
    return parts[1] if len(parts) >= 3 and parts[1] else ""
