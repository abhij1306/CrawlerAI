from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.core.config import variant_policy
from app.core.config.field_mappings import (
    ECOMMERCE_IMAGE_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_SOURCE_VALUE_PATH_FACT_TYPES,
)
from app.core.config.extraction_rules import (
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS,
)
from app.core.shared.url_utils import extract_urls


def expand_embedded_state_payload(
    root_path: str, data: object
) -> Iterable[tuple[str, object]]:
    if is_nuxt_devalue_payload(root_path, data):
        yielded = False
        for key, value in nuxt_product_roots(data):
            decoded = hydrate_parent_option_labels(value)
            if decoded not in (None, "", [], {}):
                yielded = True
                yield f"{root_path}/{key}", decoded
        if yielded:
            return
        decoded_root = decode_nuxt_devalue(data, 0)
        decoded_root = hydrate_parent_option_labels(decoded_root)
        if decoded_root not in (None, "", [], {}):
            yield root_path, decoded_root
            return
    yield root_path, data


def is_nuxt_devalue_payload(root_path: str, data: object) -> bool:
    return "__NUXT_DATA__" in root_path and isinstance(data, list) and bool(data)


def nuxt_product_roots(data: object) -> Iterable[tuple[str, object]]:
    if not isinstance(data, list):
        return
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        for key, raw_ref in item.items():
            if key in seen or not any(
                str(key).startswith(prefix)
                for prefix in variant_policy.NUXT_PRODUCT_ROOT_KEY_PREFIXES
            ):
                continue
            if type(raw_ref) is not int:
                continue
            decoded = decode_nuxt_devalue(data, raw_ref)
            if decoded in (None, "", [], {}):
                continue
            seen.add(key)
            yield str(key), decoded


def decode_nuxt_devalue(data: object, root_index: int) -> object:
    if not isinstance(data, list) or not (0 <= root_index < len(data)):
        return None
    return _NuxtDecoder(data).decode_ref(root_index, 0)


class _NuxtDecoder:
    def __init__(self, data: list[object]) -> None:
        self.data = data
        self.memo: dict[int, object] = {}
        self.visiting: set[int] = set()
        self.visited = 0

    def decode_ref(self, index: int, depth: int) -> object:
        if not (0 <= index < len(self.data)):
            return None
        if index in self.memo:
            return self.memo[index]
        if index in self.visiting or self._limit_reached(depth):
            return None
        self.visiting.add(index)
        self.visited += 1
        decoded = self.decode_node(self.data[index], depth)
        self.visiting.remove(index)
        self.memo[index] = decoded
        return decoded

    def _limit_reached(self, depth: int) -> bool:
        return (
            depth >= variant_policy.EMBEDDED_STATE_MAX_DEPTH
            or self.visited >= variant_policy.NUXT_DEVALUE_DECODE_MAX_NODES
        )

    def decode_node(self, node: object, depth: int) -> object:
        if isinstance(node, dict):
            return self._decode_mapping(node, depth)
        if isinstance(node, list):
            return self._decode_list(node, depth)
        return node

    def _decode_mapping(self, node: dict, depth: int) -> object:
        if depth >= variant_policy.EMBEDDED_STATE_MAX_DEPTH:
            return None
        return {
            str(key): self._decode_value(value, depth + 1)
            for key, value in node.items()
            if key not in (None, "")
        }

    def _decode_list(self, node: list, depth: int) -> object:
        if self._is_wrapper(node):
            return self.decode_ref(node[1], depth + 1)
        if depth >= variant_policy.EMBEDDED_STATE_MAX_DEPTH:
            return None
        return [
            self._decode_value(value, depth + 1)
            for value in node[: variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS]
        ]

    def _decode_value(self, value: object, depth: int) -> object:
        return (
            self.decode_ref(value, depth)
            if type(value) is int
            else self.decode_node(value, depth)
        )

    @staticmethod
    def _is_wrapper(node: list) -> bool:
        return (
            len(node) >= 2
            and isinstance(node[0], str)
            and node[0] in variant_policy.NUXT_DEVALUE_WRAPPER_TAGS
            and type(node[1]) is int
        )


