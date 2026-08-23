from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from app.core.config.data_enrichment import (
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
from app.core.shared.coerce_primitives import object_list
from app.core.shared.field_coerce import clean_text
from app.enrichment.shopify_repository import (
    TaxonomyIndex,
    normalize_category_path,
    normalize_taxonomy_token,
    string_iterable,
    taxonomy_phrases,
    tokenize_text,
)


@dataclass(frozen=True, slots=True)
class TaxonomyEvidenceTokens:
    primary: set[str]
    secondary: set[str]
    tertiary: set[str]

    @property
    def all(self) -> set[str]:
        return self.primary | self.secondary | self.tertiary


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

    evidence = TaxonomyEvidenceTokens(
        primary=pool_tokens(
            data,
            candidate_value_loader,
            "category",
            "product_type",
        ),
        secondary=pool_tokens(data, candidate_value_loader, "title"),
        tertiary=pool_tokens(
            data,
            candidate_value_loader,
            "brand",
            "materials",
            "material",
            "tags",
            "product_attributes",
            "specifications",
            "url_category_context",
        ),
    )
    if not evidence.all:
        return [phrase_match] if phrase_match else []

    scored = _score_taxonomy_categories(
        taxonomy_index,
        evidence=evidence,
        category_match_threshold=category_match_threshold,
    )
    if phrase_match:
        scored.insert(0, phrase_match)
    if not scored:
        token_match = leaf_token_category_match(
            candidate_values,
            taxonomy_index,
            eligible_tokens=evidence.primary | evidence.secondary,
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


def _score_taxonomy_categories(
    taxonomy_index: TaxonomyIndex,
    *,
    evidence: TaxonomyEvidenceTokens,
    category_match_threshold: float,
) -> list[dict[str, object]]:
    scored: list[dict[str, object]] = []
    for item in taxonomy_index.categories:
        category_tokens = set(
            string_iterable(item.get("path_match_tokens"))
            or tokenize_text(item.get("category_path"))
        )
        attribute_tokens = (
            set(string_iterable(item.get("attribute_match_tokens"))) - category_tokens
        )
        if not category_tokens:
            continue
        if taxonomy_candidate_conflicts(
            evidence.all,
            item.get("category_path"),
            product_tokens=evidence.primary | evidence.secondary,
        ):
            continue
        primary_score = weighted_overlap(evidence.primary, category_tokens)
        if primary_score and not has_product_kind_overlap(
            evidence.primary,
            category_tokens,
        ):
            continue
        secondary_score = weighted_overlap(evidence.secondary, category_tokens)
        tertiary_score = weighted_overlap(evidence.tertiary, category_tokens)
        category_evidence_score = weighted_overlap(
            category_tokens,
            evidence.all,
        )
        attribute_score = weighted_overlap(
            evidence.all,
            attribute_tokens,
        )
        primary_attribute_score = weighted_product_overlap(
            evidence.primary,
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
        evidence_tokens = evidence.all & category_tokens
        enough_sparse_evidence = (
            len(evidence_tokens - DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS) >= 2
        )
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
    return scored


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
                if not taxonomy_candidate_conflicts(
                    source_tokens, item.get("category_path")
                )
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
        matches = _fallback_phrase_path_matches(
            phrase_tokens,
            taxonomy_index=taxonomy_index,
            source_tokens=source_tokens,
        )
    non_accessory_matches = [
        item
        for item in matches
        if not taxonomy_accessory_path(clean_text(item.get("category_path")).casefold())
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


def _fallback_phrase_path_matches(
    phrase_tokens: set[str],
    *,
    taxonomy_index: TaxonomyIndex,
    source_tokens: set[str],
) -> list[dict[str, object]]:
    leaf_tokens_by_path = {
        str(item.get("category_path") or ""): set(
            tokenize_text(
                item.get("leaf") or clean_text(item.get("category_path")).split(">")[-1]
            )
        )
        for item in taxonomy_index.categories
    }
    return [
        item
        for item in taxonomy_index.categories
        if phrase_tokens
        <= normalized_token_set(string_iterable(item.get("path_match_tokens")))
        and bool(
            phrase_tokens & leaf_tokens_by_path[str(item.get("category_path") or "")]
        )
        and not taxonomy_candidate_conflicts(source_tokens, item.get("category_path"))
    ]


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
            if not taxonomy_candidate_conflicts(
                source_tokens, item.get("category_path")
            )
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
    return {token for value in values if (token := normalize_taxonomy_token(value))}


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


def weighted_overlap(source_tokens: set[str], category_tokens: set[str]) -> float:
    if not source_tokens or not category_tokens:
        return 0.0
    overlap = source_tokens & category_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(source_tokens)


def weighted_product_overlap(
    source_tokens: set[str], category_tokens: set[str]
) -> float:
    product_tokens = {
        token
        for token in source_tokens
        if token not in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS
    }
    return weighted_overlap(product_tokens, category_tokens)


def has_product_kind_overlap(
    source_tokens: set[str], category_tokens: set[str]
) -> bool:
    overlap = source_tokens & category_tokens
    if not overlap:
        return False
    return any(
        token not in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS for token in overlap
    )
