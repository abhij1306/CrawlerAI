from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from functools import partial
from urllib.parse import urlparse

from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES,
    DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_MARKERS,
    DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_STOP_SEGMENTS,
    DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_PRICE_EFFECTIVE_FIELDS,
    DATA_ENRICHMENT_PRICE_ORIGINAL_FIELDS,
    DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_SIZE_CONTEXT_FIELDS,
    DATA_ENRICHMENT_SIZE_CONTEXT_TERMS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
    data_enrichment_settings,
)
from app.enrichment.shopify_catalog import (
    top_taxonomy_candidates as shopify_top_taxonomy_candidates,
)
from app.enrichment.shopify_repository import (
    attribute_lookup_keys,
    load_attribute_repository_data,
    load_taxonomy_index as load_shopify_taxonomy_index,
)
from app.core.shared.currency_hints import currency_hint_from_page_url
from app.core.shared.field_coerce import clean_text, extract_currency_code, text_or_none
from app.core.shared.coerce_primitives import object_dict, object_list
from app.core.shared.material_terms import normalize_materials
from app.core.shared.value_walk import (
    candidate_values,
    decimal_text,
    first_present,
    keyword_tokens,
    split_values,
    targeted_candidate_values,
    term_present,
    tokens,
    without_empty,
)


logger = logging.getLogger(__name__)
price_range_re = re.compile(
    r"\s*[^\d+-]*([+-]?\d[\d,]*(?:\.\d+)?)\s*(?:to|[-–])\s*"
    r"[^\d+-]*([+-]?\d[\d,]*(?:\.\d+)?)(?:\s*(?:[$€£¥]|usd|eur|gbp|cad|aud|inr|each|ea|per|unit|piece|pc|pcs))?\s*",
    re.I,
)


def build_deterministic_enrichment(
    data: dict[str, object], *, source_url: str
) -> dict[str, object]:
    attribute_data = {**data, "source_url": source_url}
    if url_context := category_url_context(data.get("url") or source_url):
        attribute_data["url_category_context"] = url_context
    price_normalized = normalize_price(data, source_url=source_url)
    repository = load_attribute_repository()
    terms = object_dict(repository.get("normalization_terms"))
    category_candidates = top_taxonomy_candidates(attribute_data)
    category_match = category_candidates[0] if category_candidates else None
    category_path = (
        text_or_none(category_match.get("category_path")) if category_match else None
    )
    color_family = normalize_from_terms(
        [
            *candidate_values(
                data,
                *DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS,
            ),
            *targeted_candidate_values(
                data,
                DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS,
                *DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES,
            ),
        ],
        object_dict(terms.get("color_families")),
    )
    size_normalized, size_system = normalize_sizes(
        data,
        terms=terms,
        category_match=category_match,
    )
    gender_normalized = normalize_from_terms(
        candidate_values(
            data,
            *DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS["gender"],
        ),
        object_dict(terms.get("gender_terms")),
    )
    materials_normalized = normalize_materials(data, terms=terms)
    availability_normalized = normalize_from_terms(
        [
            *candidate_values(data, "availability", "product_attributes"),
            *targeted_candidate_values(
                data,
                DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS,
                *DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES,
            ),
        ],
        object_dict(terms.get("availability_terms")),
    )
    seo_keywords = build_seo_keywords(
        data,
        color_family=color_family,
        size_values=size_normalized,
        gender=gender_normalized,
        materials=materials_normalized,
        category_path=category_path,
    )
    return {
        "price_normalized": price_normalized,
        "color_family": color_family,
        "size_normalized": size_normalized,
        "size_system": size_system,
        "gender_normalized": gender_normalized,
        "materials_normalized": materials_normalized,
        "availability_normalized": availability_normalized,
        "seo_keywords": seo_keywords,
        "category_path": category_path,
        "_taxonomy_match": category_match,
        "_taxonomy_candidates": category_candidates,
        "_product_attributes": product_attribute_diagnostics(
            attribute_data, category_match
        ),
    }