def hydrate_parent_option_labels(data: object) -> object:
    if not isinstance(data, dict):
        return data
    axes = product_option_label_maps(data)
    if not axes:
        return data
    variants = data.get("variants")
    if not isinstance(variants, list):
        return data
    hydrated: list[object] = []
    for item in variants:
        if not isinstance(item, dict):
            hydrated.append(item)
            continue
        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            hydrated.append(item)
            continue
        update = dict(item)
        normalized_attrs = dict(attrs)
        for axis, value_map in axes.items():
            raw = scalar_value(attrs.get(axis))
            label = value_map.get(str(raw or "").strip())
            if label:
                normalized_attrs[axis] = label
                update[axis] = label
        update["attributes"] = normalized_attrs
        hydrated.append(update)
    return {**data, "variants": hydrated}


def product_option_label_maps(data: dict) -> dict[str, dict[str, str]]:
    raw_attributes = data.get("attributes")
    if not isinstance(raw_attributes, list):
        return {}
    out: dict[str, dict[str, str]] = {}
    for item in raw_attributes:
        _add_product_option_label_map(out, item)
    return out


def _add_product_option_label_map(
    out: dict[str, dict[str, str]],
    item: object,
) -> None:
    if not isinstance(item, dict):
        return
    axis = canonical_axis(first(item, "type", "attributeId", "id", "name"))
    raw_options = item.get("options")
    if not axis or not isinstance(raw_options, list):
        return
    for option in raw_options:
        _add_product_option_label(out, axis=axis, option=option)


def _add_product_option_label(
    out: dict[str, dict[str, str]],
    *,
    axis: str,
    option: object,
) -> None:
    if not isinstance(option, dict):
        return
    value = str(scalar_value(option.get("value")) or "").strip()
    label = str(scalar_value(option.get("label")) or "").strip()
    if value and label:
        out.setdefault(axis, {})[value] = label


def variant_axis_hints(
    objects: tuple[tuple[str, object], ...],
) -> dict[str, tuple[str, ...]]:
    hints: dict[str, tuple[str, ...]] = {}
    for parent_path, parent in objects:
        if not isinstance(parent, dict):
            continue
        axes = parent_option_axes(parent)
        _record_child_axis_hints(
            hints,
            parent_path=parent_path,
            parent=parent,
            child_keys=variant_policy.VARIANT_PARENT_OPTION_CHILD_KEYS,
            axes=axes,
        )
        value_axis = parent_option_value_axis(parent)
        if not value_axis:
            continue
        _record_child_axis_hints(
            hints,
            parent_path=parent_path,
            parent=parent,
            child_keys=variant_policy.VARIANT_PARENT_OPTION_VALUE_CHILD_KEYS,
            axes=(value_axis,),
        )
    return hints


def _record_child_axis_hints(
    hints: dict[str, tuple[str, ...]],
    *,
    parent_path: str,
    parent: dict,
    child_keys: tuple[str, ...],
    axes: tuple[str, ...],
) -> None:
    if not axes:
        return
    for child_key in child_keys:
        children = parent.get(child_key)
        if not isinstance(children, list):
            continue
        for index, child in enumerate(children):
            if isinstance(child, dict):
                hints[f"{parent_path}/{child_key}/{index}"] = axes


def parent_option_axes(obj: dict) -> tuple[str, ...]:
    raw_options = obj.get("options")
    if not isinstance(raw_options, list) or not raw_options:
        return ()
    axes: list[str] = []
    for raw_option in raw_options:
        raw_axis = (
            first(raw_option, *variant_policy.VARIANT_OPTION_AXIS_KEYS)
            if isinstance(raw_option, dict)
            else raw_option
        )
        axis = canonical_axis(raw_axis)
        if axis is None:
            return ()
        axes.append(axis)
    return tuple(axes)


def parent_option_value_axis(obj: dict) -> str | None:
    if not any(
        isinstance(obj.get(key), list)
        for key in variant_policy.VARIANT_PARENT_OPTION_VALUE_CHILD_KEYS
    ):
        return None
    return canonical_axis(first(obj, "attributeId", "type", "id", "name", "label"))


def with_parent_variant_axes(obj: dict, axes: tuple[str, ...]) -> dict:
    if any((not axes, obj.get("selectedOptions"))):
        return obj
    values = [
        scalar_value(obj.get(key))
        for key in variant_policy.VARIANT_POSITIONAL_OPTION_KEYS
    ]
    if not any(value not in (None, "", [], {}) for value in values):
        raw_options = obj.get("options")
        values = list(raw_options) if isinstance(raw_options, list) else []
    if not any(value not in (None, "", [], {}) for value in values):
        values = [first(obj, *variant_policy.VARIANT_OPTION_VALUE_KEYS)]
    selected = [
        {"name": axis, "value": value}
        for axis, value in zip(axes, values, strict=False)
        if all((value not in (None, "", [], {}), not isinstance(value, dict)))
    ]
    url_axis_values = variant_endpoint_url_axis_values(url_value(obj))
    selected_axes = {str(row["name"]) for row in selected}
    selected.extend(
        {"name": axis, "value": value}
        for axis, value in url_axis_values.items()
        if axis not in selected_axes
    )
    if not selected:
        return obj
    enriched = {**obj, "selectedOptions": selected}
    url = url_value(enriched)
    if all(
        (
            "variantId" not in enriched,
            url,
            variant_endpoint_url_axis_count(url) >= len(selected),
            not all((len(selected) == 1, selected[0]["name"] == "color")),
        )
    ):
        enriched["variantId"] = url
    return enriched


