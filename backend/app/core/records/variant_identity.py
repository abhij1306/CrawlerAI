from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Protocol


class VariantHint(Protocol):
    @property
    def option_values(self) -> Mapping[str, str]: ...

    @property
    def variant_id(self) -> str | None: ...

    @property
    def sku(self) -> str | None: ...

    @property
    def url(self) -> str | None: ...


class VariantEvidence(Protocol):
    @property
    def collector_id(self) -> str: ...

    @property
    def entity_hint(self) -> VariantHint | None: ...

    @property
    def fact_type(self) -> str: ...

    @property
    def value(self) -> object: ...


def selected_variant_values(hints: Iterable[VariantHint | None]) -> tuple[str, ...]:
    return tuple(
        str(value).strip().casefold()
        for hint in hints
        if hint
        for value in (*hint.option_values.values(), hint.sku)
        if value
    )


def variant_values_support_selection(
    values: Iterable[object], selected: tuple[str, ...]
) -> bool:
    candidates = tuple(_alphanumeric_tokens(value) for value in values)
    selections = tuple(_alphanumeric_tokens(value) for value in selected)
    return bool(selections) and all(
        tokens
        and any(_contains_token_sequence(candidate, tokens) for candidate in candidates)
        for tokens in selections
    )


def _alphanumeric_tokens(value: object) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _contains_token_sequence(
    candidate: tuple[str, ...], selected: tuple[str, ...]
) -> bool:
    width = len(selected)
    return any(
        candidate[index : index + width] == selected for index in range(len(candidate))
    )


def matching_variant_owner(
    values: Iterable[object],
    selections: Iterable[tuple[str, Iterable[VariantHint | None]]],
) -> str | None:
    candidate_values = tuple(values)
    owners = {
        owner
        for owner, hints in selections
        if variant_values_support_selection(
            candidate_values, selected_variant_values(hints)
        )
    }
    return next(iter(owners)) if len(owners) == 1 else None


def variant_identity_keys(rows: Iterable[VariantEvidence]) -> set[str]:
    materialized = tuple(rows)
    keys = _fact_identity_keys(materialized) | _hint_identity_keys(materialized)
    options = variant_options(materialized)
    if _options_identify_row(materialized, options):
        keys.add(
            "options:" + "|".join(f"{key}={options[key]}" for key in sorted(options))
        )
    return keys


def variant_options(rows: Iterable[VariantEvidence]) -> dict[str, str]:
    return {
        row.fact_type.removeprefix("variant.option."): str(row.value).strip()
        for row in rows
        if row.fact_type.startswith("variant.option.") and str(row.value).strip()
    }


def preferred_variant_key(keys: set[str]) -> str:
    for prefix in ("id:", "sku:", "gtin:", "url:", "options:"):
        if match := sorted(key for key in keys if key.startswith(prefix)):
            return match[0]
    return sorted(keys)[0]


def _fact_identity_keys(rows: Iterable[VariantEvidence]) -> set[str]:
    return {
        f"{prefix}:{str(row.value).strip()}"
        for prefix, fact_type in (
            ("id", "variant.id"),
            ("sku", "variant.sku"),
            ("gtin", "variant.gtin"),
            ("url", "variant.url"),
        )
        for row in rows
        if row.fact_type == fact_type and str(row.value).strip()
    }


def _hint_identity_keys(rows: Iterable[VariantEvidence]) -> set[str]:
    return {
        f"{prefix}:{str(getattr(row.entity_hint, attr) or '').strip()}"
        for prefix, attr in (("id", "variant_id"), ("sku", "sku"), ("url", "url"))
        for row in rows
        if row.entity_hint and str(getattr(row.entity_hint, attr) or "").strip()
    }


def _options_identify_row(
    rows: tuple[VariantEvidence, ...], options: dict[str, str]
) -> bool:
    selected = any(
        row.fact_type == "variant.selected" and bool(row.value) for row in rows
    )
    structured = any(
        row.collector_id in {"jsonld", "js_state", "network", "adapter"}
        and row.fact_type.startswith("variant.option.")
        for row in rows
    )
    return bool(
        options
        and (selected or len(options) >= 2 or (len(options) == 1 and structured))
    )
