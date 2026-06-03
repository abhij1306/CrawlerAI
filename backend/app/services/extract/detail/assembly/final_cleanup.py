from __future__ import annotations

__all__ = (
    "detail_image_matches_primary_family",
    "detail_title_looks_like_placeholder",
    "detail_title_from_url",
    "sanitize_variant_payload",
    "sanitize_variant_row",
    "repair_ecommerce_detail_record_quality",
)

from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    AVAILABILITY_IN_STOCK,
    AVAILABILITY_OUT_OF_STOCK,
    AVAILABILITY_UNKNOWN,
)
from app.services.extract.detail.identity.core import (
    detail_title_from_url,
)
from app.services.extract.variant_normalization.contract import (
    enforce_flat_variant_public_contract,
)
from app.services.shared.field_coerce import text_or_none
from app.services.extract.detail.images import cleanup as _image_cleanup
from app.services.extract.detail.price import money_repair as _money_repair
from app.services.extract.detail.assembly import (
    record_sanitization as _record_sanitization,
)
from app.services.extract.detail.variants import pruning as _variant_pruning
from app.services.extract.detail.variants.dom_extraction import (
    backfill_variants_from_dom_if_missing,
)
from app.services.extract.detail.variants.dom_availability import (
    reconcile_variant_availability_from_dom,
)
from app.services.extract.detail.variants.numbered_options import (
    hydrate_numbered_variant_options_from_dom,
)
from app.services.extract.detail.price.core import (
    backfill_detail_price_from_html,
    reconcile_detail_currency_with_url,
    reconcile_detail_price_magnitudes,
    reconcile_parent_price_against_variant_range,
)
from app.services.extract.detail.text.sanitizer import sanitize_detail_long_text_fields
from app.services.extract.variant_normalization import normalize_variant_record

detail_image_matches_primary_family = _image_cleanup.detail_image_matches_primary_family
detail_title_looks_like_placeholder = (
    _record_sanitization.detail_title_looks_like_placeholder
)
sanitize_variant_row = _variant_pruning.sanitize_variant_row


def sanitize_variant_payload(record: dict[str, Any], *, identity_url: str) -> None:
    _variant_pruning._sanitize_detail_variant_payload(
        record,
        identity_url=identity_url,
    )


def repair_ecommerce_detail_record_quality(
    record: dict[str, Any],
    *,
    html: str,
    page_url: str,
    requested_page_url: str | None = None,
    soup: Any | None = None,
    js_state_objects: object | None = None,
) -> None:
    _sanitize_ecommerce_detail_record(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
        soup=soup,
        js_state_objects=js_state_objects,
    )
    variant_parent_images = _variant_parent_image_values(record)
    variant_parent_image = text_or_none(record.get("image_url"))
    if variant_parent_image not in variant_parent_images:
        variant_parent_image = None
    variant_parent_availability = None
    field_sources = record.get("_field_sources")
    availability_sources = (
        field_sources.get("availability") if isinstance(field_sources, dict) else None
    )
    if isinstance(availability_sources, list) and "variant_parent_availability" in {
        str(source) for source in availability_sources
    }:
        variant_parent_availability = _variant_parent_availability_value(record)
        if record.get("availability") != variant_parent_availability:
            variant_parent_availability = None
    if (
        soup is None
        and not text_or_none(record.get("image_url"))
        and str(html or "").strip()
    ):
        parsed_soup = BeautifulSoup(str(html), "html.parser")
        _image_cleanup.backfill_detail_image_from_html(
            record,
            soup=parsed_soup,
            identity_url=text_or_none(requested_page_url) or page_url,
        )
        _image_cleanup.sanitize_detail_images(
            record,
            identity_url=text_or_none(requested_page_url) or page_url,
        )
    normalize_variant_record(record, finalize_contract=False)
    sanitize_variant_payload(
        record,
        identity_url=text_or_none(requested_page_url) or page_url,
    )
    _reconcile_variant_derived_parent_fields(
        record,
        variant_parent_image=variant_parent_image,
        variant_parent_availability=variant_parent_availability,
    )
    backfill_detail_price_from_html(record, html=html)
    reconcile_detail_currency_with_url(record, page_url=page_url)
    reconcile_detail_price_magnitudes(record)
    reconcile_parent_price_against_variant_range(record)
    _money_repair.normalize_detail_money_precision(record)
    _money_repair.repair_invalid_original_prices(record)
    _money_repair.drop_invalid_detail_discounts(record)
    _money_repair.repair_detail_variant_prices_and_identity(record)
    enforce_flat_variant_public_contract(record, page_url=page_url)


