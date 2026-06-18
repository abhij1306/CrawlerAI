from __future__ import annotations

import re

BROWSER_VERSION_RE = re.compile(
    r"\b(?:Chrome|Chromium|Edg|Firefox|HeadlessChrome)/(\d+)",
    re.IGNORECASE,
)


def object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def string_list(value: object) -> list[str]:
    return [str(item) for item in object_list(value)]


__all__ = [
    "BROWSER_VERSION_RE",
    "object_dict",
    "object_list",
    "string_list",
]
