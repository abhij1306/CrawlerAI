from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.core.config.extraction_rules import (
    VARIANT_JSONLD_NAME_OPTION_SEPARATOR,
    VARIANT_SHADE_URL_QUERY_KEYS,
)
from app.extraction.collectors._helpers import evidence, html_doc, json_objects, loads_jsonish, text_value
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class JsonLdCollector:
    collector_id = "jsonld"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        for index, tag in enumerate(doc.css('script[type*="ld+json"]')):
            data = loads_jsonish(tag.text())
            for path, obj in json_objects(data):
                if isinstance(obj, dict) and _is_product(obj) and "/hasVariant/" not in path:
                    out.extend(_product(bundle, f"jsonld:{index}", obj, path))
        return tuple(out)


def _is_product(obj: dict[str, Any]) -> bool:
    types = obj.get("@type") or obj.get("type")
    values = types if isinstance(types, list) else [types]
    return any(str(item).lower() in {"product", "productgroup"} for item in values)


def _product(bundle: CaptureBundle, artifact_id: str, obj: dict[str, Any], path: str) -> list[Evidence]:
    hint = EntityHint(entity_type="product", sku=text_value(obj.get("sku")) or None, url=text_value(obj.get("url")) or None)
    product_subject = f"product:{artifact_id}:{path or '/'}"
    fields = {"name": "product.title", "brand": "product.brand", "description": "product.description", "sku": "product.sku", "mpn": "product.mpn", "gtin": "product.gtin", "url": "product.url"}
    out = [
        evidence(bundle, artifact_id, "jsonld", fact, text_value(obj.get(key)), SourceLocator(kind="json_pointer", value=f"{path}/{key}"), hint=hint, directness="embedded", confidence=0.9, subject_id=product_subject)
        for key, fact in fields.items()
        if text_value(obj.get(key))
    ]
    raw_image = obj.get("image")
    images = raw_image if isinstance(raw_image, list) else [raw_image]
    for idx, url in enumerate(text_value(item) for item in images if text_value(item)):
        out.append(evidence(bundle, artifact_id, "jsonld", "asset.image_url", url, SourceLocator(kind="json_pointer", value=f"{path}/image/{idx}"), hint=EntityHint(entity_type="asset"), directness="embedded", confidence=0.85, parent_subject_id=product_subject))
    out.extend(_offers(bundle, artifact_id, obj.get("offers"), path, hint, product_subject))
    out.extend(_variants(bundle, artifact_id, obj.get("hasVariant"), path, hint, product_subject))
    return out


def _offers(bundle: CaptureBundle, artifact_id: str, offers: Any, path: str, hint: EntityHint, parent_subject_id: str | None = None) -> list[Evidence]:
    rows = offers if isinstance(offers, list) else [offers]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        group = f"offer:{artifact_id}:{path}/offers/{index}"
        subject_id = group
        for key, fact in {
            "price": "offer.price",
            "lowPrice": "offer.price",
            "priceCurrency": "offer.currency",
            "availability": "offer.availability",
            "seller": "offer.seller",
        }.items():
            value = text_value(row.get(key))
            if value:
                out.append(evidence(bundle, artifact_id, "jsonld", fact, value, SourceLocator(kind="json_pointer", value=f"{path}/offers/{index}/{key}"), group_id=group, hint=hint, directness="embedded", confidence=0.9, subject_id=subject_id, parent_subject_id=parent_subject_id))
    return out


def _variants(bundle: CaptureBundle, artifact_id: str, variants: Any, path: str, product_hint: EntityHint, product_subject: str) -> list[Evidence]:
    rows = variants if isinstance(variants, list) else [variants]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        sku = text_value(row.get("sku"))
        hint = EntityHint(entity_type="variant", sku=sku or None, url=text_value(row.get("url")) or None)
        group = f"variant:{artifact_id}:{path}/hasVariant/{index}"
        subject_id = group
        for key, fact in {"sku": "variant.sku", "gtin": "variant.gtin", "url": "variant.url", "color": "variant.option.color", "size": "variant.option.size"}.items():
            value = _variant_color(row) if key == "color" else text_value(row.get(key))
            if value:
                out.append(evidence(bundle, artifact_id, "jsonld", fact, value, SourceLocator(kind="json_pointer", value=f"{path}/hasVariant/{index}/{key}"), group_id=group, hint=hint, directness="embedded", confidence=0.88, subject_id=subject_id, parent_subject_id=product_subject))
        out.extend(_offers(bundle, artifact_id, row.get("offers"), f"{path}/hasVariant/{index}", hint, subject_id))
    return out


def _variant_color(row: dict[str, Any]) -> str:
    shade = _shade_from_offer_url(row.get("offers")) or _shade_from_name(text_value(row.get("name")))
    return shade or text_value(row.get("color"))


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
