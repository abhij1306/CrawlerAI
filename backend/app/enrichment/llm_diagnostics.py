from __future__ import annotations

import logging

from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_LLM_BACKFILL_FIELDS,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
    data_enrichment_settings,
)
from app.models.data_enrichment import EnrichedProduct
from app.core.shared.field_coerce import clean_text, strip_html_tags, text_or_none
from app.core.shared.coerce_primitives import object_dict, object_list
from app.core.shared.text_coerce import bounded_unique_strings as string_list
from app.enrichment.deterministic import (
    load_attribute_repository,
    load_taxonomy_index,
    normalize_from_terms,
    normalize_materials,
    normalize_sizes,
)
from app.enrichment.discovery_tags import (
    ai_discovery_allowed_tags_for_product,
    discovery_tag_slug,
)
from app.enrichment.shopify_catalog import (
    category_attribute_handles,
    taxonomy_reference_for_category_path,
)
from app.core.shared.value_walk import without_empty

logger = logging.getLogger(__name__)


def missing_llm_backfill_fields(product: EnrichedProduct) -> list[str]:
    return [
        str(name)
        for name in DATA_ENRICHMENT_LLM_BACKFILL_FIELDS
        if getattr(product, name) in (None, "", [], {})
    ]


def llm_prompt_context(
    source_data: dict[str, object],
    *,
    product: EnrichedProduct,
    category_candidates: list[dict[str, object]],
) -> dict[str, object]:
    description = clean_text(strip_html_tags(source_data.get("description")))
    category_anchor = product.category_path or text_or_none(
        category_candidates[0].get("category_path") if category_candidates else None
    )
    context = without_empty(
        {
            "title": clean_text(source_data.get("title")),
            "brand": clean_text(source_data.get("brand")),
            "category": clean_text(source_data.get("category")),
            "product_type": clean_text(source_data.get("product_type")),
            "price_normalized": product.price_normalized,
            "color_family": product.color_family,
            "size_normalized": product.size_normalized,
            "size_system": product.size_system,
            "gender_normalized": product.gender_normalized,
            "materials_normalized": product.materials_normalized,
            "availability_normalized": product.availability_normalized,
            "seo_keywords": product.seo_keywords,
            "category_path": product.category_path,
            "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
            "missing_backfill_fields": missing_llm_backfill_fields(product),
            "taxonomy_candidates": [
                taxonomy_candidate_context(candidate)
                for candidate in category_candidates[
                    : data_enrichment_settings.llm_taxonomy_hint_count
                ]
            ],
            "category_attributes": category_attribute_handles(
                category_anchor,
                load_taxonomy_index(),
            ),
            "ai_discovery_allowed_tags": ai_discovery_allowed_tags_for_product(product),
        }
    )
    if description:
        context["description_excerpt"] = description[
            : data_enrichment_settings.llm_description_excerpt_chars
        ]
    return context


def taxonomy_candidate_context(candidate: dict[str, object]) -> dict[str, object]:
    taxonomy_reference = object_dict(candidate.get("taxonomy_reference"))
    return without_empty(
        {
            "category_id": candidate.get("category_id"),
            "category_path": candidate.get("category_path"),
            "score": candidate.get("score"),
            "source": candidate.get("source"),
            "taxonomy_version": candidate.get("taxonomy_version")
            or taxonomy_reference.get("taxonomy_version")
            or DATA_ENRICHMENT_TAXONOMY_VERSION,
            "attribute_handles": object_list(
                taxonomy_reference.get("attribute_handles")
            ),
        }
    )


def taxonomy_hint(
    category_path: str | None,
    *,
    category_candidates: list[dict[str, object]],
    missing_fields: list[str],
) -> str:
    if category_path:
        guidance = f"Current deterministic category is {category_path}."
    else:
        candidate_paths = ", ".join(
            str(item.get("category_path") or "")
            for item in category_candidates[
                : data_enrichment_settings.llm_taxonomy_hint_count
            ]
            if str(item.get("category_path") or "").strip()
        )
        guidance = (
            f"Prefer one of these candidates when supported by evidence: {candidate_paths}."
            if candidate_paths
            else "Return only real Shopify category paths."
        )
    return (
        f"Use Shopify taxonomy version {DATA_ENRICHMENT_TAXONOMY_VERSION}. {guidance} "
        f"Only fill missing fields: {', '.join(missing_fields) or 'none'}."
    )


def apply_llm_payload(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    allowed_tags: list[str] | None = None,
) -> list[str]:
    applied: list[str] = []
    terms = object_dict(load_attribute_repository().get("normalization_terms"))
    _apply_category(product, payload, applied)
    _apply_normalized_terms(product, payload, terms=terms, applied=applied)
    _apply_sizes(product, payload, terms=terms, applied=applied)
    _apply_materials(product, payload, terms=terms, applied=applied)
    applied.extend(_apply_semantic_fields(product, payload, allowed_tags=allowed_tags))
    product.taxonomy_version = DATA_ENRICHMENT_TAXONOMY_VERSION
    return applied


