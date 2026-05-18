from __future__ import annotations

import logging
import re
from collections.abc import Collection, Sequence
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES,
    DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS,
    DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS,
    DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS,
    DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS,
    DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
    DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
    data_enrichment_settings,
)
from app.services.data_enrichment.shopify_catalog import (
    attribute_lookup_keys,
    category_attribute_handles as shopify_category_attribute_handles,
    load_attribute_repository_data,
    load_taxonomy_index as load_shopify_taxonomy_index,
    repository_terms,
    term_dict,
    top_taxonomy_candidates as shopify_top_taxonomy_candidates,
)
from app.services.extract.detail.price.core import currency_hint_from_page_url
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import (
    clean_text,
    extract_currency_code,
    strip_html_tags,
    text_or_none,
)


logger = logging.getLogger(__name__)
token_re = re.compile(r"[a-z0-9]+")
price_range_re = re.compile(
    r"\s*[^\d+-]*([+-]?\d[\d,]*(?:\.\d+)?)\s*(?:to|[-–])\s*"
    r"[^\d+-]*([+-]?\d[\d,]*(?:\.\d+)?)(?:\s*(?:[$€£¥]|usd|eur|gbp|cad|aud|inr|each|ea|per|unit|piece|pc|pcs))?\s*",
    re.I,
)


