from __future__ import annotations

__all__ = (
    "decimal_is_cent_magnitude_copy",
    "detail_currency_from_html",
    "detail_current_price_currency_from_html",
    "detail_jsonld_price_bundle",
    "detail_original_price_from_html",
    "detail_price_decimal",
    "detail_price_from_html",
    "detail_price_from_selector_text",
    "detail_price_is_visible_magnitude_copy",
    "detail_price_is_cent_magnitude_copy",
    "format_detail_price_decimal",
    "format_price_decimal",
    "single_decimal_value",
)

import json
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_CURRENCY_JSONLD_RE,
    DETAIL_CURRENCY_META_SELECTORS,
    DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS_NORMALIZED,
    DETAIL_JSONLD_CURRENCY_FIELDS,
    DETAIL_JSONLD_GRAPH_FIELDS,
    DETAIL_JSONLD_OFFER_FIELDS,
    DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_FIELDS,
    DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS,
    DETAIL_JSONLD_TYPE_FIELDS,
    DETAIL_ORIGINAL_PRICE_SELECTORS,
    DETAIL_PRICE_CENT_MAGNITUDE_RATIO_DECIMAL,
    DETAIL_PRICE_JSONLD_RE,
    DETAIL_PRICE_JSONLD_TYPE_RE,
    DETAIL_PRICE_MAGNITUDE_EPSILON_DECIMAL,
    DETAIL_PRICE_META_SELECTORS,
    DETAIL_RELATED_PRICE_CONTEXT_TOKENS,
    DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS_DECIMAL,
)
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import extract_currency_code, text_or_none


