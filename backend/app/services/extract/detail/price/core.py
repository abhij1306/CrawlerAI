from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    AVAILABILITY_OUT_OF_STOCK,
    DETAIL_CENT_BASED_PRICE_CURRENCY_SET,
    DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET,
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA,
    DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO,
    DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCE_SET,
    DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX_DECIMAL,
    DETAIL_STRICT_PARENT_PRICE_SOURCE_SET,
)
from app.services.extract.detail.price.parsing import (
    decimal_is_cent_magnitude_copy,
    detail_currency_from_html,
    detail_current_price_currency_from_html,
    detail_jsonld_price_bundle,
    detail_original_price_from_html,
    detail_price_decimal,
    detail_price_from_html,
    detail_price_from_selector_text,
    detail_price_is_visible_magnitude_copy,
    detail_price_is_cent_magnitude_copy,
    format_detail_price_decimal,
    format_price_decimal,
    single_decimal_value,
)
from app.services.shared.field_coerce import (
    extract_currency_code,
    text_or_none,
)
from app.services.shared.currency_hints import (
    currency_hint_from_page_url,
    detail_currency_hint_is_host_level,
)
from app.services.normalizers import normalize_decimal_price


def backfill_detail_price_from_html(
    record: dict[str, Any],
    *,
    html: str,
) -> None:
    selected_variant = record.get("selected_variant")
    record_price_is_low_signal = _detail_price_value_is_low_signal(record.get("price"))
    if not str(html or "").strip():
        return

    soup = BeautifulSoup(str(html or ""), "html.parser")
    jsonld_price_bundle = detail_jsonld_price_bundle(soup, currency=None)
    html_currency = detail_currency_from_html(
        soup,
        jsonld_price_bundle=jsonld_price_bundle,
    )
    record_url = text_or_none(record.get("url")) or ""
    expected_currency = text_or_none(currency_hint_from_page_url(record_url))
    preliminary_currency = (
        text_or_none(record.get("currency")) or expected_currency or html_currency
    )
    visible_price = detail_price_from_selector_text(
        soup,
        selectors=DETAIL_CURRENT_PRICE_SELECTORS,
        currency=preliminary_currency,
    )
    visible_price_currency = (
        detail_current_price_currency_from_html(soup) if visible_price else None
    )
    if visible_price_currency and text_or_none(record.get("currency")) not in (
        None,
        visible_price_currency,
    ):
        current_price = record.get("price")
        if (
            current_price in (None, "", [], {})
            or detail_price_decimal(current_price) == detail_price_decimal(visible_price)
            or _should_override_record_price_from_dom(
                record=record,
                dom_price=visible_price,
                record_price_is_low_signal=record_price_is_low_signal,
            )
        ):
            record["currency"] = visible_price_currency
            append_record_field_source(record, "currency", "dom_text")
    if visible_price_currency and html_currency and visible_price_currency != html_currency:
        html_currency = visible_price_currency
        jsonld_price_bundle = (None, None, None)
    html_currency_conflicts_with_host = _html_currency_conflicts_with_strong_host_hint(
        html_currency=html_currency,
        expected_currency=expected_currency,
        page_url=record_url,
    )
    unverified_localized_currency_conflict = bool(
        not visible_price
        and html_currency
        and expected_currency
        and html_currency != expected_currency
        and text_or_none(record.get("currency")) in (None, expected_currency)
    )
    if unverified_localized_currency_conflict:
        if not _should_preserve_existing_localized_money(
            record,
            expected_currency=expected_currency,
            jsonld_price=jsonld_price_bundle[0],
        ):
            _drop_unverified_localized_money(record)
        html_currency = None
        jsonld_price_bundle = (None, None, None)
    visible_currency_conflicts_with_html = bool(
        visible_price
        and html_currency
        and expected_currency
        and html_currency != expected_currency
    )
    if html_currency_conflicts_with_host:
        # JSON-LD/meta may stay on default-market currency while the rendered
        # PDP shows localized price. Ignore conflicting structured price, but
        # still allow visible DOM price or an existing parent price to repair
        # the record and nested variants.
        if _detail_price_value_is_low_signal(visible_price):
            visible_price = None
        html_currency = None
        jsonld_price_bundle = (None, None, None)

    currency = (
        text_or_none(record.get("currency"))
        or (
            expected_currency
            if html_currency_conflicts_with_host and visible_price
            else None
        )
        or html_currency
    )
    if currency and record.get("currency") in (None, "", [], {}):
        record["currency"] = currency
        append_record_field_source(record, "currency", "dom_text")

    if not html_currency_conflicts_with_host and currency != jsonld_price_bundle[2]:
        jsonld_price_bundle = detail_jsonld_price_bundle(soup, currency=currency)
    jsonld_price, jsonld_original_price, jsonld_currency = jsonld_price_bundle
    current_price_backfill_blocked = _unavailable_record_blocks_dom_price_backfill(
        record,
        jsonld_price=jsonld_price,
        visible_price=visible_price,
    )
    localized_override_price = _localized_visible_or_structured_price_override(
        record=record,
        visible_price=visible_price,
        jsonld_price=jsonld_price,
        jsonld_currency=jsonld_currency,
        expected_currency=expected_currency,
    )
    localized_override_applied = False
    price_source = ""
    if current_price_backfill_blocked:
        _drop_unavailable_dom_backfilled_detail_price(record)
    else:
        if html_currency_conflicts_with_host:
            price = visible_price or text_or_none(record.get("price"))
        else:
            price = jsonld_price or detail_price_from_html(
                soup,
                currency=currency,
                jsonld_price_bundle=jsonld_price_bundle,
            )
            if price in (None, "", [], {}):
                price = text_or_none(record.get("price"))
        price_source = "json_ld" if jsonld_price else "dom_text"
        if localized_override_price:
            price = localized_override_price
            price_source = (
                "dom_text" if visible_price == localized_override_price else "json_ld"
            )
            localized_override_applied = True
        if visible_price and (
            detail_price_is_visible_magnitude_copy(price, visible_price)
            or _should_override_record_price_from_dom(
                record=record,
                dom_price=visible_price,
                record_price_is_low_signal=record_price_is_low_signal,
            )
        ):
            price = visible_price
            price_source = "dom_text"
        if price in (None, "", [], {}):
            price = None
        if price not in (None, "", [], {}):
            if (
                price_source == "json_ld"
                and jsonld_currency
                and text_or_none(record.get("currency")) != jsonld_currency
            ):
                record["currency"] = jsonld_currency
                currency = jsonld_currency
                append_record_field_source(record, "currency", "json_ld")
            if (
                price_source == "json_ld"
                and price == jsonld_price
                and not (
                    record_field_sources(record, "price")
                    & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET
                )
            ):
                record["price"] = price
                append_record_field_source(record, "price", "json_ld")
            if (
                _should_override_record_price_from_dom(
                    record=record,
                    dom_price=price,
                    record_price_is_low_signal=record_price_is_low_signal,
                )
                or localized_override_applied
            ):
                record["price"] = price
                append_record_field_source(record, "price", price_source)
            if isinstance(selected_variant, dict) and (
                selected_variant.get("price") in (None, "", [], {})
                or _detail_price_value_is_low_signal(selected_variant.get("price"))
                or detail_price_is_cent_magnitude_copy(
                    selected_variant.get("price"), price
                )
            ):
                selected_variant["price"] = price
                if currency and selected_variant.get("currency") in (None, "", [], {}):
                    selected_variant["currency"] = currency
            variants = record.get("variants")
            if isinstance(variants, list):
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    if (
                        price_source == "json_ld"
                        and jsonld_currency
                        and _detail_price_is_visible_outlier(
                            variant.get("price"), price
                        )
                        and not (
                            record_field_sources(record, "variants")
                            & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET
                        )
                    ):
                        variant["price"] = price
                        variant["currency"] = jsonld_currency
                        continue
                    if (
                        variant.get("price") not in (None, "", [], {})
                        and not _detail_price_value_is_low_signal(variant.get("price"))
                        and not detail_price_is_cent_magnitude_copy(
                            variant.get("price"), price
                        )
                    ):
                        continue
                    variant["price"] = price
                    if currency and variant.get("currency") in (None, "", [], {}):
                        variant["currency"] = currency
            if localized_override_applied:
                _drop_unverified_variant_money(record)

    visible_original_price = detail_original_price_from_html(
        soup,
        currency=currency,
        jsonld_price_bundle=(None, None, None),
    )
    original_price = jsonld_original_price or visible_original_price
    if (
        localized_override_applied
        and price_source == "dom_text"
        and (
            visible_original_price in (None, "", [], {})
            or detail_price_decimal(visible_original_price)
            == detail_price_decimal(record.get("price"))
        )
    ):
        _drop_existing_original_price(record)
        original_price = None
    if (html_currency_conflicts_with_host or visible_currency_conflicts_with_html) and (
        original_price in (None, "", [], {})
        or detail_price_decimal(original_price)
        == detail_price_decimal(record.get("price"))
    ):
        _drop_conflicting_non_authoritative_original_price(record)
    if original_price not in (None, "", [], {}) and record.get("original_price") in (
        None,
        "",
        [],
        {},
    ):
        original_price_source = "json_ld" if jsonld_original_price else "dom_text"
        record["original_price"] = original_price
        append_record_field_source(record, "original_price", original_price_source)
        if (
            original_price_source == "json_ld"
            and jsonld_currency
            and record.get("currency") in (None, "", [], {})
        ):
            record["currency"] = jsonld_currency
            append_record_field_source(record, "currency", "json_ld")
    if (
        isinstance(selected_variant, dict)
        and original_price not in (None, "", [], {})
        and selected_variant.get("original_price") in (None, "", [], {})
    ):
        selected_variant["original_price"] = original_price
    _drop_unavailable_dom_backfilled_detail_price(record)


