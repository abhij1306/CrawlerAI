from __future__ import annotations

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
        "subject", bundle.bundle_id, "product", parent_url or bundle.final_url
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
    product_identity = _jsonld_identity(obj)
    source_subject_ids = _source_subject_ids(bundle, obj)
    hint = EntityHint(
        entity_type="product",
        product_id=text_value(obj.get("productGroupID")) or None,
        sku=text_value(obj.get("sku")) or None,
        url=text_value(obj.get("url")) or None,
    )
    product_subject = stable_id(
        "subject",
        bundle.bundle_id,
        "product",
        hint.url or bundle.final_url or product_identity,
    )
    out = [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            fact,
            text_value(obj.get(key)),
            SourceLocator(kind="json_pointer", value=f"{path}/{key}"),
            hint=hint,
            directness="embedded",
            confidence=0.9,
            subject_id=product_subject,
            subject_scope="product",
            source_subject_ids=source_subject_ids,
        )
        for key, fact in ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES.items()
        if text_value(obj.get(key))
    ]
    raw_image = obj.get("image")
    images = raw_image if isinstance(raw_image, list) else [raw_image]
    for idx, url in enumerate(text_value(item) for item in images if text_value(item)):
        out.append(
            evidence(
                bundle,
                artifact_id,
                "jsonld",
                "asset.image_url",
                url,
                SourceLocator(kind="json_pointer", value=f"{path}/image/{idx}"),
                hint=EntityHint(entity_type="asset"),
                directness="embedded",
                confidence=0.85,
                parent_subject_id=product_subject,
                parent_scope="product",
                relation_type="product_asset",
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
        source_subject_ids = _source_subject_ids(bundle, row, include_sku=True)
        child_parent_subject_id = parent_subject_id
        child_parent_scope = parent_scope
        item_offered = _item_offered_subject(bundle, row)
        if item_offered in variant_subject_ids:
            child_parent_subject_id = item_offered
            child_parent_scope = "variant"
        # Offers embedded under a variant frequently carry the shared product
        # URL as their only identity, collapsing every variant's offer into one
        # group. Namespace the group by the owning variant subject so each
        # variant keeps its own offer (and its own price/availability).
        group = (
            f"offer:{artifact_id}:{child_parent_subject_id}:{offer_identity}"
            if child_parent_scope == "variant" and child_parent_subject_id
            else f"offer:{artifact_id}:{offer_identity}"
        )
        subject_id = group
        out.extend(
            _offer_facts(
                bundle,
                artifact_id,
                row,
                offer_path,
                group,
                subject_id,
                hint,
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
                    subject_id,
                    hint,
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
    variant_identity = _jsonld_identity(row) or path
    hint = EntityHint(
        entity_type="variant",
        product_id=text_value(row.get("productGroupID")) or None,
        variant_id=text_value(row.get(_JSONLD_ID_KEY)) or None,
        sku=sku or None,
        url=text_value(row.get("url")) or None,
    )
    group = f"variant:{artifact_id}:{variant_identity}"
    subject_id = group
    source_subject_ids = _source_subject_ids(bundle, row, include_sku=True)
    out: list[Evidence] = []
    emitted_axes: set[str] = set()
    for key, fact in ECOMMERCE_JSONLD_VARIANT_FACT_TYPES.items():
        value = (
            _variant_color(row, product_brand=product_brand)
            if key == "color"
            else _variant_size(row)
            if key == "size"
            else text_value(row.get(key))
        )
        if value:
            if fact.startswith("variant.option."):
                emitted_axes.add(fact.rsplit(".", 1)[-1])
            out.append(
                evidence(
                    bundle,
                    artifact_id,
                    "jsonld",
                    fact,
                    value,
                    SourceLocator(kind="json_pointer", value=f"{path}/{key}"),
                    group_id=group,
                    hint=hint,
                    directness="embedded",
                    confidence=0.88,
                    subject_id=subject_id,
                    subject_scope="variant",
                    parent_subject_id=product_subject,
                    parent_scope="product",
                    relation_type="product_variant",
                    source_subject_ids=source_subject_ids,
                )
            )
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
                group_id=group,
                hint=hint,
                directness="embedded",
                confidence=0.88,
                subject_id=subject_id,
                subject_scope="variant",
                parent_subject_id=product_subject,
                parent_scope="product",
                relation_type="product_variant",
                source_subject_ids=source_subject_ids,
            )
        )
    raw_image = row.get("image")
    images = raw_image if isinstance(raw_image, list) else [raw_image]
    for index, url in enumerate(
        text_value(item) for item in images if text_value(item)
    ):
        out.append(
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
        )
    out.extend(
        _offers(
            bundle,
            artifact_id,
            row.get("offers"),
            path,
            hint,
            subject_id,
            "variant",
            variant_subject_ids,
        )
    )
    return out


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
    options: list[tuple[str, str, str]] = []
    declared = set(declared_axes)
    for key, raw_value in row.items():
        if not declared or str(key).startswith("@"):
            continue
        axis = canonical_variant_axis(key)
        value = text_value(raw_value)
        if axis and value and axis in declared:
            options.append((key, axis, value))
    properties = row.get("additionalProperty")
    property_rows = properties if isinstance(properties, list) else [properties]
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


def _variant_size(row: dict[str, Any]) -> str:
    explicit = text_value(row.get("size"))
    if explicit:
        return explicit
    parts = [
        item.strip()
        for item in text_value(row.get("name")).split(
            VARIANT_JSONLD_NAME_OPTION_SEPARATOR
        )
    ]
    if len(parts) < 3:
        return ""
    candidate = parts[-1]
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
        or text_value(row.get("url"))
        or text_value(row.get("sku"))
        or text_value(row.get("productGroupID"))
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
    if not value:
        return None
    return stable_id("subject", bundle.bundle_id, "product", value)


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
