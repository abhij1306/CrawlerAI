from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from decimal import Decimal, InvalidOperation

from app.core.config.data_enrichment import data_enrichment_settings
from app.core.records.normalizers import normalize_decimal_price
from app.core.shared.field_coerce import clean_text, strip_html_tags

_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
            values.extend(flatten_values(value, target_keys=target_keys))
        else:
            values.append(value)
    return values


def flatten_values(
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
    items = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else ()
    )
    for key, item in items:
        if target_keys is not None and str(key).casefold() in target_keys:
            if item not in (None, "", [], {}):
                values.extend(
                    flatten_values(item, max_depth=max_depth - 1)
                    if isinstance(item, (dict, list))
                    else [item]
                )
            continue
        if isinstance(item, (dict, list)):
            values.extend(
                flatten_values(
                    item,
                    max_depth=max_depth - 1,
                    target_keys=target_keys,
                )
            )
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
    return _TOKEN_RE.findall(clean_text(strip_html_tags(value)).casefold())


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