def build_deterministic_enrichment(
    data: dict[str, object], *, source_url: str
) -> dict[str, object]:
    attribute_data = {**data, "source_url": source_url}
    price_normalized = normalize_price(data, source_url=source_url)
    repository = load_attribute_repository()
    terms = repository_terms(repository)
    category_candidates = top_taxonomy_candidates(data)
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
        term_dict(terms, "color_families"),
    )
    size_normalized, size_system = normalize_sizes(
        data,
        terms=terms,
        category_match=category_match,
    )
    gender_normalized = normalize_from_terms(
        candidate_values(data, "gender", "category", "product_type", "title"),
        term_dict(terms, "gender_terms"),
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
        term_dict(terms, "availability_terms"),
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
    raw_price = first_present(data, "price", "sale_price", "original_price")
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
    return without_empty({"amount": float(amount), "currency": currency})


def normalize_sizes(
    data: dict[str, object],
    *,
    terms: dict[str, object],
    category_match: dict[str, object] | None = None,
) -> tuple[list[str] | None, str | None]:
    size_config = term_dict(terms, "size_systems")
    aliases_value = size_config.get("aliases")
    aliases_dict = aliases_value if isinstance(aliases_value, dict) else {}
    aliases = {str(k).casefold(): str(v) for k, v in aliases_dict.items()}
    systems_value = size_config.get("systems")
    systems_dict = systems_value if isinstance(systems_value, dict) else {}
    systems = {
        str(system): {str(item).casefold() for item in list(values or [])}
        for system, values in systems_dict.items()
        if isinstance(values, list)
    }
    values = [
        *candidate_values(data, *DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS),
        *targeted_candidate_values(
            data,
            DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS,
            *DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES,
        ),
    ]
    category_supports_size = (
        category_supports_attribute(category_match, "size")
        if category_match
        else not clean_text(data.get("category") or data.get("product_type"))
    )
    if not values and not category_supports_size:
        return None, None
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
            require_strong=not category_supports_size,
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
    return None


def normalize_materials(
    data: dict[str, object], *, terms: dict[str, object]
) -> list[str] | None:
    material_terms = term_dict(terms, "material_terms")
    found: list[str] = []
    seen: set[str] = set()
    values = candidate_values(data, *DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS)
    fallback_values = candidate_values(data, *DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS)
    for value in [*values, *fallback_values]:
        lowered = strip_material_context_noise(
            clean_text(strip_html_tags(value)).casefold()
        )
        for canonical, tokens in material_terms.items():
            if canonical in seen:
                continue
            if isinstance(tokens, list) and any(
                term_present(lowered, token) for token in tokens
            ):
                found.append(str(canonical))
                seen.add(str(canonical))
    return found or None


@lru_cache(maxsize=1)
def compiled_material_strip_patterns() -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in tuple(DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS or ()):
        try:
            compiled.append(re.compile(str(pattern), re.I))
        except re.error:
            logger.warning("Skipping invalid material strip pattern: %r", pattern)
    return tuple(compiled)


def strip_material_context_noise(value: str) -> str:
    cleaned = value
    for pattern in compiled_material_strip_patterns():
        cleaned = pattern.sub("", cleaned)
    return clean_text(cleaned)


def normalize_from_terms(
    values: Sequence[object], terms: dict[str, object]
) -> str | None:
    for value in values:
        lowered = clean_text(value).casefold()
        if not lowered:
            continue
        if lowered in terms and not isinstance(terms[lowered], list):
            return str(terms[lowered])
        for canonical, tokens in terms.items():
            if isinstance(tokens, str):
                if term_present(lowered, canonical) or term_present(lowered, tokens):
                    return tokens
            elif isinstance(tokens, list):
                canonical_text = clean_text(canonical).casefold().replace(" ", "_")
                lowered_key = lowered.replace(" ", "_")
                if canonical_text == lowered_key or any(
                    term_present(lowered, token) for token in tokens
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


def match_category_path(data: dict[str, object]) -> dict[str, object] | None:
    candidates = top_taxonomy_candidates(data, limit=1)
    return candidates[0] if candidates else None


def category_match_values(data: dict[str, object]) -> list[object]:
    values: list[object] = []
    for key in ("category", "product_type", "title"):
        value = first_present(data, key)
        if value in (None, "", [], {}):
            continue
        values.append(value)
    return values


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
            repository_terms(load_attribute_repository()).get("seo_stopwords")
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
    title_tokens = keyword_tokens(data.get("title"), stopwords)
    unigram_tokens = keyword_tokens(
        " ".join(clean_text(part) for part in raw_parts), stopwords
    )
    for token in [
        *unigram_tokens,
        *semantic_bigrams(title_tokens, set(unigram_tokens)),
    ]:
        cleaned = clean_text(token).casefold()
        if len(cleaned) < 3 or cleaned in stopwords or cleaned in seen:
            continue
        seen.add(cleaned)
        keywords.append(cleaned)
        if len(keywords) >= data_enrichment_settings.max_seo_keywords:
            break
    return keywords or None


def semantic_bigrams(tokens: list[str], unigrams: set[str]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for index in range(len(tokens) - 1):
        first = tokens[index]
        second = tokens[index + 1]
        if first not in unigrams or second not in unigrams:
            continue
        phrase = clean_text(f"{first} {second}").casefold()
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)
    return phrases


def normalize_audience_values(
    value: object, *, allowed_values: list[str]
) -> list[str] | None:
    if not allowed_values:
        return None
    terms = {
        clean_text(item).casefold(): [clean_text(item).casefold()]
        for item in allowed_values
        if clean_text(item)
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for item in split_values(string_list(value, max_items=10, max_chars=60)):
        canonical = normalize_from_terms([item], terms)
        if not canonical:
            continue
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(canonical)
    return normalized or None


def category_attribute_values(
    category_path: str | None,
    attribute_handle: str,
) -> list[str]:
    normalized_handle = str(attribute_handle or "").replace("-", "_")
    if not category_path:
        return []
    category_handles = set(category_attribute_handles(category_path))
    if normalized_handle not in category_handles:
        return []
    repository = load_attribute_repository()
    attributes_by_handle = object_dict(repository.get("attributes_by_handle"))
    attribute = object_dict(attributes_by_handle.get(normalized_handle))
    return [
        clean_text(item)
        for item in object_list(attribute.get("values"))
        if clean_text(item)
    ]


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
        if product_attribute_value(data, attribute) in (None, "", [], {}):
            missing.append(attribute)
        else:
            present.append(attribute)
    return {
        "present_attributes": present,
        "null_attributes": missing,
        "required_attributes": required,
        "recommended_attributes": recommended,
    }


def product_attribute_value(data: dict[str, object], attribute: str) -> object | None:
    keys = attribute_lookup_keys(attribute)
    return first_present(data, *keys)


def category_attribute_handles(category_path: str | None) -> list[str]:
    return shopify_category_attribute_handles(category_path, load_taxonomy_index())


def candidate_values(data: dict[str, object], *keys: str) -> list[object]:
    values: list[object] = []
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            values.extend(flatten_dict_values(value))
        elif isinstance(value, list):
            values.extend(flatten_list_values(value))
        else:
            values.append(value)
    return values


def targeted_candidate_values(
    data: dict[str, object], target_keys: Collection[str], *keys: str
) -> list[object]:
    normalized_targets = {str(key).casefold() for key in target_keys}
    values: list[object] = []
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            values.extend(flatten_targeted_dict_values(value, normalized_targets))
        elif isinstance(value, list):
            values.extend(flatten_targeted_list_values(value, normalized_targets))
        else:
            values.append(value)
    return values


def flatten_dict_values(
    value: dict[str, object], max_depth: int | None = None
) -> list[object]:
    if max_depth is None:
        max_depth = data_enrichment_settings.candidate_flatten_max_depth
    if max_depth <= 0:
        return []
    values: list[object] = []
    for item in value.values():
        if isinstance(item, dict):
            values.extend(flatten_dict_values(item, max_depth - 1))
        elif isinstance(item, list):
            values.extend(flatten_list_values(item, max_depth - 1))
        else:
            values.append(item)
    return values


def flatten_list_values(
    value: list[object], max_depth: int | None = None
) -> list[object]:
    if max_depth is None:
        max_depth = data_enrichment_settings.candidate_flatten_max_depth
    if max_depth <= 0:
        return []
    values: list[object] = []
    for item in value:
        if isinstance(item, dict):
            values.extend(flatten_dict_values(item, max_depth - 1))
        elif isinstance(item, list):
            values.extend(flatten_list_values(item, max_depth - 1))
        else:
            values.append(item)
    return values


def flatten_targeted_dict_values(
    value: dict[str, object],
    target_keys: set[str],
    max_depth: int | None = None,
) -> list[object]:
    if max_depth is None:
        max_depth = data_enrichment_settings.candidate_flatten_max_depth
    if max_depth <= 0:
        return []
    values: list[object] = []
    for key, item in value.items():
        if str(key).casefold() in target_keys and item not in (None, "", [], {}):
            if isinstance(item, dict):
                values.extend(flatten_dict_values(item, max_depth - 1))
            elif isinstance(item, list):
                values.extend(flatten_list_values(item, max_depth - 1))
            else:
                values.append(item)
            continue
        if isinstance(item, dict):
            values.extend(
                flatten_targeted_dict_values(item, target_keys, max_depth - 1)
            )
        elif isinstance(item, list):
            values.extend(
                flatten_targeted_list_values(item, target_keys, max_depth - 1)
            )
    return values


def flatten_targeted_list_values(
    value: list[object],
    target_keys: set[str],
    max_depth: int | None = None,
) -> list[object]:
    if max_depth is None:
        max_depth = data_enrichment_settings.candidate_flatten_max_depth
    if max_depth <= 0:
        return []
    values: list[object] = []
    for item in value:
        if isinstance(item, dict):
            values.extend(
                flatten_targeted_dict_values(item, target_keys, max_depth - 1)
            )
        elif isinstance(item, list):
            values.extend(
                flatten_targeted_list_values(item, target_keys, max_depth - 1)
            )
    return values


def split_values(values: list[object]) -> list[str]:
    rows: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        rows.extend(
            clean_text(part) for part in re.split(r"[,/|]", text) if clean_text(part)
        )
    return rows


def tokens(value: object) -> list[str]:
    return [
        token
        for token in token_re.findall(clean_text(strip_html_tags(value)).casefold())
        if token
    ]


def keyword_tokens(value: object, stopwords: set[str]) -> list[str]:
    return [
        token for token in tokens(value) if len(token) >= 3 and token not in stopwords
    ]


def term_present(text: str, term: object) -> bool:
    normalized = clean_text(term).casefold()
    if not normalized:
        return False
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text)
        is not None
    )


def decimal_text(value: object) -> Decimal | None:
    normalized = normalize_decimal_price(value)
    if normalized is None:
        normalized = normalize_decimal_price(value, interpret_integral_as_cents=False)
    if normalized is None:
        return None
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def first_present(data: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def without_empty(value: dict[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def object_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def string_list(value: object, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_text(item)[:max_chars]
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


@lru_cache(maxsize=1)
def load_attribute_repository() -> dict[str, object]:
    return load_attribute_repository_data(data_enrichment_settings.attributes_path)


@lru_cache(maxsize=1)
def load_taxonomy_index():
    return load_shopify_taxonomy_index(data_enrichment_settings.taxonomy_path)