def detail_price_from_html(
    soup: BeautifulSoup,
    *,
    currency: str | None,
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    jsonld_price, _jsonld_original_price, _jsonld_currency = jsonld_price_bundle
    if jsonld_price:
        return jsonld_price
    for selector in DETAIL_PRICE_META_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        raw_value = node.get("content") if hasattr(node, "get") else None
        if raw_value in (None, "", [], {}):
            raw_value = node.get_text(" ", strip=True)
        normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
        if normalized:
            return normalized
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text or '"price"' not in script_text.lower():
            continue
        if DETAIL_PRICE_JSONLD_TYPE_RE.search(script_text) is None:
            continue
        match = DETAIL_PRICE_JSONLD_RE.search(script_text)
        if match is None:
            continue
        normalized = _normalize_detail_price_candidate(
            match.group("price"),
            currency=currency,
        )
        if normalized:
            return normalized
    return detail_price_from_selector_text(
        soup,
        selectors=DETAIL_CURRENT_PRICE_SELECTORS,
        currency=currency,
    )


def detail_original_price_from_html(
    soup: BeautifulSoup,
    *,
    currency: str | None,
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    _jsonld_price, jsonld_original_price, _jsonld_currency = jsonld_price_bundle
    if jsonld_original_price:
        return jsonld_original_price
    return detail_price_from_selector_text(
        soup,
        selectors=DETAIL_ORIGINAL_PRICE_SELECTORS,
        currency=currency,
        skip_related_offer=True,
    )


def detail_price_from_selector_text(
    soup: BeautifulSoup,
    *,
    selectors: tuple[str, ...],
    currency: str | None,
    skip_related_offer: bool = True,
) -> str | None:
    for selector in selectors:
        for node in soup.select(selector):
            if _price_node_looks_like_installment(node):
                continue
            if skip_related_offer and _price_node_looks_like_related_offer(node):
                continue
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
            if normalized:
                return normalized
    return None


def detail_currency_from_html(
    soup: BeautifulSoup,
    *,
    jsonld_price_bundle: tuple[str | None, str | None, str | None],
) -> str | None:
    _jsonld_price, _jsonld_original_price, jsonld_currency = jsonld_price_bundle
    if jsonld_currency:
        return jsonld_currency
    for selector in DETAIL_CURRENCY_META_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        currency = text_or_none(node.get("content") if hasattr(node, "get") else None)
        if currency:
            return currency
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text:
            continue
        match = DETAIL_CURRENCY_JSONLD_RE.search(script_text)
        if match is not None:
            return text_or_none(match.group("currency"))
    return _first_currency_from_price_selectors(
        soup,
        (*DETAIL_CURRENT_PRICE_SELECTORS, *DETAIL_ORIGINAL_PRICE_SELECTORS),
    )


def detail_current_price_currency_from_html(soup: BeautifulSoup) -> str | None:
    return _first_currency_from_price_selectors(soup, DETAIL_CURRENT_PRICE_SELECTORS)


def _first_currency_from_price_selectors(
    soup: BeautifulSoup,
    selectors: tuple[str, ...],
) -> str | None:
    for selector in selectors:
        for node in soup.select(selector):
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            currency = extract_currency_code(raw_value)
            if currency:
                return currency
    return None


def detail_jsonld_price_bundle(
    soup: BeautifulSoup,
    *,
    currency: str | None,
) -> tuple[str | None, str | None, str | None]:
    saved_currency = text_or_none(currency)
    for offer in _iter_jsonld_offers(soup):
        offer_currency = _first_text(offer, DETAIL_JSONLD_CURRENCY_FIELDS) or currency
        saved_currency = text_or_none(offer_currency) or saved_currency
        price = _first_normalized_price(
            offer,
            DETAIL_JSONLD_PRICE_FIELDS,
            currency=offer_currency,
        )
        original_price = _first_normalized_price(
            offer,
            DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS,
            currency=offer_currency,
        )
        spec_original = _price_from_jsonld_specifications(
            offer,
            currency=offer_currency,
            current_price=price,
        )
        original_price = spec_original or original_price
        if price:
            price = format_detail_price_decimal(price) or price
        if original_price:
            original_price = format_detail_price_decimal(original_price) or original_price
        if price or original_price:
            return price, original_price, text_or_none(offer_currency)
    return None, None, saved_currency


def detail_price_decimal(value: object) -> Decimal | None:
    normalized = _normalized_price_value(value)
    if not normalized:
        return None
    try:
        return Decimal(str(normalized))
    except (InvalidOperation, ValueError):
        return None


def format_price_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def format_detail_price_decimal(value: object) -> str | None:
    price = detail_price_decimal(value)
    if price is None:
        return None
    return format_price_decimal(price)


def detail_price_is_cent_magnitude_copy(value: object, reference: object) -> bool:
    value_decimal = detail_price_decimal(value)
    reference_decimal = detail_price_decimal(reference)
    return bool(
        value_decimal is not None
        and reference_decimal is not None
        and decimal_is_cent_magnitude_copy(value_decimal, reference_decimal)
    )


def detail_price_is_visible_magnitude_copy(value: object, reference: object) -> bool:
    value_decimal = detail_price_decimal(value)
    reference_decimal = detail_price_decimal(reference)
    return bool(
        value_decimal is not None
        and reference_decimal is not None
        and decimal_is_visible_magnitude_copy(value_decimal, reference_decimal)
    )


def decimal_is_cent_magnitude_copy(value: Decimal, reference: Decimal) -> bool:
    if value <= 0 or reference <= 0:
        return False
    return (
        abs(value - (reference * DETAIL_PRICE_CENT_MAGNITUDE_RATIO_DECIMAL))
        <= DETAIL_PRICE_MAGNITUDE_EPSILON_DECIMAL
    )


def decimal_is_visible_magnitude_copy(value: Decimal, reference: Decimal) -> bool:
    if value <= 0 or reference <= 0:
        return False
    return any(
        abs(value - (reference * ratio)) <= DETAIL_PRICE_MAGNITUDE_EPSILON_DECIMAL
        for ratio in DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS_DECIMAL
    )


def single_decimal_value(values: list[Decimal]) -> Decimal | None:
    unique = {format_price_decimal(value) for value in values if value > 0}
    if len(unique) != 1:
        return None
    return Decimal(next(iter(unique)))


def _price_node_looks_like_installment(node: object) -> bool:
    text_parts: list[str] = []
    if node is None:
        return False
    if hasattr(node, "get_text"):
        text_parts.append(node.get_text(" ", strip=True))
    if hasattr(node, "get"):
        for attr_name in ("aria-label",):
            raw = node.get(attr_name)
            if isinstance(raw, list):
                text_parts.extend(str(item) for item in raw)
            elif raw not in (None, "", [], {}):
                text_parts.append(str(raw))
    lowered = " ".join(text_parts).lower()
    return any(token in lowered for token in DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS_NORMALIZED)


def _price_node_looks_like_related_offer(node: object) -> bool:
    current = node
    depth = 0
    while current is not None and depth < 4:
        attrs = getattr(current, "attrs", {}) or {}
        context = " ".join(
            str(value)
            for key, value in attrs.items()
            if key in {"class", "id", "data-testid", "data-test", "aria-label"}
        ).lower()
        if any(token in context for token in DETAIL_RELATED_PRICE_CONTEXT_TOKENS):
            return True
        current = current.find_parent() if hasattr(current, "find_parent") else None
        depth += 1
    return False


def _iter_jsonld_offers(soup: BeautifulSoup) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for payload in _iter_jsonld_payloads(soup):
        offers.extend(_offers_from_jsonld_node(payload))
    return offers


def _iter_jsonld_payloads(soup: BeautifulSoup) -> list[Any]:
    payloads: list[Any] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text:
            continue
        try:
            payloads.append(json.loads(script_text))
        except json.JSONDecodeError:
            continue
    return payloads


def _offers_from_jsonld_node(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            results.extend(_offers_from_jsonld_node(item))
        return results
    if not isinstance(value, dict):
        return []
    for field_name in DETAIL_JSONLD_GRAPH_FIELDS:
        results.extend(_offers_from_jsonld_node(value.get(field_name)))
    node_type = _jsonld_type_text(value)
    if node_type in {"offer", "aggregateoffer"}:
        results.append(value)
    for field_name in DETAIL_JSONLD_OFFER_FIELDS:
        results.extend(_offers_from_jsonld_node(value.get(field_name)))
    return results


def _jsonld_type_text(value: dict[str, Any]) -> str:
    for field_name in DETAIL_JSONLD_TYPE_FIELDS:
        raw_type = value.get(field_name)
        if isinstance(raw_type, list):
            raw_type = next((item for item in raw_type if text_or_none(item)), None)
        text = text_or_none(raw_type)
        if text:
            return text.rsplit("/", 1)[-1].lower()
    return ""


def _first_text(value: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        text = text_or_none(value.get(field_name))
        if text:
            return text
    return None


def _first_normalized_price(
    value: dict[str, Any],
    field_names: tuple[str, ...],
    *,
    currency: str | None,
) -> str | None:
    for field_name in field_names:
        normalized = _normalize_detail_price_candidate(
            value.get(field_name),
            currency=currency,
        )
        if normalized:
            return normalized
    return None


def _price_from_jsonld_specifications(
    offer: dict[str, Any],
    *,
    currency: str | None,
    current_price: str | None,
) -> str | None:
    specs: list[Any] = []
    for field_name in DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS:
        raw_specs = offer.get(field_name)
        if isinstance(raw_specs, list):
            specs.extend(raw_specs)
        elif raw_specs not in (None, "", [], {}):
            specs.append(raw_specs)
    current = detail_price_decimal(current_price)
    candidates: list[Decimal] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        price = detail_price_decimal(
            _first_normalized_price(spec, DETAIL_JSONLD_PRICE_FIELDS, currency=currency)
        )
        if price is None:
            continue
        if current is None or price > current:
            candidates.append(price)
    if not candidates:
        return None
    return format_price_decimal(max(candidates))


def _normalize_detail_price_candidate(
    value: object,
    *,
    currency: str | None,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    if (
        currency
        and re.fullmatch(r"\d+(?:\.\d+)?", text)
        and "." not in text
        and len(re.sub(r"\D+", "", text)) <= 3
    ):
        return text
    return normalize_decimal_price(text, interpret_integral_as_cents=False)


def _normalized_price_value(value: object) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return text
    return normalize_decimal_price(text, interpret_integral_as_cents=False)
