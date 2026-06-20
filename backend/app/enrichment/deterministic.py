from __future__ import annotations

import logging
import re
from collections.abc import Collection, Sequence
from decimal import Decimal, InvalidOperation
from functools import lru_cache, partial
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
    DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS,
    DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS,
    DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE,
    DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS,
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
    attribute_lookup_keys,
    load_attribute_repository_data,
    load_taxonomy_index as load_shopify_taxonomy_index,
    repository_terms,
    term_dict,
    top_taxonomy_candidates as shopify_top_taxonomy_candidates,
)
from app.core.shared.regex_patterns import compile_regex_patterns
from app.core.shared.currency_hints import currency_hint_from_page_url
from app.core.records.normalizers import normalize_decimal_price
from app.core.shared.field_coerce import (
    clean_text,
    extract_currency_code,
    strip_html_tags,
    text_or_none,
)
from app.core.shared.coerce_primitives import object_dict, object_list


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
    if url_context := category_url_context(data.get("url") or source_url):
        attribute_data["url_category_context"] = url_context
    price_normalized = normalize_price(data, source_url=source_url)
    repository = load_attribute_repository()
    terms = repository_terms(repository)
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
        term_dict(terms, "color_families"),
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


def normalize_price(data: dict[str, object], *, source_url: str) -> dict[str, object] | None:
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
    original_amount = decimal_text(first_present(data, *DATA_ENRICHMENT_PRICE_ORIGINAL_FIELDS))
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
    size_config = term_dict(terms, "size_systems")
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
        else False
    )
    size_context = has_size_context(data)
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
            require_strong=not (category_supports_size or size_context),
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
    return any(term_present(context, term) for term in DATA_ENRICHMENT_SIZE_CONTEXT_TERMS)


def normalize_materials(data: dict[str, object], *, terms: dict[str, object]) -> list[str] | None:
    material_terms = term_dict(terms, "material_terms")
    found: list[str] = []
    seen: set[str] = set()
    values = candidate_values(data, *DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS)
    fallback_values = candidate_values(data, *DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS)
    for value in values:
        lowered = clean_text(strip_html_tags(value)).casefold()
        collect_material_matches(lowered, material_terms, found, seen)
    for value in fallback_values:
        lowered = clean_text(strip_html_tags(value)).casefold()
        collect_material_percentage_matches(lowered, material_terms, found, seen)
        collect_material_matches(
            strip_material_context_noise(lowered), material_terms, found, seen
        )
    return found or None


def collect_material_matches(
    text: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    collect_material_percentage_matches(text, material_terms, found, seen)
    for canonical, tokens in material_terms.items():
        if canonical in seen:
            continue
        if isinstance(tokens, list) and any(term_present(text, token) for token in tokens):
            found.append(str(canonical))
            seen.add(str(canonical))


def collect_material_percentage_matches(
    text: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    for material in percentage_material_parse(text):
        add_material_match(material, material_terms, found, seen)


def percentage_material_parse(text: str) -> list[str]:
    materials: list[str] = []
    material_token = r"[a-z]+(?:-[a-z]+)?"  # nosec B105
    material_phrase = rf"{material_token}(?:\s+{material_token}){{0,4}}"
    patterns = (
        DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE,
        rf"\b(?P<material>{material_phrase})\s*(?P<percent>\d{{1,3}}(?:\.\d+)?)\s*(?:%|percent)\b",
        rf"\b(?P<percent>\d{{1,3}}(?:\.\d+)?)\s*percent\s*(?P<material>{material_phrase})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            if material := clean_percentage_material(match.group("material")):
                materials.append(material)
    return materials


def clean_percentage_material(value: object) -> str:
    material = clean_text(value).casefold()
    material = re.sub(r"^(?:and|or|with|of|made\s+with|made\s+of)\s+", "", material)
    material = re.sub(r"^.*\b(?:with|of|contains|composition|fabric)\s+", "", material)
    material = re.split(r"\b(?:and|or|plus)\b|[,.;:/()]", material, maxsplit=1)[0]
    return clean_text(material)


def add_material_match(
    value: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    normalized = clean_text(value).casefold()
    for canonical, tokens in material_terms.items():
        if canonical in seen:
            continue
        if normalized == str(canonical).casefold() or (
            isinstance(tokens, list)
            and any(term_present(normalized, token) for token in tokens)
        ):
            found.append(str(canonical))
            seen.add(str(canonical))
            return


@lru_cache(maxsize=1)
def compiled_material_strip_patterns() -> tuple[re.Pattern[str], ...]:
    return compile_regex_patterns(
        tuple(DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS or ()),
        logger=logger,
        warning_message="Skipping invalid material strip pattern: %r",
        skip_blank=False,
    )


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
            segment.strip().casefold()
            for segment in path.split("/")
            if segment.strip()
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
    except (ValueError, UnicodeError, re.error):
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
    return list(dict.fromkeys(
        clean_text(f"{first} {second}").casefold()
        for first, second in zip(tokens, tokens[1:], strict=False)
        if first in unigrams and second in unigrams
    ))


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
def candidate_values(data: dict[str, object], *keys: str) -> list[object]:
    return _candidate_values(data, keys)


def targeted_candidate_values(
    data: dict[str, object], target_keys: Collection[str], *keys: str
) -> list[object]:
    return _candidate_values(data, keys, {str(key).casefold() for key in target_keys})


def _candidate_values(
    data: dict[str, object], keys: Sequence[str], target_keys: set[str] | None = None
) -> list[object]:
    values: list[object] = []
    for key in keys:
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            values.extend(_flatten_values(value, target_keys=target_keys))
        else:
            values.append(value)
    return values


def flatten_values(value: object, max_depth: int | None = None) -> list[object]:
    return _flatten_values(value, max_depth=max_depth)


def flatten_targeted_values(
    value: object,
    target_keys: set[str],
    max_depth: int | None = None,
) -> list[object]:
    return _flatten_values(value, max_depth=max_depth, target_keys=target_keys)


def _flatten_values(
    value: object,
    *,
    max_depth: int | None = None,
    target_keys: set[str] | None = None,
) -> list[object]:
    if max_depth is None:
        max_depth = data_enrichment_settings.candidate_flatten_max_depth
    if max_depth <= 0:
        return []
    values: list[object] = []
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, item in items:
        if target_keys is not None and str(key).casefold() in target_keys:
            if item not in (None, "", [], {}):
                values.extend(
                    _flatten_values(item, max_depth=max_depth - 1)
                    if isinstance(item, (dict, list))
                    else [item]
                )
            continue
        if isinstance(item, (dict, list)):
            values.extend(_flatten_values(
                item, max_depth=max_depth - 1, target_keys=target_keys
            ))
        elif target_keys is None:
            values.append(item)
    return values


def split_values(values: list[object]) -> list[str]:
    return [
        cleaned
        for value in values
        if (text := clean_text(value))
        for part in re.split(r"[,/|;·]", text)
        if (cleaned := clean_text(part))
    ]


def tokens(value: object) -> list[str]:
    return token_re.findall(clean_text(strip_html_tags(value)).casefold())


def keyword_tokens(value: object, stopwords: set[str]) -> list[str]:
    return [token for token in tokens(value) if len(token) >= 3 and token not in stopwords]


def term_present(text: str, term: object) -> bool:
    normalized = clean_text(term).casefold()
    return bool(normalized) and (
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


load_attribute_repository = partial(load_attribute_repository_data, data_enrichment_settings.attributes_path)
load_taxonomy_index = partial(load_shopify_taxonomy_index, data_enrichment_settings.taxonomy_path)
