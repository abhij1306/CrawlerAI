from __future__ import annotations

from app.services.extraction_v2.collectors._helpers import evidence, json_objects
from app.services.extraction_v2.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


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


def network_row(bundle: CaptureBundle, artifact_id: str, path: str, obj: dict) -> list[Evidence]:
    mapping = {"title": "product.title", "name": "product.title", "brand": "product.brand", "sku": "product.sku", "price": "offer.price", "currency": "offer.currency", "available": "offer.availability", "availability": "offer.availability", "image": "asset.image_url", "imageUrl": "asset.image_url"}
    out: list[Evidence] = []
    if not any(key in obj for key in mapping):
        out.extend(_variant_row(bundle, artifact_id, path, obj))
        return out
    group = f"offer:{artifact_id}:{path}" if any(key in obj for key in ("price", "currency", "available", "availability")) else None
    for key, fact in mapping.items():
        value = _scalar_value(obj.get(key))
        if value in (None, "", [], {}):
            continue
        hint = EntityHint(entity_type="offer" if fact.startswith("offer.") else "asset" if fact.startswith("asset.") else "product", sku=str(obj.get("sku") or "").strip() or None)
        out.append(evidence(bundle, artifact_id, "js_state", fact, value, SourceLocator(kind="script_path", value=f"{path}/{key}"), group_id=group if fact.startswith("offer.") else None, hint=hint, directness="embedded", confidence=0.8))
    return out


def _variant_row(bundle: CaptureBundle, artifact_id: str, path: str, obj: dict) -> list[Evidence]:
    if not _looks_like_variant(obj):
        return []
    sku = str(_scalar_value(obj.get("sku") or obj.get("id") or "") or "").strip()
    hint = EntityHint(entity_type="variant", variant_id=str(obj.get("id") or "").strip() or None, sku=sku or None, selected=bool(obj.get("selected") or obj.get("isSelected")))
    group = f"variant:{artifact_id}:{path}"
    fields = _variant_fields(obj)
    out = [
        evidence(bundle, artifact_id, "js_state", fact, value, SourceLocator(kind="script_path", value=f"{path}/{name}"), group_id=group, hint=hint, directness="embedded", confidence=0.82)
        for name, fact, value in fields
        if value not in (None, "", [], {})
    ]
    out.extend(_variant_offer(bundle, artifact_id, path, obj, hint))
    return out


def _looks_like_variant(obj: dict) -> bool:
    keys = {str(key).lower() for key in obj}
    identity = bool(keys & {"sku", "id", "variantid", "variant_id"})
    options = bool(keys & {"size", "color", "colour", "width", "length", "style", "capacity", "quantity"})
    typed = "variant" in str(obj.get("type") or obj.get("__typename") or "").lower()
    return (identity and options) or typed


def _variant_fields(obj: dict) -> list[tuple[str, str, object]]:
    raw = [
        ("id", "variant.id", obj.get("id") or obj.get("variantId") or obj.get("variant_id")),
        ("sku", "variant.sku", obj.get("sku")),
        ("url", "variant.url", obj.get("url")),
        ("selected", "variant.selected", bool(obj.get("selected") or obj.get("isSelected"))),
    ]
    axes = {"size": "size", "color": "color", "colour": "color", "width": "width", "length": "length", "material": "material", "style": "style", "capacity": "capacity", "quantity": "quantity"}
    raw.extend((key, f"variant.option.{axis}", _scalar_value(obj.get(key))) for key, axis in axes.items())
    return [(name, fact, _scalar_value(value)) for name, fact, value in raw]


def _variant_offer(bundle: CaptureBundle, artifact_id: str, path: str, obj: dict, hint: EntityHint) -> list[Evidence]:
    group = f"offer:{artifact_id}:{path}"
    rows = [("price", "offer.price", obj.get("price")), ("currency", "offer.currency", obj.get("currency")), ("availability", "offer.availability", obj.get("availability") or obj.get("available"))]
    return [
        evidence(bundle, artifact_id, "js_state", fact, _scalar_value(value), SourceLocator(kind="script_path", value=f"{path}/{name}"), group_id=group, hint=hint, directness="embedded", confidence=0.82)
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
