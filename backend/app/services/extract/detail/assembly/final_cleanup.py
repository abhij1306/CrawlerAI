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
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
    if not variants:
        return
    values = {text_or_none(row.get("availability")) for row in variants}
    values.discard(None)
    parent_availability = text_or_none(record.get("availability"))
    if AVAILABILITY_IN_STOCK in values:
        record["availability"] = AVAILABILITY_IN_STOCK
    elif (
        parent_availability in (None, "", AVAILABILITY_UNKNOWN)
        and values
        and values <= {AVAILABILITY_OUT_OF_STOCK, AVAILABILITY_UNKNOWN}
    ):
        record["availability"] = AVAILABILITY_OUT_OF_STOCK