def normalize_price(
    data: dict[str, object], *, source_url: str
) -> dict[str, object] | None:
    raw_price = first_present(
        data,
        *DATA_ENRICHMENT_PRICE_EFFECTIVE_FIELDS,
        *DATA_ENRICHMENT_PRICE_ORIGINAL_FIELDS,
    )
    if raw_price in (None, "", [], {}):
        return None
    currency = (
        extract_currency_code(data.get("currency"))
        or extract_currency_code(raw_price)
        or currency_hint_from_page_url(source_url)
    )
    range_match = price_range_re.fullmatch(clean_text(raw_price))
    if range_match:
        try:
            price_min = Decimal(range_match.group(1).replace(",", ""))
            price_max = Decimal(range_match.group(2).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
        return without_empty(
            {
                "price_min": float(price_min),
                "price_max": float(price_max),
                "currency": currency,
            }
        )
    amount = decimal_text(raw_price)
    if amount is None:
        return None
    normalized: dict[str, object] = {"amount": float(amount), "currency": currency}
    sale_amount = decimal_text(first_present(data, "sale_price", "discounted_price"))
    original_amount = decimal_text(
        first_present(data, *DATA_ENRICHMENT_PRICE_ORIGINAL_FIELDS)
    )
    if sale_amount is not None:
        normalized["sale_price"] = float(sale_amount)
    if original_amount is not None:
        normalized["original_price"] = float(original_amount)
    return without_empty(normalized)


def normalize_sizes(
    data: dict[str, object],
    *,
    terms: dict[str, object],
    category_match: dict[str, object] | None = None,
) -> tuple[list[str] | None, str | None]:
    aliases, systems = _size_rules(terms)
    values = [
        *candidate_values(data, *DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS),
        *targeted_candidate_values(
            data,
            DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
            *DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
        ),
    ]
    category_supports_size = bool(
        category_match and category_supports_attribute(category_match, "size")
    )
    if not values and not category_supports_size:
        return None, None
    return _normalize_size_values(
        values,
        aliases=aliases,
        systems=systems,
        require_strong=not (category_supports_size or has_size_context(data)),
    )


def _size_rules(
    terms: dict[str, object],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    size_config = object_dict(terms.get("size_systems"))
    aliases_value = size_config.get("aliases")
    aliases_dict = aliases_value if isinstance(aliases_value, dict) else {}
    aliases = {str(k).casefold(): str(v) for k, v in aliases_dict.items()}
    systems_value = size_config.get("systems")
    systems_dict = systems_value if isinstance(systems_value, dict) else {}
    systems = {
        str(system): {str(item).casefold() for item in values or []}
        for system, values in systems_dict.items()
        if isinstance(values, list)
    }
    return aliases, systems


def _normalize_size_values(
    values: list[object],
    *,
    aliases: dict[str, str],
    systems: dict[str, set[str]],
    require_strong: bool,
) -> tuple[list[str] | None, str | None]:
    normalized: list[str] = []
    seen: set[str] = set()
    detected_system = None
    for value in split_values(values):
        cleaned = clean_text(value).strip()
        if not cleaned:
            continue
        if not plausible_size_value(
            cleaned,
            aliases=aliases,
            systems=systems,
            require_strong=require_strong,
        ):
            continue
        canonical = aliases.get(
            cleaned.casefold(), cleaned.upper() if len(cleaned) <= 4 else cleaned
        )
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(canonical)
        if detected_system is None:
            detected_system = detect_size_system(canonical, systems)
    return (normalized or None), detected_system


def plausible_size_value(
    value: str,
    *,
    aliases: dict[str, str],
    systems: dict[str, set[str]],
    require_strong: bool = False,
) -> bool:
    normalized = clean_text(value).casefold()
    if normalized in aliases:
        return True
    if require_strong and not re.search(r"[a-z]", normalized):
        return False
    if any(normalized in values for values in systems.values()):
        return True
    if require_strong:
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:\s*(?:m|t|w|y|us|uk|eu))?", normalized))


def category_supports_attribute(
    category_match: dict[str, object],
    attribute_handle: str,
) -> bool:
    taxonomy_reference = object_dict(category_match.get("taxonomy_reference"))
    handles = {
        str(item).replace("-", "_")
        for item in object_list(taxonomy_reference.get("attribute_handles"))
        if str(item or "").strip()
    }
    return str(attribute_handle or "").replace("-", "_") in handles


def detect_size_system(value: str, systems: dict[str, set[str]]) -> str | None:
    normalized = clean_text(value).casefold()
    for system, values in systems.items():
        if normalized in values:
            return system
    if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
        return "numeric"
    return None


def has_size_context(data: dict[str, object]) -> bool:
    context = " ".join(
        clean_text(value).casefold()
        for value in candidate_values(data, *DATA_ENRICHMENT_SIZE_CONTEXT_FIELDS)
    )
    if not context:
        return False
    return any(
        term_present(context, term) for term in DATA_ENRICHMENT_SIZE_CONTEXT_TERMS
    )


def normalize_from_terms(
    values: Sequence[object], terms: dict[str, object]
) -> str | None:
    for value in values:
        lowered = clean_text(value).casefold()
        if not lowered:
            continue
        if lowered in terms and not isinstance(terms[lowered], list):
            return str(terms[lowered])
        for canonical, term_tokens in terms.items():
            if isinstance(term_tokens, str):
                if term_present(lowered, canonical) or term_present(
                    lowered, term_tokens
                ):
                    return term_tokens
            elif isinstance(term_tokens, list):
                canonical_text = clean_text(canonical).casefold().replace(" ", "_")
                lowered_key = lowered.replace(" ", "_")
                if canonical_text == lowered_key or any(
                    term_present(lowered, token) for token in term_tokens
                ):
                    return str(canonical)
    return None


def top_taxonomy_candidates(
    data: dict[str, object], *, limit: int | None = None
) -> list[dict[str, object]]:
    if limit is None:
        limit = data_enrichment_settings.llm_taxonomy_hint_count
    return shopify_top_taxonomy_candidates(
        data,
        load_taxonomy_index(),
        category_match_threshold=data_enrichment_settings.category_match_threshold,
        limit=limit,
        candidate_values=category_match_values(data),
        candidate_value_loader=candidate_values,
    )


def category_match_values(data: dict[str, object]) -> list[object]:
    return [
        value
        for key in ("category", "product_type", "title", "url_category_context")
        if (value := data.get(key)) not in (None, "", [], {})
    ]


def build_seo_keywords(
    data: dict[str, object],
    *,
    color_family: str | None,
    size_values: list[str] | None,
    gender: str | None,
    materials: list[str] | None,
    category_path: str | None,
) -> list[str] | None:
    stopwords = {
        str(item).casefold()
        for item in object_list(
            object_dict(load_attribute_repository().get("normalization_terms")).get(
                "seo_stopwords"
            )
        )
    }
    raw_parts = [
        data.get("title"),
        data.get("brand"),
        data.get("category"),
        data.get("product_type"),
        color_family,
        gender,
        category_path,
        *(size_values or []),
        *(materials or []),
    ]
    keywords: list[str] = []
    seen: set[str] = set()
    stem_seen: set[str] = set()
    brand_phrase = clean_text(data.get("brand")).casefold()
    if brand_phrase and " " in brand_phrase:
        keywords.append(brand_phrase)
        seen.add(brand_phrase)
        stem_seen.add(brand_phrase)
    title_tokens = keyword_tokens(data.get("title"), stopwords)
    unigram_tokens = keyword_tokens(
        " ".join(clean_text(part) for part in raw_parts), stopwords
    )
    for token in [
        *unigram_tokens,
        *title_bigrams(title_tokens, set(unigram_tokens)),
    ]:
        cleaned = clean_text(token).casefold()
        stemmed = keyword_stem_key(cleaned)
        if (
            len(cleaned) < 3
            or cleaned in stopwords
            or cleaned in seen
            or stemmed in stem_seen
        ):
            continue
        seen.add(cleaned)
        stem_seen.add(stemmed)
        keywords.append(cleaned)
        if len(keywords) >= data_enrichment_settings.max_seo_keywords:
            break
    return keywords or None


def category_url_context(source_url: object) -> str | None:
    try:
        path = urlparse(clean_text(source_url)).path
        if not path:
            return None
        segments = [
            segment.strip().casefold() for segment in path.split("/") if segment.strip()
        ]
        for marker in DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_MARKERS:
            if marker not in segments:
                continue
            before_marker = segments[: segments.index(marker)]
            useful = [
                segment.replace("-", " ").replace("_", " ")
                for segment in before_marker
                if segment not in DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_STOP_SEGMENTS
                and not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", segment)
            ]
            context = clean_text(" ".join(useful))
            context_tokens = set(tokens(context))
            if {"camera", "cameras"} & context_tokens and "lens" in context_tokens:
                context = clean_text(f"{context} digital cameras")
            return context or None
    except (ValueError, re.error):
        return None
    return None


def keyword_stem_key(value: str) -> str:
    if " " in value:
        return value
    for suffix in ("ing", "ers", "er", "ed"):
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            stem = value[: -len(suffix)]
            if len(stem) >= 2 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            return stem
    return value


def title_bigrams(tokens: list[str], unigrams: set[str]) -> list[str]:
    return list(
        dict.fromkeys(
            clean_text(f"{first} {second}").casefold()
            for first, second in zip(tokens, tokens[1:], strict=False)
            if first in unigrams and second in unigrams
        )
    )


def product_attribute_diagnostics(
    data: dict[str, object],
    category_match: dict[str, object] | None,
) -> dict[str, object]:
    required = [str(item) for item in DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES]
    recommended: list[str] = []
    if category_match:
        taxonomy_reference = object_dict(category_match.get("taxonomy_reference"))
        recommended.extend(
            str(item)
            for item in object_list(taxonomy_reference.get("attribute_handles"))
            if str(item or "").strip()
        )
    attributes = [
        str(item) for item in [*required, *recommended] if str(item or "").strip()
    ]
    attributes = list(dict.fromkeys(attributes))
    present: list[str] = []
    missing: list[str] = []
    for attribute in attributes:
        value = first_present(data, *attribute_lookup_keys(attribute))
        if value in (None, "", [], {}):
            missing.append(attribute)
        else:
            present.append(attribute)
    return {
        "present_attributes": present,
        "null_attributes": missing,
        "required_attributes": required,
        "recommended_attributes": recommended,
    }


load_attribute_repository = partial(
    load_attribute_repository_data, data_enrichment_settings.attributes_path
)
load_taxonomy_index = partial(
    load_shopify_taxonomy_index, data_enrichment_settings.taxonomy_path
)
