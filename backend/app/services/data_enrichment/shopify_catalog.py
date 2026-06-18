from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_AUDIENCE_ALIASES,
    DATA_ENRICHMENT_AVAILABILITY_TERMS,
    DATA_ENRICHMENT_COLOR_FAMILY_ALIASES,
    DATA_ENRICHMENT_GENDER_ALIASES,
    DATA_ENRICHMENT_SEO_STOPWORDS,
    DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS,
    DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES,
    DATA_ENRICHMENT_TAXONOMY_ACCESSORY_EVIDENCE_TERMS,
    DATA_ENRICHMENT_TAXONOMY_ACCESSORY_PATH_TERMS,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS,
    DATA_ENRICHMENT_TAXONOMY_GAME_EVIDENCE_TERMS,
    DATA_ENRICHMENT_TAXONOMY_SPECIFIC_SPORT_TERMS,
    DATA_ENRICHMENT_TAXONOMY_SPORT_EVIDENCE_TERMS,
    DATA_ENRICHMENT_TAXONOMY_TOY_EVIDENCE_TERMS,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
)
from app.services.shared.field_coerce import clean_text, strip_html_tags

_token_re = re.compile(r"[a-z0-9]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaxonomyIndex:
    version: str
    categories: tuple[dict[str, object], ...]
    exact_lookup: dict[str, dict[str, object]]
    leaf_lookup: dict[str, tuple[dict[str, object], ...]]
    path_phrase_lookup: dict[str, tuple[dict[str, object], ...]]
    id_lookup: dict[str, dict[str, object]]


def normalize_category_path(value: object) -> str:
    return " > ".join(
        " ".join(tokenize_text(part))
        for part in clean_text(value).split(">")
        if tokenize_text(part)
    )


def tokenize_text(value: object) -> list[str]:
    return [
        normalized
        for token in _token_re.findall(clean_text(strip_html_tags(value)).casefold())
        if token != "s" and (normalized := normalize_taxonomy_token(token))  # nosec B105
    ]


def normalize_taxonomy_token(value: object) -> str:
    """Normalize taxonomy match tokens.

    Rules: preserve one-letter size tokens, map handbag leaves to Shopify bag
    wording, singularize common English plurals, and leave other tokens intact.
    """
    token = str(value or "").strip().casefold()
    if token in {"handbag", "handbags"}:
        return "bag"
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 4 and token.endswith(("xes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def object_iterable(value: object) -> list[object]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return list(value)
    return []


def string_iterable(value: object) -> list[str]:
    return [str(item).strip() for item in object_iterable(value) if str(item).strip()]


def repository_terms(repository: dict[str, object]) -> dict[str, object]:
    terms = repository.get("normalization_terms")
    return dict(terms) if isinstance(terms, dict) else {}


def term_dict(terms: dict[str, object], key: str) -> dict[str, object]:
    value = terms.get(key)
    return dict(value) if isinstance(value, dict) else {}


def attribute_lookup_keys(attribute: str) -> tuple[str, ...]:
    normalized = str(attribute or "").strip().replace("-", "_")
    explicit = DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS.get(normalized)
    if explicit:
        return tuple(str(item) for item in explicit)
    variants = [normalized]
    if normalized.endswith("_type"):
        variants.append(normalized[:-5])
    if normalized.startswith("target_"):
        variants.append(normalized.replace("target_", "", 1))
    return tuple(dict.fromkeys(item for item in variants if item))


def category_attribute_handles(
    category_path: str | None, taxonomy_index: TaxonomyIndex
) -> list[str]:
    if not category_path:
        return []
    reference = taxonomy_reference_for_category_path(category_path, taxonomy_index)
    if not reference:
        return []
    return [
        str(item)
        for item in object_list(reference.get("attribute_handles"))
        if str(item or "").strip()
    ]


def exact_category_match(
    values: list[object],
    taxonomy_index: TaxonomyIndex,
    scores: tuple[float, float],
) -> dict[str, object] | None:
    for value in values:
        normalized = normalize_category_path(clean_text(value))
        if normalized in taxonomy_index.exact_lookup:
            return category_match_payload(
                taxonomy_index.exact_lookup[normalized],
                score=scores[0],
                source="exact_path",
            )
        if not normalized:
            continue
        leaf_matches = list(taxonomy_index.leaf_lookup.get(normalized) or ())
        if len(leaf_matches) == 1:
            return category_match_payload(
                leaf_matches[0],
                score=scores[1],
                source="leaf",
            )
    return None


def top_taxonomy_candidates(
    data: dict[str, object],
    taxonomy_index: TaxonomyIndex,
    *,
    category_match_threshold: float,
    limit: int,
    candidate_values: list[object],
    candidate_value_loader,
) -> list[dict[str, object]]:
    all_source_tokens = set()
    for value in candidate_values:
        all_source_tokens.update(tokenize_text(value))
    exact_match = exact_category_match(candidate_values, taxonomy_index, (1.0, 0.92))
    if exact_match:
        if exact_match.get("source") == "exact_path":
            return [exact_match]
        if not taxonomy_candidate_conflicts(
            all_source_tokens,
            exact_match.get("category_path"),
        ):
            return [exact_match]
    phrase_match = phrase_leaf_category_match(candidate_values, taxonomy_index)

    primary_tokens = pool_tokens(data, candidate_value_loader, "category", "product_type")
    secondary_tokens = pool_tokens(data, candidate_value_loader, "title")
    tertiary_tokens = pool_tokens(
        data,
        candidate_value_loader,
        "brand",
        "materials",
        "material",
        "tags",
        "product_attributes",
        "specifications",
        "url_category_context",
    )
    if not primary_tokens and not secondary_tokens and not tertiary_tokens:
        return [phrase_match] if phrase_match else []

    scored: list[dict[str, object]] = []
    if phrase_match:
        scored.append(phrase_match)
    for item in taxonomy_index.categories:
        category_tokens = set(
            string_iterable(item.get("path_match_tokens"))
            or tokenize_text(item.get("category_path"))
        )
        attribute_tokens = set(string_iterable(item.get("attribute_match_tokens"))) - category_tokens
        if not category_tokens:
            continue
        if taxonomy_candidate_conflicts(
            primary_tokens | secondary_tokens | tertiary_tokens,
            item.get("category_path"),
            product_tokens=primary_tokens | secondary_tokens,
        ):
            continue
        primary_score = weighted_overlap(primary_tokens, category_tokens)
        if primary_score and not has_product_kind_overlap(primary_tokens, category_tokens):
            continue
        secondary_score = weighted_overlap(secondary_tokens, category_tokens)
        tertiary_score = weighted_overlap(tertiary_tokens, category_tokens)
        category_evidence_score = weighted_overlap(
            category_tokens,
            primary_tokens | secondary_tokens | tertiary_tokens,
        )
        attribute_score = weighted_overlap(
            primary_tokens | secondary_tokens | tertiary_tokens,
            attribute_tokens,
        )
        primary_attribute_score = weighted_product_overlap(
            primary_tokens,
            attribute_tokens,
        )
        score = (
            primary_score
            + (secondary_score * 0.35)
            + (tertiary_score * 0.15)
            + (category_evidence_score * 0.4)
            + (attribute_score * 0.3)
            + (primary_attribute_score * 0.5)
        )
        evidence_tokens = (
            primary_tokens | secondary_tokens | tertiary_tokens
        ) & category_tokens
        enough_sparse_evidence = len(
            evidence_tokens - DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS
        ) >= 2
        if (
            primary_score == 0
            and primary_attribute_score == 0
            and not enough_sparse_evidence
            and score > 0
        ):
            score *= 0.6
        if score < category_match_threshold:
            continue
        scored.append(
            category_match_payload(
                item,
                score=round(score, 3),
                source="scored_match",
            )
        )
    if not scored:
        token_match = leaf_token_category_match(
            candidate_values,
            taxonomy_index,
            eligible_tokens=primary_tokens | secondary_tokens,
        )
        return [token_match] if token_match else []
    scored.sort(
        key=lambda item: (
            -score_float(item.get("score")),
            len(str(item.get("category_path") or "")),
            str(item.get("category_path") or ""),
        )
    )
    return scored[:limit]


def phrase_leaf_category_match(
    values: list[object],
    taxonomy_index: TaxonomyIndex,
) -> dict[str, object] | None:
    source_tokens = set()
    for value in values:
        source_tokens.update(tokenize_text(value))
    candidates: list[tuple[int, int, str, dict[str, object]]] = []
    for value in values:
        value_tokens = tokenize_text(value)
        if len(value_tokens) < 2:
            continue
        for phrase in taxonomy_phrases(value_tokens):
            phrase_size = len(tokenize_text(phrase))
            leaf_matches = list(taxonomy_index.leaf_lookup.get(phrase) or ())
            leaf_matches = [
                item
                for item in leaf_matches
                if not taxonomy_candidate_conflicts(source_tokens, item.get("category_path"))
            ]
            for item in leaf_matches:
                candidates.append(
                    (
                        phrase_size,
                        category_depth(item.get("category_path")),
                        str(item.get("category_path") or ""),
                        item,
                    )
                )
    if candidates:
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return category_match_payload(candidates[0][3], score=1.3, source="leaf_phrase")
    for value in values:
        value_tokens = tokenize_text(value)
        if len(value_tokens) < 2:
            continue
        for phrase in taxonomy_phrases(value_tokens):
            path_match = phrase_path_category_match(
                phrase,
                taxonomy_index,
                source_tokens=source_tokens,
            )
            if path_match:
                return path_match
    return None


def phrase_path_category_match(
    phrase: str,
    taxonomy_index: TaxonomyIndex,
    *,
    source_tokens: set[str],
) -> dict[str, object] | None:
    phrase_tokens = set(tokenize_text(phrase))
    if len(phrase_tokens) < 2:
        return None
    if phrase_tokens <= DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
        return None
    matches = [
        item
        for item in taxonomy_index.path_phrase_lookup.get(phrase, ())
        if not taxonomy_candidate_conflicts(source_tokens, item.get("category_path"))
    ]
    if not matches:
        # Fallback: build leaf token sets via clean_text/tokenize_text, then keep
        # paths whose normalized path tokens cover the phrase, share a leaf token,
        # and do not conflict; the post-filter prefers non-accessory paths.
        leaf_tokens_by_path = {
            str(item.get("category_path") or ""): set(
                tokenize_text(item.get("leaf") or clean_text(item.get("category_path")).split(">")[-1])
            )
            for item in taxonomy_index.categories
        }
        matches = [
            item
            for item in taxonomy_index.categories
            if phrase_tokens <= normalized_token_set(
                string_iterable(item.get("path_match_tokens"))
            )
            and bool(phrase_tokens & leaf_tokens_by_path[str(item.get("category_path") or "")])
            and not taxonomy_candidate_conflicts(source_tokens, item.get("category_path"))
        ]
    non_accessory_matches = [
        item for item in matches if not taxonomy_accessory_path(clean_text(item.get("category_path")).casefold())
    ]
    if non_accessory_matches:
        matches = non_accessory_matches
    if not matches:
        return None
    matches.sort(
        key=lambda item: (
            category_depth(item.get("category_path")),
            str(item.get("category_path") or ""),
        )
    )
    return category_match_payload(matches[0], score=0.87, source="path_phrase")


def taxonomy_phrases(tokens: list[str]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    max_width = min(5, len(tokens))
    for width in range(max_width, 1, -1):
        for index in range(len(tokens) - width + 1):
            phrase = " ".join(tokens[index : index + width])
            if phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
    return phrases


def leaf_token_category_match(
    values: list[object],
    taxonomy_index: TaxonomyIndex,
    *,
    eligible_tokens: set[str],
) -> dict[str, object] | None:
    token_counts: dict[str, int] = {}
    source_tokens: set[str] = set()
    for value in values:
        for token in tokenize_text(value):
            if token in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
                continue
            token_counts[token] = token_counts.get(token, 0) + 1
            source_tokens.add(token)
    candidates: list[tuple[int, str, dict[str, object]]] = []
    for token, count in token_counts.items():
        if count < 2 or token not in eligible_tokens:
            continue
        leaf_matches = list(taxonomy_index.leaf_lookup.get(token) or ())
        leaf_matches = [
            item
            for item in leaf_matches
            if not taxonomy_candidate_conflicts(source_tokens, item.get("category_path"))
        ]
        if len(leaf_matches) != 1:
            continue
        candidates.append(
            (
                category_depth(leaf_matches[0].get("category_path")),
                str(leaf_matches[0].get("category_path") or ""),
                leaf_matches[0],
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return category_match_payload(candidates[0][2], score=0.84, source="leaf_token")


def score_float(value: object) -> float:
    try:
        parsed = float(str(value)) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(parsed) or math.isinf(parsed):
        return 0.0
    return parsed


def taxonomy_context_conflicts(source_tokens: set[str], category_path: object) -> bool:
    if not source_tokens:
        return False
    path_text = clean_text(category_path).casefold()
    if not path_text:
        return False
    for block in tuple(DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS or ()):
        if not isinstance(block, dict):
            continue
        context_terms = tuple(
            str(item).casefold() for item in object_list(block.get("context_terms"))
        )
        path_terms = tuple(
            str(item).casefold() for item in object_list(block.get("path_terms"))
        )
        if not context_terms or not path_terms:
            continue
        if not any(
            tokens <= source_tokens
            for term in context_terms
            if (tokens := set(tokenize_text(term)))
        ):
            continue
        if any(term in path_text for term in path_terms):
            return True
    return False


def taxonomy_candidate_conflicts(
    source_tokens: set[str],
    category_path: object,
    *,
    product_tokens: set[str] | None = None,
) -> bool:
    path_text = clean_text(category_path).casefold()
    path_tokens = normalized_token_set(tokenize_text(path_text))
    evidence_tokens = product_tokens if product_tokens is not None else source_tokens
    return any(
        (
            taxonomy_context_conflicts(source_tokens, category_path),
            accessory_path_conflict(path_text, evidence_tokens),
            toys_vs_sports_conflict(path_text, source_tokens),
            sport_specific_conflict(source_tokens, path_tokens),
            special_token_conflict(source_tokens, path_tokens),
        )
    )


def normalized_token_set(values: Iterable[object]) -> set[str]:
    return {
        token
        for value in values
        if (token := normalize_taxonomy_token(value))
    }


def accessory_path_conflict(path_text: str, evidence_tokens: set[str]) -> bool:
    accessory_terms = normalized_token_set(
        DATA_ENRICHMENT_TAXONOMY_ACCESSORY_EVIDENCE_TERMS
    )
    return taxonomy_accessory_path(path_text) and not evidence_tokens & accessory_terms


def toys_vs_sports_conflict(path_text: str, source_tokens: set[str]) -> bool:
    sport_or_game_terms = normalized_token_set(
        DATA_ENRICHMENT_TAXONOMY_SPORT_EVIDENCE_TERMS
    ) | normalized_token_set(DATA_ENRICHMENT_TAXONOMY_GAME_EVIDENCE_TERMS)
    toy_terms = normalized_token_set(DATA_ENRICHMENT_TAXONOMY_TOY_EVIDENCE_TERMS)
    return (
        "toys & games" in path_text
        and bool(source_tokens & sport_or_game_terms)
        and not source_tokens & toy_terms
    )


def sport_specific_conflict(source_tokens: set[str], path_tokens: set[str]) -> bool:
    sport_terms = normalized_token_set(DATA_ENRICHMENT_TAXONOMY_SPECIFIC_SPORT_TERMS)
    source_sports = source_tokens & sport_terms
    path_sports = path_tokens & sport_terms
    return bool(source_sports and path_sports and not source_sports & path_sports)


def special_token_conflict(source_tokens: set[str], path_tokens: set[str]) -> bool:
    if "ball" in source_tokens and "ball" not in path_tokens:
        return True
    lego_terms = {"lego", "minifigure"}
    return bool(
        lego_terms & source_tokens
        and {"mature", "weapon", "star", "planet"} & path_tokens
    )


def taxonomy_accessory_path(path_text: str) -> bool:
    if path_text.startswith("apparel & accessories > clothing accessories"):
        return False
    if "handbags, wallets & cases" in path_text:
        return False
    parts = [part.strip() for part in path_text.split(">") if part.strip()]
    if not parts:
        return False
    scoped_path = " > ".join(parts[1:])
    if not scoped_path:
        return False
    scoped_tokens = set(tokenize_text(scoped_path))
    return any(
        term_tokens <= scoped_tokens
        for term in DATA_ENRICHMENT_TAXONOMY_ACCESSORY_PATH_TERMS
        if (term_tokens := set(tokenize_text(term)))
    )


def category_depth(category_path: object) -> int:
    return len([part for part in clean_text(category_path).split(">") if part.strip()])


def taxonomy_reference_for_category_path(
    category_path: str, taxonomy_index: TaxonomyIndex
) -> dict[str, object] | None:
    match = exact_category_match([category_path], taxonomy_index, (1.0, 0.92))
    if not match:
        return None
    return taxonomy_reference_payload(
        taxonomy_index.id_lookup.get(str(match.get("category_id") or ""), {})
    )


@lru_cache(maxsize=16)
def load_attribute_repository_data(path: Path) -> dict[str, object]:
    raw = load_json_dict(path)
    raw_attributes = [
        item for item in object_list(raw.get("attributes")) if isinstance(item, dict)
    ]
    attribute_lookup = {
        str(item.get("handle") or "").replace("-", "_"): {
            "name": str(item.get("name") or ""),
            "handle": str(item.get("handle") or ""),
            "values": [
                str(value.get("name") or "")
                for value in object_list(item.get("values"))
                if isinstance(value, dict) and str(value.get("name") or "").strip()
            ],
        }
        for item in raw_attributes
        if str(item.get("handle") or "").strip()
    }
    color_attribute = merged_attribute_by_name(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["color"],
    )
    color_families = shopify_color_family_terms(color_attribute, raw_attributes)
    size_attribute = attribute_by_name(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["size"],
    )
    audience_attribute = attribute_by_name(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["audience"],
    )
    size_systems = shopify_size_systems(size_attribute)
    # Audience falls back only to audience-specific aliases; gender terms stay separate.
    audience_terms = shopify_attribute_terms(audience_attribute) or {
        key: list(values)
        for key, values in DATA_ENRICHMENT_AUDIENCE_ALIASES.items()
    }
    material_terms = shopify_material_terms(
        raw_attributes,
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["fabric"],
        DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES["material"],
    )
    return {
        "version": str(raw.get("version") or ""),
        "normalization_terms": {
            "availability_terms": {
                key: list(values)
                for key, values in DATA_ENRICHMENT_AVAILABILITY_TERMS.items()
            },
            "audience_terms": audience_terms,
            "color_families": color_families,
            "gender_terms": {
                key: list(values)
                for key, values in DATA_ENRICHMENT_GENDER_ALIASES.items()
            },
            "material_terms": material_terms,
            "seo_stopwords": list(DATA_ENRICHMENT_SEO_STOPWORDS),
            "size_systems": size_systems,
        },
        "attributes_by_handle": attribute_lookup,
    }


@lru_cache(maxsize=16)
def load_taxonomy_index(path: Path) -> TaxonomyIndex:
    raw = load_json_dict(path)
    rows: list[dict[str, object]] = []
    exact_lookup: dict[str, dict[str, object]] = {}
    leaf_lookup: dict[str, list[dict[str, object]]] = {}
    path_phrase_lookup: dict[str, list[dict[str, object]]] = {}
    id_lookup: dict[str, dict[str, object]] = {}
    for vertical in object_list(raw.get("verticals")):
        if not isinstance(vertical, dict):
            continue
        for category in object_list(vertical.get("categories")):
            if not isinstance(category, dict):
                continue
            category_id = str(category.get("id") or "").strip()
            category_path = clean_text(category.get("full_name"))
            normalized_path = normalize_category_path(category_path)
            leaf = normalize_category_path(category.get("name"))
            if not category_id or not category_path or not normalized_path:
                continue
            row: dict[str, Any] = {
                "category_id": category_id,
                "category_path": category_path,
                "normalized_path": normalized_path,
                "leaf": leaf,
                "attribute_handles": [
                    str(item.get("handle") or "").replace("-", "_")
                    for item in object_list(category.get("attributes"))
                    if isinstance(item, dict) and str(item.get("handle") or "").strip()
                ],
            }
            row["path_match_tokens"] = set(tokenize_text(row["category_path"]))
            row["attribute_match_tokens"] = category_attribute_match_tokens(row)
            rows.append(row)
            exact_lookup[normalized_path] = row
            if leaf:
                leaf_lookup.setdefault(leaf, []).append(row)
            for phrase in taxonomy_path_lookup_phrases(row):
                path_phrase_lookup.setdefault(phrase, []).append(row)
            id_lookup[category_id] = row
    return TaxonomyIndex(
        version=str(raw.get("version") or ""),
        categories=tuple(rows),
        exact_lookup=exact_lookup,
        leaf_lookup={key: tuple(value) for key, value in leaf_lookup.items()},
        path_phrase_lookup={key: tuple(value) for key, value in path_phrase_lookup.items()},
        id_lookup=id_lookup,
    )


def taxonomy_path_lookup_phrases(item: dict[str, object]) -> list[str]:
    phrases = taxonomy_phrases(tokenize_text(item.get("normalized_path")))
    parts = [part for part in clean_text(item.get("category_path")).split(">") if part.strip()]
    if len(parts) < 2:
        return phrases
    root_tokens = tokenize_text(parts[0])
    leaf_tokens = tokenize_text(parts[-1])
    for root_token in root_tokens:
        if root_token in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
            continue
        for leaf_token in leaf_tokens:
            if leaf_token in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
                continue
            phrases.append(f"{leaf_token} {root_token}")
            phrases.append(f"{root_token} {leaf_token}")
    return list(dict.fromkeys(phrases))


def attribute_by_name(
    attributes: list[dict[str, object]], name: str
) -> dict[str, object]:
    normalized_name = str(name or "").strip().casefold()
    for item in attributes:
        if str(item.get("name") or "").strip().casefold() == normalized_name:
            values = [
                str(value.get("name") or "")
                for value in object_list(item.get("values"))
                if isinstance(value, dict) and str(value.get("name") or "").strip()
            ]
            return {
                "name": str(item.get("name") or ""),
                "handle": str(item.get("handle") or ""),
                "values": values,
            }
    return {}


def merged_attribute_by_name(
    attributes: list[dict[str, object]], name: str
) -> dict[str, object]:
    normalized_name = str(name or "").strip().casefold()
    values: list[str] = []
    seen: set[str] = set()
    handle = ""
    for item in attributes:
        if str(item.get("name") or "").strip().casefold() != normalized_name:
            continue
        if not handle:
            handle = str(item.get("handle") or "")
        for value in object_list(item.get("values")):
            if not isinstance(value, dict):
                continue
            cleaned = str(value.get("name") or "").strip()
            if cleaned and cleaned.casefold() not in seen:
                seen.add(cleaned.casefold())
                values.append(cleaned)
    if not values:
        return {}
    return {"name": str(name or ""), "handle": handle, "values": values}


def shopify_material_terms(
    attributes: list[dict[str, object]], *names: str
) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name in names:
        attribute = attribute_by_name(attributes, name)
        for value in object_list(attribute.get("values")):
            cleaned = clean_text(value).casefold()
            if cleaned:
                values.setdefault(cleaned, [cleaned])
    return values


def shopify_attribute_terms(attribute: dict[str, object]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for value in object_list(attribute.get("values")):
        cleaned = clean_text(value).casefold()
        if cleaned:
            values[cleaned] = [cleaned]
    return values


def shopify_color_family_terms(
    attribute: dict[str, object],
    attributes: list[dict[str, object]],
) -> dict[str, list[str]]:
    source_values = set(shopify_attribute_terms(attribute).keys())
    for item in attributes:
        for value in object_list(item.get("values")):
            if isinstance(value, dict) and clean_text(value.get("name")):
                source_values.add(clean_text(value.get("name")).casefold())
    if not source_values:
        return {}
    terms: dict[str, list[str]] = {}
    for canonical, aliases in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES.items():
        allowed = [alias for alias in aliases if clean_text(alias).casefold() in source_values]
        if clean_text(canonical).casefold() in source_values and canonical not in allowed:
            allowed.insert(0, canonical)
        if allowed:
            terms[canonical] = list(dict.fromkeys(allowed))
    return terms


def shopify_size_systems(attribute: dict[str, object]) -> dict[str, object]:
    aliases: dict[str, str] = {}
    alpha_values: set[str] = set()
    numeric_values: set[str] = set()
    for value in object_list(attribute.get("values")):
        cleaned = clean_text(value)
        if not cleaned:
            continue
        match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", cleaned)
        canonical = match.group(1).upper() if match else ""
        if canonical:
            aliases[cleaned.casefold()] = canonical
            base_name = clean_text(re.sub(r"\s*\([A-Za-z0-9]+\)\s*$", "", cleaned))
            if base_name:
                aliases[base_name.casefold()] = canonical
            if re.fullmatch(r"[A-Z]{1,4}|\d+XL", canonical):
                alpha_values.add(canonical.casefold())
            elif canonical.isdigit():
                numeric_values.add(canonical.casefold())
        if cleaned.casefold() == "one size":
            aliases[cleaned.casefold()] = "OS"
            alpha_values.add("os")
        if cleaned.isdigit():
            numeric_values.add(cleaned.casefold())
    return {
        "aliases": aliases,
        "systems": {
            "alpha": sorted(alpha_values),
            "numeric": sorted(numeric_values),
        },
    }


def category_match_payload(
    item: dict[str, object], *, score: float, source: str
) -> dict[str, object]:
    return {
        "category_id": item.get("category_id") or "",
        "category_path": item.get("category_path") or "",
        "score": round(float(score), 3),
        "source": source,
        "taxonomy_reference": taxonomy_reference_payload(item) or {},
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
    }


def taxonomy_reference_payload(item: dict[str, object]) -> dict[str, object] | None:
    if not item:
        return None
    return {
        "category_id": item.get("category_id") or "",
        "category_path": item.get("category_path") or "",
        "attribute_handles": string_iterable(item.get("attribute_handles")),
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
    }


def pool_tokens(
    data: dict[str, object], candidate_value_loader, *keys: str
) -> set[str]:
    tokens: set[str] = set()
    for key in keys:
        for value in candidate_value_loader(data, key):
            tokens.update(tokenize_text(value))
    return tokens


def category_attribute_match_tokens(item: dict[str, Any]) -> set[str]:
    return set(
        tokenize_text(
            " ".join(
                str(handle)
                for handle in object_iterable(item.get("attribute_handles"))
                if str(handle).strip()
            )
        )
    )


def weighted_overlap(source_tokens: set[str], category_tokens: set[str]) -> float:
    if not source_tokens or not category_tokens:
        return 0.0
    overlap = source_tokens & category_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(source_tokens)


def weighted_product_overlap(source_tokens: set[str], category_tokens: set[str]) -> float:
    product_tokens = {
        token
        for token in source_tokens
        if token not in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS
    }
    return weighted_overlap(product_tokens, category_tokens)


def has_product_kind_overlap(source_tokens: set[str], category_tokens: set[str]) -> bool:
    overlap = source_tokens & category_tokens
    if not overlap:
        return False
    return any(
        token not in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS for token in overlap
    )


def load_json_dict(path: Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Data enrichment JSON must be an object: {path}")
    return payload


def object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []
