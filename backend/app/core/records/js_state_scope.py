from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, TypeGuard
from urllib.parse import unquote, urlparse

from app.core.config import variant_policy
from app.core.config.extraction_rules import (
    ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS,
    ECOMMERCE_RELATED_PRODUCT_BOUNDARY_PATH_TOKENS,
)
from app.core.config.field_mappings import (
    ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS,
    ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS,
)
from app.core.records.url_identity import (
    detail_identity_codes_from_url,
    detail_title_from_url,
    detail_url_resource_identity,
    semantic_identity_tokens,
)

RootStatus = Literal["selected", "unresolved", "ambiguous"]


@dataclass(frozen=True)
class RootSelection:
    """Outcome of fail-closed product-root selection over structured objects.

    ``selected`` carries one or more agreed product-root paths; ``unresolved``
    means no product root could be identified; ``ambiguous`` means several
    independent product roots compete and none matches the page. Only
    ``selected`` admits structured evidence — ``unresolved``/``ambiguous`` admit
    nothing, so recommendation/search/cache objects can never leak in (AUD-02).
    """

    status: RootStatus
    roots: tuple[str, ...] = ()


# Structural identity keys an embedded object may use to name the page product.
_ROOT_URL_KEYS = (
    "url",
    "canonicalUrl",
    "canonical_url",
    "productUrl",
    "product_url",
    "@id",
    "handle",
    "slug",
)
_ROOT_CODE_KEYS = (
    *ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS,
    "sku",
    "mpn",
    "gtin",
    "id",
    "@id",
)
_ROOT_TITLE_KEYS = ("name", "productName", "title", "productTitle")
_ROOT_TITLE_MIN_OVERLAP = 2


def path_tokens(path: str) -> set[str]:
    normalized = str(path).replace("[", "/").replace("]", "/").replace(".", "/")
    return {token.casefold() for token in normalized.split("/") if token}


def has_product_context(path: str, obj: dict) -> bool:
    keys = set(obj)
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    tokens = path_tokens(path)
    parts = tuple(token for token in str(path).replace(".", "/").split("/") if token)
    direct_product_path = bool(
        parts and parts[-1].casefold() in {"product", "products"}
    )
    product_keys = keys & ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS
    complete_offer = "price" in keys and bool(keys & {"currency", "currencyCode"})
    if (
        "config" in tokens
        and not direct_product_path
        and not complete_offer
        and not bool(keys & {"sku", "url", "productUrl", "product_url"})
    ):
        return False
    return (
        "product" in type_name
        or direct_product_path
        or len(product_keys) >= 2
        or bool(product_keys & {"name", "productName", "title"})
        and complete_offer
    )


def _path_is_descendant(path: str, ancestor: str) -> bool:
    if ancestor == "":
        return bool(path)
    normalized = ancestor.rstrip("/")
    if not normalized:
        return False
    if not path.startswith(normalized) or len(path) == len(normalized):
        return False
    return path[len(normalized)] in "/.["


@dataclass(frozen=True)
class _TargetSignals:
    """Structural identity signals derived from the page (final) URL."""

    identity: str
    path: str
    terminal: str
    codes: frozenset[str]
    title_tokens: frozenset[str]


def _normalized_url_path(value: str) -> str:
    parsed = urlparse(str(value or ""))
    path = unquote(parsed.path) if parsed.path else unquote(str(value or ""))
    return path.casefold().rstrip("/")


def _normalized_code(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _target_signals(final_url: str) -> _TargetSignals:
    path = _normalized_url_path(final_url)
    terminal = path.rsplit("/", 1)[-1] if path else ""
    return _TargetSignals(
        identity=detail_url_resource_identity(final_url),
        path=path,
        terminal=terminal,
        codes=frozenset(detail_identity_codes_from_url(final_url)),
        title_tokens=frozenset(
            semantic_identity_tokens(detail_title_from_url(final_url))
        ),
    )


def _object_title_tokens(obj: dict) -> frozenset[str]:
    tokens: set[str] = set()
    for key in _ROOT_TITLE_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            tokens |= set(semantic_identity_tokens(value))
    return frozenset(tokens)


def _object_matches_target(obj: dict, signals: _TargetSignals) -> bool:
    # 1. URL / handle / slug agreement (absolute identity, path, or terminal slug).
    for key in _ROOT_URL_KEYS:
        value = obj.get(key)
        if not _has_text(value):
            continue
        text = value.strip()
        if signals.identity and detail_url_resource_identity(text) == signals.identity:
            return True
        candidate_path = _normalized_url_path(text)
        candidate_terminal = candidate_path.rsplit("/", 1)[-1] if candidate_path else ""
        if signals.terminal and candidate_terminal == signals.terminal:
            return True
    # 2. Identity-code agreement (product id / sku / mpn / gtin embedded in the URL).
    if signals.codes:
        for key in _ROOT_CODE_KEYS:
            normalized = _normalized_code(obj.get(key))
            if len(normalized) >= 4 and normalized in signals.codes:
                return True
    # 3. Title agreement — only when it strongly covers the page title, so that
    #    same-brand recommendations cannot masquerade as the page product.
    if len(signals.title_tokens) >= _ROOT_TITLE_MIN_OVERLAP:
        shared = _object_title_tokens(obj) & signals.title_tokens
        if len(shared) >= _ROOT_TITLE_MIN_OVERLAP and len(shared) * 2 >= len(
            signals.title_tokens
        ):
            return True
    return False


def _has_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _promote_to_product_root(
    path: str, obj: dict, rows: tuple[tuple[str, Any], ...]
) -> str | None:
    ancestors = [
        candidate_path
        for candidate_path, candidate in rows
        if isinstance(candidate, dict)
        and candidate_path != path
        and _path_is_descendant(path, candidate_path)
        and has_product_context(candidate_path, candidate)
    ]
    if ancestors:
        return max(ancestors, key=len)
    if has_product_context(path, obj):
        return path
    return None


def _path_is_noise(path: str) -> bool:
    return bool(path_tokens(path) & ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS)


def _top_level_product_roots(rows: tuple[tuple[str, Any], ...]) -> list[str]:
    contexts = [
        (path, obj)
        for path, obj in rows
        if isinstance(obj, dict)
        and has_product_context(path, obj)
        and not _path_is_noise(path)
    ]
    context_paths = [path for path, _ in contexts]
    roots: list[str] = []
    for path, _obj in contexts:
        if any(
            other != path and _path_is_descendant(path, other)
            for other in context_paths
        ):
            continue
        roots.append(path)
    return roots


def _sorted_roots(roots: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(roots), key=lambda value: (len(value), value)))


