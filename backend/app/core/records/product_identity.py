from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from app.core.records.url_identity import (
    detail_url_marker_identity,
    detail_url_resource_identity,
    detail_title_from_url,
    selected_variant_axes,
    semantic_identity_tokens,
)


def normalized_product_identity_value(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    return " ".join(str(value).casefold().split())


def product_title_identity_tokens(values: Iterable[object]) -> set[str]:
    return {token for value in values for token in semantic_identity_tokens(str(value))}


def product_url_target_rank(target_url: str, candidates: Iterable[object]) -> int:
    urls = tuple(
        str(hint.url)
        for candidate in candidates
        if (hint := getattr(candidate, "entity_hint", None)) is not None and hint.url
    )
    if not urls:
        return 2
    target_resource = detail_url_resource_identity(target_url)
    if target_resource and target_resource in {
        detail_url_resource_identity(url) for url in urls
    }:
        return 0
    target_marker = detail_url_marker_identity(target_url)
    if target_marker and target_marker in {
        detail_url_marker_identity(url) for url in urls
    }:
        return 1
    return 3


def target_product_owner_id(
    is_target: bool, current: str | None, owners: Iterable[str]
) -> str | None:
    if current is not None or not is_target:
        return current
    unique_owners = set(owners)
    return next(iter(unique_owners)) if len(unique_owners) == 1 else None


def target_offer_group_id(
    target_url: str, candidate_url: str = "", product_id: object = None
) -> str:
    target_resource = detail_url_resource_identity(target_url)
    if not target_resource:
        return ""
    target_marker = detail_url_marker_identity(target_url)
    candidate_resource = detail_url_resource_identity(candidate_url)
    if candidate_resource:
        if selected_variant_axes(target_url) != selected_variant_axes(candidate_url):
            return ""
        candidate_marker = detail_url_marker_identity(candidate_url)
        if candidate_resource != target_resource and (
            not target_marker or candidate_marker != target_marker
        ):
            return ""
        return f"offer:target:{target_marker or target_resource}"
    identity = normalized_product_identity_value(product_id)
    target_ids = {
        normalized_product_identity_value(value.rsplit("/", 1)[-1])
        for value in (target_marker, target_resource)
        if value
    }
    return (
        f"offer:target:{target_marker or target_resource}"
        if identity and identity in target_ids
        else ""
    )


def product_identity_sets_match(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    if left & right:
        return True
    if _product_url_marker_keys(left) & _product_url_marker_keys(right):
        return True
    if _jsonld_node_matches_product_url(left, right):
        return True
    left_urls = {value for kind, value in left if kind == "product.url"}
    right_urls = {value for kind, value in right if kind == "product.url"}
    return _product_url_paths_compatible(left_urls, right_urls)


def _jsonld_node_matches_product_url(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    return bool(
        _url_terminal_keys(left, kind="jsonld.node_id")
        & _url_terminal_keys(right, kind="product.url")
        or _url_terminal_keys(right, kind="jsonld.node_id")
        & _url_terminal_keys(left, kind="product.url")
    )


def _url_terminal_keys(
    identities: set[tuple[str, str]], *, kind: str
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for identity_kind, value in identities:
        if identity_kind != kind:
            continue
        parsed = urlsplit(value)
        terminal = parsed.path.rstrip("/").rsplit("/", 1)[-1].casefold()
        if parsed.hostname and terminal:
            keys.add((parsed.hostname.casefold(), terminal))
    return keys


def _product_url_marker_keys(
    identities: set[tuple[str, str]],
) -> set[str]:
    return {
        marker
        for kind, value in identities
        if kind == "product.url" and (marker := detail_url_marker_identity(value))
    }


def product_identity_sets_compatible(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    for kind in {identity_kind for identity_kind, _value in left | right}:
        left_values = {value for identity_kind, value in left if identity_kind == kind}
        right_values = {
            value for identity_kind, value in right if identity_kind == kind
        }
        if not _identity_kind_compatible(
            kind,
            left,
            right,
            left_values=left_values,
            right_values=right_values,
        ):
            return False
    return True


def _identity_kind_compatible(
    kind: str,
    left: set[tuple[str, str]],
    right: set[tuple[str, str]],
    *,
    left_values: set[str],
    right_values: set[str],
) -> bool:
    if _identity_values_compatible(left_values, right_values):
        return True
    if kind == "jsonld.node_path":
        return True
    if kind not in {"product.url", "product.url_resource"}:
        return False
    if _product_url_marker_keys(left) & _product_url_marker_keys(right):
        return True
    left_urls = {
        value for identity_kind, value in left if identity_kind == "product.url"
    }
    right_urls = {
        value for identity_kind, value in right if identity_kind == "product.url"
    }
    if _product_url_paths_compatible(left_urls, right_urls):
        return True
    if _shares_strong_product_identity(left, right):
        return True
    return kind == "product.url" and any(
        identity in right for identity in left if identity[0] == "product.url_resource"
    )


def _identity_values_compatible(left: set[str], right: set[str]) -> bool:
    return not left or not right or not left.isdisjoint(right)


def _shares_strong_product_identity(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    strong = {"product.gtin", "product.id", "product.mpn", "product.sku"}
    return any(identity in right for identity in left if identity[0] in strong)


def _product_url_paths_compatible(left: set[str], right: set[str]) -> bool:
    for left_url in left:
        for right_url in right:
            first, second = urlsplit(left_url), urlsplit(right_url)
            if first.hostname != second.hostname:
                continue
            short, long = sorted(
                (first.path.rstrip("/"), second.path.rstrip("/")), key=len
            )
            short_url = left_url if first.path.rstrip("/") == short else right_url
            if (
                short
                and long.startswith(f"{short}/")
                and detail_title_from_url(short_url)
            ):
                return True
    return False
