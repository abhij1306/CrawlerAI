"""Product-level fact emission from JSON-LD product nodes.

Owns the identity facts, the images, and the attributes that sit beside them -
material, condition, size, colour, audience gender, and the nested
``aggregateRating`` node. Kept apart from ``jsonld.py`` so that module stays
focused on locating nodes and harvesting offers and variants.
"""

from __future__ import annotations

from typing import Any

from app.core.config import field_mappings
from app.extraction.collectors._helpers import evidence, text_value
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator

__all__ = [
    "product_attribute_evidence",
    "product_fact_evidence",
    "product_image_evidence",
    "shared_product_offer_condition_evidence",
]


def shared_product_offer_condition_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    offers: Any,
    path: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
) -> list[Evidence]:
    """Lift an offer condition only when every stated product offer agrees."""
    if parent_scope != "product" or not parent_subject_id:
        return []
    rows = offers if isinstance(offers, list) else [offers]
    key = field_mappings.ECOMMERCE_JSONLD_ITEM_CONDITION_KEY
    located = [
        (index, value)
        for index, row in enumerate(rows)
        if isinstance(row, dict) and (value := text_value(row.get(key)))
    ]
    if not located or len({value.casefold() for _index, value in located}) != 1:
        return []
    index, value = located[0]
    offer_path = (
        f"{path}/offers/{index}" if isinstance(offers, list) else f"{path}/offers"
    )
    return [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            field_mappings.PRODUCT_CONDITION_FACT_TYPE,
            value,
            SourceLocator(kind="json_pointer", value=f"{offer_path}/{key}"),
            hint=hint,
            directness="embedded",
            confidence=0.9,
            subject_id=parent_subject_id,
            subject_scope="product",
        )
    ]


def product_attribute_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    obj: dict[str, Any],
    path: str,
    *,
    hint: EntityHint,
    product_subject: str,
    source_subject_ids: tuple[str, ...],
) -> list[Evidence]:
    """Product attributes that sit beside identity: material, condition, size,
    colour, audience gender, and the nested ``aggregateRating`` node."""
    rows: list[tuple[str, str, str]] = []
    for (
        key,
        fact,
    ) in field_mappings.ECOMMERCE_JSONLD_PRODUCT_ATTRIBUTE_FACT_TYPES.items():
        if value := text_value(obj.get(key)):
            rows.append((fact, value, f"{path}/{key}"))
    rating = obj.get("aggregateRating")
    if isinstance(rating, dict):
        for keys, fact in (
            (
                field_mappings.ECOMMERCE_JSONLD_RATING_KEYS,
                field_mappings.PRODUCT_RATING_FACT_TYPE,
            ),
            (
                field_mappings.ECOMMERCE_JSONLD_REVIEW_COUNT_KEYS,
                field_mappings.PRODUCT_REVIEW_COUNT_FACT_TYPE,
            ),
        ):
            for key in keys:
                if value := text_value(rating.get(key)):
                    rows.append((fact, value, f"{path}/aggregateRating/{key}"))
                    break
    raw_audience = obj.get("audience")
    audiences = raw_audience if isinstance(raw_audience, list) else [raw_audience]
    sources = [(path, obj)] + [
        (
            f"{path}/audience/{index}"
            if isinstance(raw_audience, list)
            else f"{path}/audience",
            item,
        )
        for index, item in enumerate(audiences)
    ]
    for prefix, source in sources:
        if not isinstance(source, dict):
            continue
        for key in field_mappings.ECOMMERCE_JSONLD_GENDER_KEYS:
            if value := text_value(source.get(key)):
                rows.append(
                    (field_mappings.PRODUCT_GENDER_FACT_TYPE, value, f"{prefix}/{key}")
                )
                break
    return [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            fact,
            value,
            SourceLocator(kind="json_pointer", value=locator),
            hint=hint,
            directness="embedded",
            confidence=0.9,
            subject_id=product_subject,
            subject_scope="product",
            source_subject_ids=source_subject_ids,
        )
        for fact, value, locator in rows
    ]


def product_fact_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    obj: dict[str, Any],
    path: str,
    *,
    hint: EntityHint,
    product_subject: str,
    source_subject_ids: tuple[str, ...],
    explicit_node_id: str,
) -> list[Evidence]:
    return [
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
            metadata={
                "jsonld_node_id": explicit_node_id,
                "jsonld_node_path": path if not explicit_node_id else "",
            },
        )
        for key, fact in field_mappings.ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES.items()
        if text_value(obj.get(key))
    ]


def product_image_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    obj: dict[str, Any],
    path: str,
    *,
    product_subject: str,
) -> list[Evidence]:
    raw_image = obj.get("image")
    images: list[Any] = raw_image if isinstance(raw_image, list) else [raw_image]
    is_list = isinstance(raw_image, list)
    # Index from the source list so a skipped empty entry cannot shift the
    # locator onto a different element; a scalar has no index at all.
    located = [
        (text_value(item), f"{path}/image/{index}" if is_list else f"{path}/image")
        for index, item in enumerate(images)
        if text_value(item)
    ]
    return [
        evidence(
            bundle,
            artifact_id,
            "jsonld",
            "asset.image_url",
            url,
            SourceLocator(kind="json_pointer", value=locator),
            hint=EntityHint(entity_type="asset"),
            directness="embedded",
            confidence=0.85,
            parent_subject_id=product_subject,
            parent_scope="product",
            relation_type="product_asset",
        )
        for url, locator in located
    ]
