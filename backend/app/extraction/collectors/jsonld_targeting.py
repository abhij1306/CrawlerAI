from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from app.core.records.js_state_scope import RootSelection, select_product_roots
from app.core.records.product_identity import target_offer_group_id
from app.core.records.url_identity import detail_url_resource_identity
from app.core.shared.ids import stable_id


def include_selected_product_group(
    objects: tuple[tuple[str, Any], ...], final_url: str
) -> RootSelection:
    """Admit a ProductGroup when target identity selects one of its variants."""
    selection = select_product_roots(objects, final_url)
    if selection.status != "selected":
        return selection
    by_path = dict(objects)
    roots = set(selection.roots)
    for root in selection.roots:
        if "/hasVariant/" not in root:
            continue
        parent_path = root.split("/hasVariant/", 1)[0]
        parent = by_path.get(parent_path)
        if isinstance(parent, dict) and is_product_group(parent):
            roots.add(parent_path)
    return RootSelection(
        status="selected",
        roots=tuple(sorted(roots, key=lambda value: (len(value), value))),
    )


def sole_target_offer_url(final_url: str, offers: Any) -> str:
    rows = offers if isinstance(offers, list) else [offers]
    urls = {
        str(url).strip()
        for row in rows
        if isinstance(row, dict)
        and (url := row.get("url"))
        and (
            target_offer_group_id(final_url, str(url))
            or detail_url_resource_identity(final_url)
            == detail_url_resource_identity(str(url))
        )
    }
    return next(iter(urls)) if len(urls) == 1 else ""


def selected_product_group_child_url(final_url: str, children: Any) -> str:
    """Return one child URL that the request selects through hasVariant."""
    rows = children if isinstance(children, list) else [children]
    urls = {
        url
        for row in rows
        if isinstance(row, dict)
        for url in _variant_urls(row)
        if target_offer_group_id(final_url, url)
    }
    return next(iter(urls)) if len(urls) == 1 else ""


def hint_target_offer_group(final_url: str, rows: list[Any], hint_url: str) -> str:
    """Let only one URL-less offer claim the hinted target group."""
    group = target_offer_group_id(final_url, hint_url)
    if not group:
        return ""
    claimants = sum(
        1
        for row in rows
        if isinstance(row, dict) and not str(row.get("url") or "").strip()
    )
    return group if claimants == 1 else ""


def target_product_owner_identity(
    final_url: str,
    declared_product_url: str,
    target_offer_url: str,
    selected_child_url: str,
    *,
    is_product_group: bool,
) -> str:
    owns_target = _owns_target(
        final_url,
        declared_product_url,
        target_offer_url,
        selected_child_url,
        is_product_group=is_product_group,
    )
    return final_url if owns_target else ""


def target_product_source_aliases(
    source_subject_ids: tuple[str, ...],
    *,
    bundle_id: str,
    final_url: str,
    declared_product_url: str,
    target_offer_url: str,
    selected_child_url: str,
    is_product_group: bool,
) -> tuple[str, ...]:
    owns_target = _owns_target(
        final_url,
        declared_product_url,
        target_offer_url,
        selected_child_url,
        is_product_group=is_product_group,
    )
    if not owns_target:
        return source_subject_ids
    return tuple(
        dict.fromkeys(
            (
                *source_subject_ids,
                stable_id("subject", bundle_id, "product", final_url),
            )
        )
    )


def _owns_target(
    final_url: str,
    declared_product_url: str,
    target_offer_url: str,
    selected_child_url: str,
    *,
    is_product_group: bool,
) -> bool:
    return (
        bool(selected_child_url)
        or bool(target_offer_url and not declared_product_url)
        or _same_host_terminal_resource(final_url, declared_product_url)
        or bool(
            is_product_group
            and declared_product_url
            and target_offer_group_id(final_url, declared_product_url)
        )
    )


def _same_host_terminal_resource(final_url: str, declared_product_url: str) -> bool:
    """Treat locale-prefixed URLs with the same terminal PDP slug as one resource."""
    if not declared_product_url:
        return False
    target = urlsplit(final_url)
    candidate = urlsplit(declared_product_url)
    target_host = str(target.hostname or "").casefold().removeprefix("www.")
    candidate_host = str(candidate.hostname or "").casefold().removeprefix("www.")
    target_terminal = unquote(target.path).casefold().rstrip("/").rsplit("/", 1)[-1]
    candidate_terminal = (
        unquote(candidate.path).casefold().rstrip("/").rsplit("/", 1)[-1]
    )
    return bool(
        target_host
        and target_host == candidate_host
        and target_terminal
        and target_terminal == candidate_terminal
    )


def is_product_group(obj: dict[str, Any]) -> bool:
    types = obj.get("@type") or obj.get("type")
    values = types if isinstance(types, list) else [types]
    return any(str(item).casefold() == "productgroup" for item in values)


def _variant_urls(row: dict[str, Any]) -> tuple[str, ...]:
    offers = row.get("offers")
    offer_rows = offers if isinstance(offers, list) else [offers]
    values = (
        row.get("url"),
        *(offer.get("url") for offer in offer_rows if isinstance(offer, dict)),
    )
    return tuple(
        dict.fromkeys(
            str(value).strip() for value in values if str(value or "").strip()
        )
    )