def _apply_category(
    product: EnrichedProduct, payload: dict[str, object], applied: list[str]
) -> None:
    category_path = text_or_none(payload.get("category_path"))
    if product.category_path is not None or not category_path:
        return
    reference = taxonomy_reference_for_category_path(
        category_path,
        load_taxonomy_index(),
    )
    if reference is None:
        return
    resolved_category_path = text_or_none(reference.get("category_path"))
    if not resolved_category_path:
        return
    product.category_path = resolved_category_path
    applied.append("category_path")


def _apply_normalized_terms(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    terms: dict[str, object],
    applied: list[str],
) -> None:
    for field_name, term_name in (
        ("color_family", "color_families"),
        ("gender_normalized", "gender_terms"),
        ("availability_normalized", "availability_terms"),
    ):
        if getattr(product, field_name) is not None:
            continue
        raw_value = payload.get(field_name)
        normalized = normalize_from_terms(
            string_list(raw_value, max_items=1, max_chars=60) or [raw_value],
            object_dict(terms.get(term_name)),
        )
        if normalized:
            setattr(product, field_name, normalized)
            applied.append(field_name)


def _apply_sizes(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    terms: dict[str, object],
    applied: list[str],
) -> None:
    if product.size_normalized is None:
        size_normalized, size_system = normalize_sizes(
            {
                "size": payload.get("size_normalized"),
                "size_system": payload.get("size_system"),
                "category": product.category_path,
            },
            terms=terms,
            category_match=_category_match_for_product_path(product.category_path),
        )
        if size_normalized:
            product.size_normalized = size_normalized
            applied.append("size_normalized")
        if product.size_system is None and size_system:
            product.size_system = size_system
            applied.append("size_system")
    if product.size_system is not None:
        return
    size_system = text_or_none(payload.get("size_system"))
    known_systems = set(
        map(
            str,
            object_dict(object_dict(terms.get("size_systems")).get("systems")),
        )
    )
    if size_system and size_system in known_systems:
        product.size_system = size_system
        applied.append("size_system")


def _apply_materials(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    terms: dict[str, object],
    applied: list[str],
) -> None:
    if product.materials_normalized is not None:
        return
    materials = normalize_materials(
        {"materials": payload.get("materials_normalized")}, terms=terms
    )
    if materials:
        product.materials_normalized = materials
        applied.append("materials_normalized")


def _apply_semantic_fields(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    allowed_tags: list[str] | None,
) -> list[str]:
    applied: list[str] = []
    allowed = set(allowed_tags or ai_discovery_allowed_tags_for_product(product))
    for field_name in (
        "intent_attributes",
        "audience",
        "style_tags",
        "ai_discovery_tags",
        "suggested_bundles",
    ):
        values = _semantic_values(payload, field_name)
        if field_name == "ai_discovery_tags":
            values = _supported_discovery_tags(product, values, allowed)
        setattr(product, field_name, values or None)
        if values:
            applied.append(field_name)
    return applied


def _semantic_values(payload: dict[str, object], field_name: str) -> list[str]:
    max_chars = (
        data_enrichment_settings.llm_semantic_list_item_chars
        if field_name in {"intent_attributes", "audience", "style_tags"}
        else 60
    )
    return string_list(payload.get(field_name), max_items=10, max_chars=max_chars)


def _supported_discovery_tags(
    product: EnrichedProduct, values: list[str], allowed: set[str]
) -> list[str]:
    pairs = [(str(value), discovery_tag_slug(value)) for value in values]
    discarded = [
        {"value": value, "slug": slug}
        for value, slug in pairs
        if slug and slug not in allowed
    ]
    if discarded:
        logger.warning(
            "Discarded unsupported ai_discovery_tags for product_id=%s: %s",
            product.id,
            discarded,
        )
    return [slug for _value, slug in pairs if slug and slug in allowed]


def _category_match_for_product_path(
    category_path: str | None,
) -> dict[str, object] | None:
    if not category_path:
        return None
    reference = taxonomy_reference_for_category_path(
        category_path, load_taxonomy_index()
    )
    if reference is None:
        return None
    return {
        "category_path": str(reference.get("category_path") or category_path),
        "taxonomy_reference": reference,
    }


def build_llm_diagnostics(
    payload: dict[str, object], applied_fields: list[str]
) -> dict[str, object]:
    return {
        "rejected_payload": rejected_llm_payload(payload, applied_fields),
    }


def rejected_llm_payload(
    payload: dict[str, object], applied_fields: list[str]
) -> dict[str, object]:
    applied = set(applied_fields)
    rejected: dict[str, object] = {}
    for key, value in payload.items():
        if key in applied or value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            if values := string_list(value, max_items=10, max_chars=60):
                rejected[str(key)] = values
            continue
        if text := text_or_none(value):
            rejected[str(key)] = text[:120]
    return rejected
