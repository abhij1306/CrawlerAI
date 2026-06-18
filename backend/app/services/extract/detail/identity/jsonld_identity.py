from __future__ import annotations

from bs4 import BeautifulSoup

__all__ = [
    "jsonld_item_candidate_record",
    "jsonld_item_product_name",
    "jsonld_item_supports_identity",
    "jsonld_items",
    "prune_duplicate_product_headings",
]

_JSONLD_IDENTITY_FIELDS = (
    "name",
    "offers",
    "sku",
    "mpn",
    "productId",
    "productID",
    "gtin",
    "gtin8",
    "gtin12",
    "gtin13",
    "gtin14",
)


def _jsonld_item_has_identity_fields(item: dict[str, object]) -> bool:
    return any(key in item for key in _JSONLD_IDENTITY_FIELDS)


def _jsonld_graph_items(item: dict[str, object]) -> list[object]:
    items: list[object] = []
    if _jsonld_item_has_identity_fields(item):
        items.append(item)
    graph = item.get("@graph")
    if isinstance(graph, list):
        return items + list(graph)
    if isinstance(graph, dict):
        return items + [graph]
    if "@graph" in item:
        return items
    return items or [item]


def jsonld_items(payload: object) -> list[object]:
    if isinstance(payload, list):
        items: list[object] = []
        for item in payload:
            items.extend(_jsonld_graph_items(item) if isinstance(item, dict) else [item])
        return items
    if isinstance(payload, dict):
        return _jsonld_graph_items(payload)
    return []


def jsonld_item_supports_identity(item: dict[str, object]) -> bool:
    return _jsonld_item_has_identity_fields(item)


def jsonld_item_product_name(item: dict[str, object]) -> str:
    raw_name = item.get("name")
    return raw_name.strip() if isinstance(raw_name, str) else ""


def jsonld_item_candidate_record(item: dict[str, object]) -> dict[str, object]:
    barcode = (
        item.get("gtin")
        or item.get("gtin8")
        or item.get("gtin12")
        or item.get("gtin13")
        or item.get("gtin14")
    )
    return {
        "title": item.get("name") or item.get("title"),
        "url": item.get("url") or item.get("@id"),
        "sku": item.get("sku"),
        "product_id": item.get("productId") or item.get("productID"),
        "part_number": item.get("mpn"),
        "barcode": barcode,
        "brand": item.get("brand"),
        "color": item.get("color"),
        "size": item.get("size"),
        "description": item.get("description"),
    }


def prune_duplicate_product_headings(
    soup: BeautifulSoup,
    *,
    pruned_product_names: list[str],
) -> None:
    def _norm(value: str) -> str:
        return " ".join(value.lower().split())

    pruned_norms = {_norm(name) for name in pruned_product_names if name}
    for h1 in list(soup.find_all("h1")):
        h1_text = _norm(h1.get_text(separator=" ", strip=True))
        if h1_text and h1_text in pruned_norms:
            h1.decompose()