def _sanitize_ecommerce_detail_record(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None,
    soup: Any | None = None,
    js_state_objects: object | None = None,
) -> None:
    identity_url = text_or_none(requested_page_url) or page_url
    _record_sanitization.sanitize_detail_placeholder_scalars(
        record,
        identity_url=identity_url,
    )
    _record_sanitization.sanitize_detail_identity_scalars(
        record,
        identity_url=identity_url,
    )
    hydrate_numbered_variant_options_from_dom(record, soup=soup)
    if soup is not None:
        backfill_variants_from_dom_if_missing(
            record,
            soup=soup,
            page_url=page_url,
            js_state_objects=js_state_objects
            if isinstance(js_state_objects, dict)
            else None,
        )
        reconcile_variant_availability_from_dom(record, soup=soup)
        _image_cleanup.backfill_detail_image_from_html(
            record,
            soup=soup,
            identity_url=identity_url,
        )
    sanitize_variant_payload(
        record,
        identity_url=identity_url,
    )
    sanitize_detail_long_text_fields(
        record,
        title_hint=detail_title_from_url(identity_url),
    )
    _image_cleanup.sanitize_detail_images(record, identity_url=identity_url)
    _image_cleanup.backfill_parent_image_from_variants(record)
    _reconcile_detail_availability_from_variants(record)


def _reconcile_detail_availability_from_variants(record: dict[str, Any]) -> None:
    availability = _variant_parent_availability_value(record)
    if availability is None:
        return
    record["availability"] = availability
    field_sources = record.setdefault("_field_sources", {})
    if isinstance(field_sources, dict):
        field_sources["availability"] = ["variant_parent_availability"]


def _variant_parent_availability_value(record: dict[str, Any]) -> str | None:
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
    if not variants:
        return None
    values = {text_or_none(row.get("availability")) for row in variants}
    values.discard(None)
    if AVAILABILITY_IN_STOCK in values:
        return AVAILABILITY_IN_STOCK
    complete_variant_set = bool(
        record.get("variants_complete") or record.get("variant_rows_complete")
    )
    parent_is_out_of_stock = record.get("availability") == AVAILABILITY_OUT_OF_STOCK
    if values == {AVAILABILITY_OUT_OF_STOCK} and (
        complete_variant_set
        or parent_is_out_of_stock
        or _all_variants_have_zero_stock(variants)
    ):
        return AVAILABILITY_OUT_OF_STOCK
    if (
        values
        and values <= {AVAILABILITY_OUT_OF_STOCK, AVAILABILITY_UNKNOWN}
        and (complete_variant_set or parent_is_out_of_stock)
    ):
        return AVAILABILITY_OUT_OF_STOCK
    return None


def _all_variants_have_zero_stock(variants: list[dict[str, Any]]) -> bool:
    # Missing stock_quantity means unknown stock, not zero, so it blocks all-zero.
    return bool(variants) and all(
        row.get("stock_quantity") in (0, "0") for row in variants
    )


def _variant_parent_image_values(record: dict[str, Any]) -> set[str]:
    images: set[str] = set()
    for variant in record.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        image_url = text_or_none(variant.get("image_url"))
        if image_url:
            images.add(image_url)
    return images


def _reconcile_variant_derived_parent_fields(
    record: dict[str, Any],
    *,
    variant_parent_image: str | None,
    variant_parent_availability: str | None,
) -> None:
    if any(isinstance(row, dict) for row in record.get("variants") or []):
        _image_cleanup.backfill_parent_image_from_variants(record)
        _reconcile_detail_availability_from_variants(record)
        return
    if variant_parent_image and record.get("image_url") == variant_parent_image:
        record.pop("image_url", None)
    if (
        variant_parent_availability
        and record.get("availability") == variant_parent_availability
    ):
        record.pop("availability", None)
