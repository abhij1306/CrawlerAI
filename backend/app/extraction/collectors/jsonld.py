from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.core.config.field_mappings import (
    ECOMMERCE_JSONLD_OFFER_FACT_TYPES,
    ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES,
    ECOMMERCE_JSONLD_VARIANT_FACT_TYPES,
)
from app.core.config.extraction_rules import (
    VARIANT_JSONLD_NAME_OPTION_SEPARATOR,
    VARIANT_SHADE_URL_QUERY_KEYS,
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
from app.core.shared.ids import stable_id


_IS_VARIANT_OF_KEY = "is" + "VariantOf"
_JSONLD_ID_KEY = "@" + "id"


class JsonLdCollector:
    collector_id = "jsonld"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        for index, tag in enumerate(doc.css('script[type*="ld+json"]')):
            data = loads_jsonish(tag.text())
            objects = tuple(json_objects(data))
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
                        _standalone_variant(bundle, f"jsonld:{index}", obj, path)
                    )
                    continue
                out.extend(_product(bundle, f"jsonld:{index}", obj, path))
        return tuple(out)


def _is_product(obj: dict[str, Any]) -> bool:
    types = obj.get("@type") or obj.get("type")
    values = types if isinstance(types, list) else [types]
    return any(str(item).lower() in {"product", "productgroup"} for item in values)


def _is_standalone_variant(obj: dict[str, Any]) -> bool:
    return isinstance(obj.get(_IS_VARIANT_OF_KEY), (dict, str))


def _standalone_variant(
    bundle: CaptureBundle, artifact_id: str, row: dict[str, Any], path: str
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
    return _variant(bundle, artifact_id, row, path, product_subject)


def _product(
    bundle: CaptureBundle, artifact_id: str, obj: dict[str, Any], path: str
) -> list[Evidence]:
    hint = EntityHint(
        entity_type="product",
        sku=text_value(obj.get("sku")) or None,
        url=text_value(obj.get("url")) or None,
    )
    product_subject = stable_id(
        "subject", bundle.bundle_id, "product", hint.url or bundle.final_url
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
            )
        )
    out.extend(
        _offers(bundle, artifact_id, obj.get("offers"), path, hint, product_subject)
    )
    out.extend(
        _variants(
            bundle,
            artifact_id,
            obj.get("hasVariant"),
            path,
            text_value(obj.get("brand")),
            product_subject,
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
) -> list[Evidence]:
    rows = offers if isinstance(offers, list) else [offers]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        offer_path = f"{path}/offers/{index}"
        group = f"offer:{artifact_id}:{offer_path}"
        subject_id = group
        for key, fact in ECOMMERCE_JSONLD_OFFER_FACT_TYPES.items():
            value = text_value(row.get(key))
            if value:
                out.append(
                    evidence(
                        bundle,
                        artifact_id,
                        "jsonld",
                        fact,
                        value,
                        SourceLocator(kind="json_pointer", value=f"{offer_path}/{key}"),
                        group_id=group,
                        hint=hint,
                        directness="embedded",
                        confidence=0.9,
                        subject_id=subject_id,
                        parent_subject_id=parent_subject_id,
                        parent_scope=parent_scope,
                    )
                )
        out.extend(
            _offers(
                bundle,
                artifact_id,
                row.get("offers"),
                offer_path,
                hint,
                parent_subject_id,
                parent_scope,
            )
        )
    return out


def _variants(
    bundle: CaptureBundle,
    artifact_id: str,
    variants: Any,
    path: str,
    product_brand: str,
    product_subject: str,
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
) -> list[Evidence]:
    sku = text_value(row.get("sku"))
    hint = EntityHint(
        entity_type="variant",
        sku=sku or None,
        url=text_value(row.get("url")) or None,
    )
    group = f"variant:{artifact_id}:{path}"
    subject_id = group
    out: list[Evidence] = []
    for key, fact in ECOMMERCE_JSONLD_VARIANT_FACT_TYPES.items():
        value = (
            _variant_color(row, product_brand=product_brand)
            if key == "color"
            else _variant_size(row)
            if key == "size"
            else text_value(row.get(key))
        )
        if value:
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
                    parent_subject_id=product_subject,
                    parent_scope="product",
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
        )
    )
    return out


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
