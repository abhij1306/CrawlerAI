from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_AUDIENCE_ALIASES,
    DATA_ENRICHMENT_AVAILABILITY_TERMS,
    DATA_ENRICHMENT_COLOR_FAMILY_ALIASES,
    DATA_ENRICHMENT_GENDER_ALIASES,
    DATA_ENRICHMENT_SEO_STOPWORDS,
    DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS,
    DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS,
)
from app.core.shared.coerce_primitives import object_list, string_list
from app.core.shared.field_coerce import clean_text, strip_html_tags

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class TaxonomyIndex:
    version: str
    categories: tuple[dict[str, object], ...]
    exact_lookup: dict[str, dict[str, object]]
    leaf_lookup: dict[str, tuple[dict[str, object], ...]]
    path_phrase_lookup: dict[str, tuple[dict[str, object], ...]]
    id_lookup: dict[str, dict[str, object]]


def normalize_taxonomy_token(value: object) -> str:
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


def tokenize_text(value: object) -> list[str]:
    return [
        normalized
        for token in _TOKEN_RE.findall(clean_text(strip_html_tags(value)).casefold())
        if token != "s" and (normalized := normalize_taxonomy_token(token))  # nosec B105
    ]


def normalize_category_path(value: object) -> str:
    normalized_parts = [tokenize_text(part) for part in clean_text(value).split(">")]
    return " > ".join(" ".join(tokens) for tokens in normalized_parts if tokens)


def string_iterable(value: object) -> list[str]:
    return [
        item
        for item in string_list(value, accept_iterable=True, strip=True)
        if item
    ]


def attribute_lookup_keys(attribute: str) -> tuple[str, ...]:
    normalized = str(attribute or "").strip().replace("-", "_")
    explicit = DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS.get(normalized)
    if explicit:
        return tuple(str(item) for item in explicit)
    variants = [normalized]
    if normalized.endswith("_type"):
        variants.append(normalized[:-5])
    if normalized.startswith("target_"):
        variants.append(normalized.removeprefix("target_"))
    return tuple(dict.fromkeys(item for item in variants if item))


def taxonomy_phrases(tokens: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            " ".join(tokens[index : index + width])
            for width in range(min(5, len(tokens)), 1, -1)
            for index in range(len(tokens) - width + 1)
        )
    )