def select_product_roots(
    objects: Iterable[tuple[str, Any]], final_url: str
) -> RootSelection:
    """Fail-closed product-root selection over embedded structured objects.

    Strong target matches (URL/handle, identity code, or dominant title overlap)
    select their promoted product roots. Absent any match, exactly one top-level
    product context selects; zero is ``unresolved`` and several is ``ambiguous``.
    Only a ``selected`` outcome admits evidence downstream.
    """

    rows = tuple(objects)
    signals = _target_signals(final_url)
    strong_roots: set[str] = set()
    for path, obj in rows:
        if not isinstance(obj, dict):
            continue
        if _object_matches_target(obj, signals):
            root = _promote_to_product_root(path, obj, rows)
            if root is not None:
                strong_roots.add(root)
    if strong_roots:
        return RootSelection("selected", _sorted_roots(strong_roots))
    top_roots = _top_level_product_roots(rows)
    if len(top_roots) == 1:
        return RootSelection("selected", _sorted_roots(top_roots))
    if not top_roots:
        return RootSelection("unresolved", ())
    return RootSelection("ambiguous", ())


def path_is_within_selected_root(path: str, selected_roots: tuple[str, ...]) -> bool:
    """Fail-closed containment test — an empty root set admits nothing (AUD-02)."""

    normalized = str(path).rstrip("/")
    for root in selected_roots:
        root_normalized = str(root).rstrip("/")
        if normalized == root_normalized or normalized.startswith(
            root_normalized + "/"
        ):
            return True
    return False


def root_admits_path(selection: RootSelection, path: str) -> bool:
    """Decide whether a structured-object path may contribute evidence.

    ``selected`` scopes strictly to the chosen product roots — unrelated
    siblings/recommendations are excluded (AUD-02). ``ambiguous`` (several
    competing product roots, none matching the page) admits nothing — choosing
    one would be a guess. ``unresolved`` (no product-context object at all, e.g.
    a bare ``variants``/offer array whose identity is the page itself) defers to
    the collector's own per-row conflict guards rather than discarding the only
    payload on the page.
    """

    if selection.status == "selected":
        return path_is_within_selected_root(path, selection.roots)
    if selection.status == "ambiguous":
        return False
    return True


def path_is_nested_sibling_product(
    selection: RootSelection,
    path: str,
    obj: dict,
    final_url: str,
) -> bool:
    if selection.status != "selected":
        return False
    normalized = str(path).rstrip("/")
    if any(normalized == str(root).rstrip("/") for root in selection.roots):
        return False
    if not path_is_within_selected_root(normalized, selection.roots):
        return False
    if not (path_tokens(normalized) & ECOMMERCE_RELATED_PRODUCT_BOUNDARY_PATH_TOKENS):
        return False
    if not has_product_context(normalized, obj):
        return False
    return not _object_matches_target(obj, _target_signals(final_url))


def selected_product_root_paths(
    objects: Iterable[tuple[str, Any]], final_url: str
) -> tuple[str, ...]:
    """Backward-compatible accessor returning roots only when selection succeeds."""

    return select_product_roots(objects, final_url).roots


def _normalized_cache_item_id(path_part: str) -> str | None:
    prefix, separator, encoded = str(path_part).partition(":")
    if separator != ":" or prefix.casefold() != "item" or not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return None
    entity, separator, item_id = decoded.partition(":")
    if separator != ":" or entity.casefold() != "item" or not item_id.isdigit():
        return None
    return item_id


def path_product_identity_conflicts(page_url: str, path: str) -> bool:
    parent_codes = set(detail_identity_codes_from_url(page_url))
    if not parent_codes:
        return False
    parts = tuple(
        part
        for part in str(path).replace("[", "/").replace("]", "/").split("/")
        if part
    )
    normalized_item_ids = {
        item_id
        for part in parts
        if (item_id := _normalized_cache_item_id(part)) is not None
    }
    if normalized_item_ids - parent_codes:
        return True
    for index, part in enumerate(parts[:-1]):
        if part.casefold() not in variant_policy.VARIANT_PRODUCT_MAP_PATH_TOKENS:
            continue
        candidate = parts[index + 1]
        normalized = "".join(char for char in candidate if char.isalnum()).upper()
        valid_code = all(
            (
                len(normalized) >= variant_policy.VARIANT_PRODUCT_MAP_KEY_MIN_LENGTH,
                any(map(str.isalpha, normalized)),
                any(map(str.isdigit, normalized)),
            )
        )
        if not valid_code:
            continue
        if not any(
            any((left == normalized, left in normalized, normalized in left))
            for left in parent_codes
        ):
            return True
    return False
