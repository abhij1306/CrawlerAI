from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class JsonNode:
    pointer: str
    parent_key: str | None
    array_index: int | None
    ancestor_keys: tuple[str, ...]
    ancestor_schema_types: tuple[str, ...]
    value: Any


def walk_json(value: Any) -> Iterator[JsonNode]:
    yield from _walk(
        value,
        pointer="",
        parent_key=None,
        array_index=None,
        ancestor_keys=(),
        ancestor_schema_types=(),
    )


def _walk(
    value: Any,
    *,
    pointer: str,
    parent_key: str | None,
    array_index: int | None,
    ancestor_keys: tuple[str, ...],
    ancestor_schema_types: tuple[str, ...],
) -> Iterator[JsonNode]:
    schema_types = ancestor_schema_types
    if isinstance(value, dict):
        raw_type = value.get("@type")
        if isinstance(raw_type, str) and raw_type:
            schema_types = (*schema_types, raw_type)
        elif isinstance(raw_type, list):
            schema_types = (*schema_types, *(str(item) for item in raw_type if item))
    yield JsonNode(
        pointer=pointer or "/",
        parent_key=parent_key,
        array_index=array_index,
        ancestor_keys=ancestor_keys,
        ancestor_schema_types=schema_types,
        value=value,
    )
    if isinstance(value, dict):
        for key, child in value.items():
            escaped_key = str(key).replace("~", "~0").replace("/", "~1")
            yield from _walk(
                child,
                pointer=f"{pointer}/{escaped_key}",
                parent_key=str(key),
                array_index=None,
                ancestor_keys=(*ancestor_keys, str(key)),
                ancestor_schema_types=schema_types,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(
                child,
                pointer=f"{pointer}/{index}",
                parent_key=parent_key,
                array_index=index,
                ancestor_keys=ancestor_keys,
                ancestor_schema_types=schema_types,
            )
