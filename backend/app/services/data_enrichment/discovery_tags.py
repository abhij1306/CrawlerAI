from __future__ import annotations

import re

from app.models.data_enrichment import EnrichedProduct
from app.services.data_enrichment.deterministic import category_attribute_handles
from app.services.shared.field_coerce import clean_text


def ai_discovery_allowed_tags_for_product(product: EnrichedProduct) -> list[str]:
    seo_keywords = product.seo_keywords if isinstance(product.seo_keywords, list) else []
    materials = (
        product.materials_normalized
        if isinstance(product.materials_normalized, list)
        else []
    )
    sizes = product.size_normalized if isinstance(product.size_normalized, list) else []
    prioritized_values: list[tuple[int, object]] = [
        *((100, value) for value in seo_keywords),
        (90, product.category_path),
        *(
            (85, value)
            for value in category_attribute_handles(product.category_path)
            if product.category_path
        ),
        (70, product.color_family),
        (70, product.gender_normalized),
        *((50, value) for value in materials),
        *((50, value) for value in sizes),
    ]
    scored: dict[str, tuple[int, int]] = {}
    for index, (priority, value) in enumerate(prioritized_values):
        for tag in discovery_tag_candidates(value):
            current = scored.get(tag)
            if current is None or priority > current[0]:
                scored[tag] = (priority, index)
    return [
        tag
        for tag, _score in sorted(
            scored.items(),
            key=lambda item: (-item[1][0], item[1][1], item[0]),
        )[:50]
    ]


def discovery_tag_candidates(value: object) -> list[str]:
    text = clean_text(value).casefold()
    if not text:
        return []
    parts = [text]
    if ">" in text:
        parts.extend(clean_text(part).casefold() for part in text.split(">"))
    return [tag for part in parts if (tag := discovery_tag_slug(part))]


def discovery_tag_slug(value: object) -> str:
    text = clean_text(value).casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text)
