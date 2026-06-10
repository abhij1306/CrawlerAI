from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(slots=True)
class ContradictionFlag:
    field: str
    source_a: str
    value_a: str
    source_b: str
    value_b: str


def detect_contradictions(packet: Any) -> list[ContradictionFlag]:
    flags: list[ContradictionFlag] = []
    product = packet.jsonld_product_blocks[0] if packet.jsonld_product_blocks else {}
    _maybe_add_text(
        flags,
        "availability",
        _availability(_offer_value(product, "availability")),
        "dom",
        _availability(packet.dom_fields.get("availability", "")),
    )
    _maybe_add_text(
        flags,
        "title",
        _text(product.get("name")),
        "og",
        _text(packet.og_tags.get("og:title") or packet.og_tags.get("name")),
    )
    return flags


def _maybe_add_text(
    flags: list[ContradictionFlag],
    field: str,
    value_a: str,
    source_b: str,
    value_b: str,
) -> None:
    if not value_a or not value_b:
        return
    left = _normalized(value_a)
    right = _normalized(value_b)
    if field == "title" and (left in right or right in left):
        return
    if left != right:
        flags.append(ContradictionFlag(field, "jsonld", value_a, source_b, value_b))


def _offer_value(product: dict[str, Any], key: str) -> str:
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if isinstance(offer, dict):
        return _text(offer.get(key))
    return _text(product.get(key))


def _availability(value: object) -> str:
    text = _text(value).lower()
    if "outofstock" in text or "out of stock" in text or "sold out" in text:
        return "out_of_stock"
    if "instock" in text or "in stock" in text or "available" in text:
        return "in_stock"
    return text


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _text(value).lower())).strip()


def _text(value: object) -> str:
    return str(value or "").strip()
