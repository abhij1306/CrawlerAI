from __future__ import annotations

__all__ = (
    "repair_detail_variant_prices_and_identity",
    "normalize_detail_money_precision",
    "drop_invalid_detail_discounts",
    "repair_invalid_original_prices",
)

import logging
import re
from decimal import Decimal
from typing import Any


from app.services.config.extraction_rules import (
    AVAILABILITY_IN_STOCK,
    DETAIL_LOW_SIGNAL_PARENT_MIN,
    DETAIL_LOW_SIGNAL_PRICE_MAX,
    DETAIL_PRICE_COMPARISON_TOLERANCE,
)
from app.services.shared.field_coerce import (
    clean_text,
    text_or_none,
)
from app.services.extract.detail.price.core import (
    detail_price_decimal,
    format_detail_price_decimal,
)
from app.services.extract.detail.assembly import (
    record_sanitization as _record_sanitization,
)
from app.services.extract.detail.variants import pruning as _variant_pruning

logger = logging.getLogger(__name__)

_looks_like_uuid = _record_sanitization._looks_like_uuid
_variant_title_is_low_signal = _variant_pruning._variant_title_is_low_signal
_variant_title_from_parent = _variant_pruning._variant_title_from_parent


def _repair_detail_variant_prices_and_identity(record: dict[str, Any]) -> None:
    parent_price = text_or_none(record.get("price"))
    parent_availability = text_or_none(record.get("availability"))
    parent_sku = text_or_none(record.get("sku"))
    parent_title = clean_text(record.get("title"))
    rows = [row for row in list(record.get("variants") or []) if isinstance(row, dict)]
    for row in rows:
        if parent_price:
            row_price = text_or_none(row.get("price"))
            if (
                not row_price
                or _price_is_cents_copy(row_price, parent_price)
                or _price_is_low_signal_copy(row_price, parent_price)
            ):
                row["price"] = parent_price
        if (
            parent_availability
            and row.get("availability") in (None, "", [], {})
            and any(
                row.get(field_name) not in (None, "", [], {})
                for field_name in (
                    "sku",
                    "variant_id",
                    "barcode",
                    "image_url",
                    "title",
                    "size",
                    "color",
                    "url",
                )
            )
        ):
            row["availability"] = parent_availability
        row_sku = text_or_none(row.get("sku"))
        if row_sku and _looks_like_uuid(row_sku):
            row.pop("sku", None)
        barcode = text_or_none(row.get("barcode"))
        if (
            barcode
            and row.get("sku") == barcode
            and len(re.sub(r"\D+", "", barcode)) <= 8
        ):
            row.pop("barcode", None)
        title = clean_text(row.get("title"))
        if title and _variant_title_is_low_signal(title):
            replacement = _variant_title_from_parent(parent_title, row)
            if replacement:
                row["title"] = replacement
            else:
                row.pop("title", None)
    variant_rows = [
        row for row in list(record.get("variants") or []) if isinstance(row, dict)
    ]
    if (
        parent_availability == AVAILABILITY_IN_STOCK
        and variant_rows
        and all(
            text_or_none(row.get("availability")) == parent_availability
            for row in variant_rows
        )
    ):
        for row in variant_rows:
            row.pop("availability", None)
    if parent_sku and _looks_like_uuid(parent_sku):
        record.pop("sku", None)


def repair_detail_variant_prices_and_identity(record: dict[str, Any]) -> None:
    _repair_detail_variant_prices_and_identity(record)


def _price_is_cents_copy(value: str, parent_price: str) -> bool:
    value_number = detail_price_decimal(value)
    parent_number = detail_price_decimal(parent_price)
    if value_number is None or parent_number is None or parent_number <= 0:
        return False
    return abs(value_number - (parent_number * 100)) < Decimal(
        str(DETAIL_PRICE_COMPARISON_TOLERANCE)
    )


def _price_is_low_signal_copy(value: str, parent_price: str) -> bool:
    value_number = detail_price_decimal(value)
    parent_number = detail_price_decimal(parent_price)
    if value_number is None or parent_number is None:
        return False
    return Decimal("0") < value_number <= Decimal(
        str(DETAIL_LOW_SIGNAL_PRICE_MAX)
    ) and parent_number >= Decimal(str(DETAIL_LOW_SIGNAL_PARENT_MIN))


def _normalize_detail_money_precision(record: dict[str, Any]) -> None:
    for container in _detail_money_containers(record):
        if not isinstance(container, dict):
            continue
        if not text_or_none(container.get("currency")):
            continue
        for field_name in ("price", "original_price"):
            normalized = _money_two_decimals(container.get(field_name))
            if normalized is not None:
                container[field_name] = normalized


def normalize_detail_money_precision(record: dict[str, Any]) -> None:
    _normalize_detail_money_precision(record)


def _detail_money_containers(record: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [record]
    variants = record.get("variants")
    if isinstance(variants, list):
        containers.extend(row for row in variants if isinstance(row, dict))
    return containers


def _money_two_decimals(value: object) -> str | None:
    text = text_or_none(value)
    if not text or not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return format_detail_price_decimal(text)


def _drop_invalid_detail_discounts(record: dict[str, Any]) -> None:
    price = detail_price_decimal(record.get("price"))
    original_price = detail_price_decimal(record.get("original_price"))
    discount_amount = detail_price_decimal(record.get("discount_amount"))
    discount_percentage = detail_price_decimal(record.get("discount_percentage"))
    if discount_percentage is not None and not (0 < discount_percentage <= 100):
        record.pop("discount_percentage", None)
    if discount_amount is None:
        return
    if discount_amount <= 0:
        record.pop("discount_amount", None)
        return
    if price is not None and discount_amount > price:
        record.pop("discount_amount", None)
        return
    if original_price is not None and discount_amount > original_price:
        record.pop("discount_amount", None)


def drop_invalid_detail_discounts(record: dict[str, Any]) -> None:
    _drop_invalid_detail_discounts(record)


def _repair_invalid_original_prices(record: dict[str, Any]) -> None:
    for container in _detail_money_containers(record):
        if not isinstance(container, dict):
            continue
        price = detail_price_decimal(container.get("price"))
        original_price = detail_price_decimal(container.get("original_price"))
        if price is None or original_price is None or original_price >= price:
            continue
        normalized_price = _money_two_decimals(container.get("price"))
        if normalized_price is not None:
            container["original_price"] = normalized_price


def repair_invalid_original_prices(record: dict[str, Any]) -> None:
    _repair_invalid_original_prices(record)