def _localized_visible_or_structured_price_override(
    *,
    record: dict[str, Any],
    visible_price: object,
    jsonld_price: object,
    jsonld_currency: str | None,
    expected_currency: str | None,
) -> str | None:
    if not expected_currency:
        return None
    current_sources = record_field_sources(record, "price")
    if not (current_sources & {"adapter", "js_state"}):
        return None
    if visible_price and _detail_price_is_visible_outlier(
        record.get("price"), visible_price
    ):
        return text_or_none(visible_price)
    if (
        jsonld_price
        and jsonld_currency == expected_currency
        and _detail_price_is_visible_outlier(record.get("price"), jsonld_price)
    ):
        return text_or_none(jsonld_price)
    return None


def _drop_unverified_variant_money(record: dict[str, Any]) -> None:
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        for field_name in ("price", "sale_price", "original_price", "currency"):
            selected_variant.pop(field_name, None)
    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        for field_name in ("price", "sale_price", "original_price", "currency"):
            variant.pop(field_name, None)


def _drop_existing_original_price(record: dict[str, Any]) -> None:
    record.pop("original_price", None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        field_sources.pop("original_price", None)


def _should_preserve_existing_localized_money(
    record: dict[str, Any],
    *,
    expected_currency: str | None,
    jsonld_price: object,
) -> bool:
    if not expected_currency:
        return False
    if text_or_none(record.get("currency")) != expected_currency:
        return False
    current_price = record.get("price")
    if current_price in (None, "", [], {}) or _detail_price_value_is_low_signal(
        current_price
    ):
        return False
    currency_sources = record_field_sources(record, "currency")
    if "url_currency_hint" in currency_sources:
        return True
    if jsonld_price in (None, "", [], {}):
        return True
    return _detail_price_is_visible_outlier(jsonld_price, current_price)


def _drop_unverified_localized_money(record: dict[str, Any]) -> None:
    for field_name in ("price", "sale_price", "original_price", "currency"):
        record.pop(field_name, None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        for field_name in ("price", "sale_price", "original_price", "currency"):
            field_sources.pop(field_name, None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        for field_name in ("price", "sale_price", "original_price", "currency"):
            selected_variant.pop(field_name, None)
    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            for field_name in ("price", "sale_price", "original_price", "currency"):
                variant.pop(field_name, None)


def _drop_conflicting_non_authoritative_original_price(record: dict[str, Any]) -> None:
    if record.get("original_price") in (None, "", [], {}):
        return
    original_sources = record_field_sources(record, "original_price")
    if original_sources & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET:
        return
    record.pop("original_price", None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        field_sources.pop("original_price", None)


def _unavailable_record_blocks_dom_price_backfill(
    record: dict[str, Any],
    *,
    jsonld_price: object,
    visible_price: object,
) -> bool:
    if text_or_none(record.get("availability")) != AVAILABILITY_OUT_OF_STOCK:
        return False
    if jsonld_price not in (None, "", [], {}):
        return False
    if visible_price not in (None, "", [], {}):
        return False
    return _price_sources_are_non_authoritative(record)


def _drop_unavailable_dom_backfilled_detail_price(record: dict[str, Any]) -> None:
    if text_or_none(record.get("availability")) != AVAILABILITY_OUT_OF_STOCK:
        return
    if not _price_sources_are_non_authoritative(record):
        return
    record.pop("price", None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        field_sources.pop("price", None)
    currency_sources = record_field_sources(record, "currency")
    if record.get("original_price") in (None, "", [], {}) and not (
        currency_sources & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET
    ):
        record.pop("currency", None)
        if isinstance(field_sources, dict):
            field_sources.pop("currency", None)


def _price_sources_are_non_authoritative(record: dict[str, Any]) -> bool:
    price_sources = record_field_sources(record, "price")
    return bool(price_sources) and not (
        price_sources & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET
    )


def drop_low_signal_zero_detail_price(record: dict[str, Any]) -> None:
    if not _price_value_is_zero(record.get("price")):
        return
    price_sources = record_field_sources(record, "price")
    if not _zero_detail_price_is_low_signal(record, price_sources=price_sources):
        return
    if _detail_record_has_positive_price_corroboration(record):
        return

    record.pop("price", None)
    field_sources = record.get("_field_sources")
    if isinstance(field_sources, dict):
        field_sources.pop("price", None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and _price_value_is_zero(
        selected_variant.get("price")
    ):
        selected_variant.pop("price", None)
        selected_variant.pop("currency", None)

    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict) or not _price_value_is_zero(
                variant.get("price")
            ):
                continue
            variant.pop("price", None)
            variant.pop("currency", None)

    currency_sources = record_field_sources(record, "currency")
    if record.get("original_price") not in (None, "", [], {}):
        return
    if (
        text_or_none(record.get("availability")) == AVAILABILITY_OUT_OF_STOCK
        or not currency_sources
        or currency_sources <= DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCE_SET
    ):
        record.pop("currency", None)
        if isinstance(field_sources, dict):
            field_sources.pop("currency", None)


def _zero_detail_price_is_low_signal(
    record: dict[str, Any],
    *,
    price_sources: set[str],
) -> bool:
    if text_or_none(record.get("availability")) == AVAILABILITY_OUT_OF_STOCK:
        return True
    return (
        bool(price_sources) and price_sources <= DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCE_SET
    )


def reconcile_detail_currency_with_url(
    record: dict[str, Any],
    *,
    page_url: str,
) -> None:
    expected_currency = text_or_none(currency_hint_from_page_url(page_url))
    if not expected_currency:
        return
    strong_host_hint = detail_currency_hint_is_host_level(
        page_url,
        expected_currency=expected_currency,
    )
    variant_currency = _unanimous_variant_currency(record)
    if (
        variant_currency
        and variant_currency != expected_currency
        and not strong_host_hint
    ):
        expected_currency = variant_currency
    before_currency = text_or_none(record.get("currency"))

    adapter_price = "adapter" in record_field_sources(record, "price")
    if not (
        strong_host_hint
        and adapter_price
        and before_currency is not None
        and before_currency != expected_currency
    ):
        _reconcile_container_currency(
            record,
            expected_currency=expected_currency,
            strong_host_hint=strong_host_hint,
        )
    if before_currency != text_or_none(record.get("currency")):
        append_record_field_source(record, "currency", "url_currency_hint")

    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        before_currency = text_or_none(selected_variant.get("currency"))
        _reconcile_container_currency(
            selected_variant,
            expected_currency=expected_currency,
            strong_host_hint=strong_host_hint,
        )
        if before_currency != text_or_none(selected_variant.get("currency")):
            append_record_field_source(
                record, "selected_variant.currency", "url_currency_hint"
            )

    variants = record.get("variants")
    adapter_variants = "adapter" in record_field_sources(record, "variants")
    if isinstance(variants, list):
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                before_currency = text_or_none(variant.get("currency"))
                if not (
                    strong_host_hint
                    and adapter_variants
                    and before_currency is not None
                    and before_currency != expected_currency
                ):
                    _reconcile_container_currency(
                        variant,
                        expected_currency=expected_currency,
                        strong_host_hint=strong_host_hint,
                    )
                if before_currency != text_or_none(variant.get("currency")):
                    append_record_field_source(
                        record,
                        f"variants[{index}].currency",
                        "url_currency_hint",
                    )


def _unanimous_variant_currency(record: dict[str, Any]) -> str:
    currencies: set[str] = set()
    for row in record.get("variants") or []:
        if not isinstance(row, dict):
            continue
        currency = extract_currency_code(row.get("currency"))
        if currency:
            currencies.add(currency)
    return next(iter(currencies)) if len(currencies) == 1 else ""


def reconcile_detail_price_magnitudes(record: dict[str, Any]) -> None:
    parent_price = detail_price_decimal(record.get("price"))
    variant_rows: list[tuple[str, dict[str, Any]]] = []
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        variant_rows.append(("selected_variant", selected_variant))
    variants = record.get("variants")
    if isinstance(variants, list):
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                variant_rows.append((f"variants[{index}]", variant))
    variant_prices: list[Decimal] = []
    for _path, row in variant_rows:
        row_price = detail_price_decimal(row.get("price"))
        if row_price is not None:
            variant_prices.append(row_price)
    safe_variant_price = single_decimal_value(variant_prices)
    if (
        parent_price is not None
        and safe_variant_price is not None
        and decimal_is_cent_magnitude_copy(parent_price, safe_variant_price)
        and not (
            record_field_sources(record, "price")
            & DETAIL_STRICT_PARENT_PRICE_SOURCE_SET
        )
    ):
        record["price"] = format_price_decimal(safe_variant_price)
        append_record_field_source(record, "price", "variant_price_magnitude")
        parent_price = safe_variant_price
    if parent_price is None:
        return
    for path, row in variant_rows:
        row_price = detail_price_decimal(row.get("price"))
        if row_price is None:
            continue
        if decimal_is_cent_magnitude_copy(row_price, parent_price):
            row["price"] = format_price_decimal(parent_price)
            append_record_field_source(
                record, f"{path}.price", "parent_price_magnitude"
            )


def reconcile_parent_price_against_variant_range(record: dict[str, Any]) -> None:
    """Repair parent ``price`` when every variant reports a single, different price.

    DQ-7 / 2026-05-04 gemini audit (Selfridges): parent price 190 while both
    variants (50ml, 100ml) report 310. The parent value was scraped from an
    unrelated DOM element. When all variant rows agree on a single positive
    price and the parent price falls within the same order of magnitude as
    that variant price (i.e. not a cents/units magnitude copy), adopt the
    unanimous variant price as the parent.

    Conservative by design:
      * only acts when ``_single_decimal_value`` yields a unique variant price;
      * skips only when the parent is far higher than the unanimous variant
        price, so cents-magnitude mismatches (100x) are still left to
        :func:`reconcile_detail_price_magnitudes`;
      * skips when the parent price came from an authoritative / strict
        source such as ``network_payload``;
      * skips when the parent equals the variant price.
    """
    parent_price = detail_price_decimal(record.get("price"))
    if parent_price is None or parent_price <= 0:
        return
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    variant_dicts = [variant for variant in variants if isinstance(variant, dict)]
    if not variant_dicts:
        return
    variant_prices: list[Decimal] = []
    for variant in variant_dicts:
        parsed_price = detail_price_decimal(variant.get("price"))
        if parsed_price is not None:
            variant_prices.append(parsed_price)
    if len(variant_prices) < len(variant_dicts):
        # At least one variant lacks a price; skip to avoid misjudging the
        # distribution.
        return
    unanimous_variant_price = single_decimal_value(variant_prices)
    if unanimous_variant_price is None or unanimous_variant_price <= 0:
        return
    if parent_price == unanimous_variant_price:
        return
    # Skip only when the parent is far above the unanimous variant price.
    # Lower parent values are safe repair candidates after the cent-magnitude
    # guard because variant unanimity is stronger evidence than a lone parent
    # scrape.
    if (
        parent_price > unanimous_variant_price
        and (parent_price / unanimous_variant_price)
        > DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX_DECIMAL
    ):
        return
    if record_field_sources(record, "price") & DETAIL_STRICT_PARENT_PRICE_SOURCE_SET:
        return
    record["price"] = format_price_decimal(unanimous_variant_price)
    append_record_field_source(record, "price", "variant_price_range")


def record_field_sources(record: dict[str, Any], field_name: str) -> set[str]:
    field_sources = record.get("_field_sources")
    if not isinstance(field_sources, dict):
        return set()
    source_values = field_sources.get(field_name)
    if not isinstance(source_values, list):
        return set()
    return {str(source).strip() for source in source_values if str(source).strip()}


def append_record_field_source(
    record: dict[str, Any],
    field_name: str,
    source: str,
) -> None:
    normalized_source = str(source).strip()
    if not normalized_source:
        return
    field_sources = record.setdefault("_field_sources", {})
    if not isinstance(field_sources, dict):
        return
    source_bucket = field_sources.setdefault(field_name, [])
    if not isinstance(source_bucket, list):
        return
    if normalized_source not in source_bucket:
        source_bucket.append(normalized_source)


def _should_override_record_price_from_dom(
    *,
    record: dict[str, Any],
    dom_price: object,
    record_price_is_low_signal: bool,
) -> bool:
    current_price = record.get("price")
    if current_price in (None, "", [], {}):
        return True
    if record_price_is_low_signal:
        return True
    if detail_price_is_visible_magnitude_copy(current_price, dom_price):
        return True
    if not _detail_price_is_visible_outlier(current_price, dom_price):
        return False
    current_sources = record_field_sources(record, "price")
    return not bool(current_sources & DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET)


def normalize_mismatched_host_currency_price(
    value: object,
    *,
    expected_currency: str,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    digits_only = re.sub(r"\D+", "", text)
    if "." in text or not digits_only or len(digits_only) < 4:
        return None
    normalized = normalize_decimal_price(
        text,
        interpret_integral_as_cents=expected_currency
        in DETAIL_CENT_BASED_PRICE_CURRENCY_SET,
    )
    if normalized and "." not in normalized:
        return f"{normalized}.00"
    return normalized


def _reconcile_container_currency(
    container: dict[str, Any],
    *,
    expected_currency: str,
    strong_host_hint: bool,
) -> None:
    actual_currency = text_or_none(container.get("currency"))
    has_price = container.get("price") not in (None, "", [], {})
    if not actual_currency:
        if has_price:
            container["currency"] = expected_currency
        return
    if actual_currency == expected_currency or not strong_host_hint:
        return

    corrected_price = normalize_mismatched_host_currency_price(
        container.get("price"),
        expected_currency=expected_currency,
    )
    if corrected_price:
        container["price"] = corrected_price
        container["currency"] = expected_currency
        return


def _html_currency_conflicts_with_strong_host_hint(
    *,
    html_currency: str | None,
    expected_currency: str | None,
    page_url: str,
) -> bool:
    return bool(
        html_currency
        and expected_currency
        and html_currency != expected_currency
        and detail_currency_hint_is_host_level(
            page_url,
            expected_currency=expected_currency,
        )
    )


def _price_value_is_zero(value: object) -> bool:
    normalized = detail_price_decimal(value)
    return normalized is not None and normalized == Decimal("0")


def _price_value_is_positive(value: object) -> bool:
    normalized = detail_price_decimal(value)
    return normalized is not None and normalized > Decimal("0")


def _detail_price_value_is_low_signal(value: object) -> bool:
    price = detail_price_decimal(value)
    if price is None:
        return False
    return Decimal("0") < price <= Decimal("1")


def _detail_price_is_visible_outlier(value: object, visible_value: object) -> bool:
    current = detail_price_decimal(value)
    visible = detail_price_decimal(visible_value)
    if current is None or visible is None or current <= 0 or visible <= 0:
        return False
    if detail_price_is_visible_magnitude_copy(current, visible):
        return True
    if visible <= current:
        return False
    if visible - current < Decimal(str(DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA)):
        return False
    return current <= visible * Decimal(str(DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO))


def _detail_record_has_positive_price_corroboration(record: dict[str, Any]) -> bool:
    if _price_value_is_positive(record.get("original_price")):
        return True
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and any(
        _price_value_is_positive(selected_variant.get(field_name))
        for field_name in ("price", "original_price")
    ):
        return True
    variants = record.get("variants")
    if not isinstance(variants, list):
        return False
    return any(
        isinstance(variant, dict)
        and any(
            _price_value_is_positive(variant.get(field_name))
            for field_name in ("price", "original_price")
        )
        for variant in variants
    )


__all__ = [
    "append_record_field_source",
    "backfill_detail_price_from_html",
    "currency_hint_from_page_url",
    "detail_currency_hint_is_host_level",
    "drop_low_signal_zero_detail_price",
    "format_detail_price_decimal",
    "normalize_mismatched_host_currency_price",
    "reconcile_detail_price_magnitudes",
    "reconcile_detail_currency_with_url",
    "reconcile_parent_price_against_variant_range",
    "record_field_sources",
    "detail_price_decimal",
]
