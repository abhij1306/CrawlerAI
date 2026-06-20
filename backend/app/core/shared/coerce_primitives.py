from __future__ import annotations

__all__ = [
    "coerce_int",
    "bounded_int",
    "is_blank",
    "object_dict",
    "object_list",
    "positive_int",
    "safe_int",
    "string_list",
]

from collections.abc import Iterable


def is_blank(value: object) -> bool:
    return value in (None, "", [], {})


def object_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def object_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def string_list(
    value: object,
    *,
    accept_iterable: bool = False,
    strip: bool = False,
    none_as_empty: bool = False,
) -> list[str]:
    if accept_iterable:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            return []
        items = value
    elif isinstance(value, list):
        items = value
    else:
        return []
    values = [str(item or "") if none_as_empty else str(item) for item in items]
    return [item.strip() for item in values] if strip else values


def safe_int(value: object, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return default


def coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def positive_int(value: object) -> int | None:
    parsed = coerce_int(value)
    return parsed if parsed > 0 else None


def bounded_int(value: object, default: int, *, ceiling: int) -> int:
    return min(max(1, coerce_int(value, default=default)), int(ceiling))