def same_product_variant_endpoint(page_url: str, candidate_url: str) -> bool:
    absolute = urljoin(page_url, candidate_url)
    page = urlsplit(page_url)
    candidate = urlsplit(absolute)
    if (
        not page.hostname
        or page.hostname.lower() != str(candidate.hostname or "").lower()
    ):
        return False
    path_tokens = {
        token for token in re.split(r"[^a-z0-9]+", candidate.path.casefold()) if token
    }
    if not (path_tokens & VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS):
        return False
    return variant_endpoint_url_axis_count(absolute) > 0


def variant_endpoint_url_axis_count(candidate_url: str) -> int:
    return len(variant_endpoint_url_axis_values(candidate_url))


def variant_endpoint_url_axis_values(candidate_url: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in parse_qsl(urlsplit(candidate_url).query, keep_blank_values=False):
        if not value:
            continue
        axis_match = re.match(VARIANT_DOM_URL_AXIS_PARAM_PATTERN, key, flags=re.I)
        if not axis_match:
            continue
        axis = variant_policy.canonical_variant_axis(axis_match.group("axis"))
        if axis:
            out.setdefault(axis, value)
    return out


def url_value(obj: dict) -> str:
    candidate = first(obj, *variant_policy.VARIANT_URL_VALUE_KEYS)
    if isinstance(candidate, dict):
        candidate = first(candidate, *variant_policy.VARIANT_NESTED_URL_VALUE_KEYS)
    scalar = scalar_value(candidate)
    return scalar.strip() if isinstance(scalar, str) else ""


def first(obj: dict, *keys: str, depth: int = 0):
    if depth >= variant_policy.EMBEDDED_STATE_MAX_DEPTH:
        return None
    for key in keys:
        if (value := obj.get(key)) not in (None, "", [], {}):
            return value
    for source in obj.values():
        if isinstance(source, dict) and (
            value := first(source, *keys, depth=depth + 1)
        ) not in (None, "", [], {}):
            return value
    return None


def scalar_value(value):
    if isinstance(value, dict):
        for key in variant_policy.VARIANT_SCALAR_VALUE_KEYS:
            if value.get(key) not in (None, "", [], {}):
                return scalar_value(value.get(key))
        return ""
    if isinstance(value, list):
        return " ".join(
            str(scalar_value(item)) for item in value if scalar_value(item)
        ).strip()
    return value


def canonical_axis(value: object) -> str | None:
    text = str(scalar_value(value) or "").strip()
    return variant_policy.canonical_variant_axis(text)


def configured_value_path_rows(obj: dict) -> list[tuple[str, str, object, str]]:
    rows: list[tuple[str, str, object, str]] = []
    for key_path, fact in ECOMMERCE_STRUCTURED_SOURCE_VALUE_PATH_FACT_TYPES.items():
        value = value_at_path(obj, key_path)
        if value in (None, "", [], {}):
            continue
        key = key_path[0]
        suffix = "".join(f"/{part}" for part in key_path[1:])
        rows.append((key, fact, scalar_value(value), suffix))
    return rows


def value_at_path(obj: dict, key_path: tuple[str, ...]) -> object:
    return value_at_path_suffix(obj, key_path)


def value_at_path_suffix(current: object, key_path: tuple[str, ...]) -> object:
    if not key_path:
        return current
    if isinstance(current, list):
        for item in current:
            value = value_at_path_suffix(item, key_path)
            if value not in (None, "", [], {}):
                return value
        return None
    if not isinstance(current, dict):
        return None
    return value_at_path_suffix(current.get(key_path[0]), key_path[1:])


def source_values(key: str, value: object) -> tuple[object, ...]:
    if key in ECOMMERCE_IMAGE_SOURCE_KEYS:
        return tuple(extract_urls(value, ""))
    return (scalar_value(value),)