def _load_json_dict(path: Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Data enrichment JSON must be an object: {path}")
    return payload


def _attribute_values(item: dict[str, object]) -> list[str]:
    return [
        str(value.get("name") or "")
        for value in object_list(item.get("values"))
        if isinstance(value, dict) and str(value.get("name") or "").strip()
    ]


def _attribute_by_name(
    attributes: list[dict[str, object]], name: str, *, merge: bool = False
) -> dict[str, object]:
    normalized_name = str(name or "").strip().casefold()
    matches = [
        item
        for item in attributes
        if str(item.get("name") or "").strip().casefold() == normalized_name
    ]
    if not matches:
        return {}
    values = [value for item in matches for value in _attribute_values(item)]
    if merge:
        values = list({value.casefold(): value for value in reversed(values)}.values())[::-1]
    elif values:
        values = _attribute_values(matches[0])
    return {
        "name": str(matches[0].get("name") or name or ""),
        "handle": str(matches[0].get("handle") or ""),
        "values": values,
    }


def _attribute_terms(attribute: dict[str, object]) -> dict[str, list[str]]:
    return {
        cleaned: [cleaned]
        for value in object_list(attribute.get("values"))
        if (cleaned := clean_text(value).casefold())
    }


def _color_family_terms(
    attribute: dict[str, object], attributes: list[dict[str, object]]
) -> dict[str, list[str]]:
    source_values = set(_attribute_terms(attribute))
    source_values.update(
        clean_text(value.get("name")).casefold()
        for item in attributes
        for value in object_list(item.get("values"))
        if isinstance(value, dict) and clean_text(value.get("name"))
    )
    terms: dict[str, list[str]] = {}
    for canonical, aliases in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES.items():
        allowed = [alias for alias in aliases if clean_text(alias).casefold() in source_values]
        if clean_text(canonical).casefold() in source_values and canonical not in allowed:
            allowed.insert(0, canonical)
        if allowed:
            terms[canonical] = list(dict.fromkeys(allowed))
    return terms


def _size_systems(attribute: dict[str, object]) -> dict[str, object]:
    aliases: dict[str, str] = {}
    systems: dict[str, set[str]] = {"alpha": set(), "numeric": set()}
    for raw_value in object_list(attribute.get("values")):
        value = clean_text(raw_value)
        if not value:
            continue
        match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", value)
        canonical = match.group(1).upper() if match else ""
        if canonical:
            aliases[value.casefold()] = canonical
            base_name = clean_text(re.sub(r"\s*\([A-Za-z0-9]+\)\s*$", "", value))
            if base_name:
                aliases[base_name.casefold()] = canonical
            target = "alpha" if re.fullmatch(r"[A-Z]{1,4}|\d+XL", canonical) else "numeric"
            if target == "alpha" or canonical.isdigit():
                systems[target].add(canonical.casefold())
        if value.casefold() == "one size":
            aliases[value.casefold()] = "OS"
            systems["alpha"].add("os")
        if value.isdigit():
            systems["numeric"].add(value.casefold())
    return {"aliases": aliases, "systems": {key: sorted(values) for key, values in systems.items()}}


@lru_cache(maxsize=16)
def load_attribute_repository_data(path: Path) -> dict[str, object]:
    raw = _load_json_dict(path)
    attributes = [item for item in object_list(raw.get("attributes")) if isinstance(item, dict)]
    by_handle = {
        str(item.get("handle") or "").replace("-", "_"): {
            "name": str(item.get("name") or ""),
            "handle": str(item.get("handle") or ""),
            "values": _attribute_values(item),
        }
        for item in attributes
        if str(item.get("handle") or "").strip()
    }
    names = DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES
    color = _attribute_by_name(attributes, names["color"], merge=True)
    size = _attribute_by_name(attributes, names["size"])
    audience = _attribute_by_name(attributes, names["audience"])
    material_terms = {
        value: [value]
        for name in (names["fabric"], names["material"])
        for value in _attribute_terms(_attribute_by_name(attributes, name))
    }
    audience_terms = _attribute_terms(audience) or {
        key: list(values) for key, values in DATA_ENRICHMENT_AUDIENCE_ALIASES.items()
    }
    return {
        "version": str(raw.get("version") or ""),
        "normalization_terms": {
            "availability_terms": {
                key: list(values) for key, values in DATA_ENRICHMENT_AVAILABILITY_TERMS.items()
            },
            "audience_terms": audience_terms,
            "color_families": _color_family_terms(color, attributes),
            "gender_terms": {
                key: list(values) for key, values in DATA_ENRICHMENT_GENDER_ALIASES.items()
            },
            "material_terms": material_terms,
            "seo_stopwords": list(DATA_ENRICHMENT_SEO_STOPWORDS),
            "size_systems": _size_systems(size),
        },
        "attributes_by_handle": by_handle,
    }


def _taxonomy_path_phrases(item: dict[str, object]) -> list[str]:
    phrases = taxonomy_phrases(tokenize_text(item.get("normalized_path")))
    parts = [part for part in clean_text(item.get("category_path")).split(">") if part.strip()]
    if len(parts) < 2:
        return phrases
    for root_token in tokenize_text(parts[0]):
        for leaf_token in tokenize_text(parts[-1]):
            if root_token in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
                continue
            if leaf_token in DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS:
                continue
            phrases.extend((f"{leaf_token} {root_token}", f"{root_token} {leaf_token}"))
    return list(dict.fromkeys(phrases))


def _taxonomy_row(category: dict[str, object]) -> dict[str, Any] | None:
    category_id = str(category.get("id") or "").strip()
    category_path = clean_text(category.get("full_name"))
    normalized_path = normalize_category_path(category_path)
    if not category_id or not category_path or not normalized_path:
        return None
    handles = [
        str(item.get("handle") or "").replace("-", "_")
        for item in object_list(category.get("attributes"))
        if isinstance(item, dict) and str(item.get("handle") or "").strip()
    ]
    return {
        "category_id": category_id,
        "category_path": category_path,
        "normalized_path": normalized_path,
        "leaf": normalize_category_path(category.get("name")),
        "attribute_handles": handles,
        "path_match_tokens": set(tokenize_text(category_path)),
        "attribute_match_tokens": set(tokenize_text(" ".join(handles))),
    }


@lru_cache(maxsize=16)
def load_taxonomy_index(path: Path) -> TaxonomyIndex:
    raw = _load_json_dict(path)
    rows = [
        row
        for vertical in object_list(raw.get("verticals"))
        if isinstance(vertical, dict)
        for category in object_list(vertical.get("categories"))
        if isinstance(category, dict)
        if (row := _taxonomy_row(category)) is not None
    ]
    exact_lookup = {str(row["normalized_path"]): row for row in rows}
    id_lookup = {str(row["category_id"]): row for row in rows}
    leaf_lookup: dict[str, list[dict[str, object]]] = {}
    phrase_lookup: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if leaf := str(row.get("leaf") or ""):
            leaf_lookup.setdefault(leaf, []).append(row)
        for phrase in _taxonomy_path_phrases(row):
            phrase_lookup.setdefault(phrase, []).append(row)
    return TaxonomyIndex(
        version=str(raw.get("version") or ""),
        categories=tuple(rows),
        exact_lookup=exact_lookup,
        leaf_lookup={key: tuple(value) for key, value in leaf_lookup.items()},
        path_phrase_lookup={key: tuple(value) for key, value in phrase_lookup.items()},
        id_lookup=id_lookup,
    )
