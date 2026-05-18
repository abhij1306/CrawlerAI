from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    public_variant_axis_fields,
)
from app.services.shared.field_coerce import (
    absolute_url,
    coerce_field_value,
    coerce_text,
    text_or_none,
)

from .structured_values import _coerce_structured_candidate_value

_OFFER_TITLE_SIZE_RE = re.compile(
    r"(?:^|[,\s])(\d+(?:\.\d+)?\s*-?\s*(?:lb|lbs|oz|kg|g|ml|l|ct|count|pack|pk|bag|bags))\b",
    re.I,
)


def _variant_url_from_id(page_url: str, variant_id: str) -> str:
    parsed = urlparse(page_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "variant"
    ]
    query.append(("variant", variant_id))
    composed = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    return composed if parsed.scheme and parsed.netloc else absolute_url(page_url, composed) or ""


def _structured_variant_rows(
    variants: object, page_url: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in variants if isinstance(variants, list) else []:
        if not isinstance(item, dict):
            continue
        offer = item.get("offers")
        offer = offer[0] if isinstance(offer, list) and offer else offer
        availability_source = (
            offer if isinstance(offer, dict) else item.get("availability")
        )
        row: dict[str, object] = {}
        sku = coerce_text(item.get("sku"))
        if sku:
            row["sku"] = sku
        gtin = coerce_text(item.get("gtin13") or item.get("gtin") or item.get("gtin14"))
        if gtin:
            row["barcode"] = gtin
        title = coerce_text(item.get("name"))
        if title:
            row["title"] = title
        color = coerce_field_value("color", item.get("color"), page_url)
        if color:
            row["color"] = color
        size = coerce_field_value("size", item.get("size"), page_url)
        if size:
            row["size"] = size
        price = coerce_field_value("price", offer or item, page_url)
        if price not in (None, "", [], {}):
            row["price"] = price
        availability = coerce_field_value("availability", availability_source, page_url)
        if availability not in (None, "", [], {}):
            row["availability"] = availability
        image_url = coerce_field_value("image_url", item.get("image"), page_url)
        if image_url not in (None, "", [], {}):
            row["image_url"] = image_url
        variant_url = coerce_field_value("url", offer or item, page_url)
        if variant_url not in (None, "", [], {}):
            row["url"] = variant_url
        option_values: dict[str, object] = {}
        if color:
            option_values["color"] = color
        if size:
            option_values["size"] = size
        # Schema.org additionalProperty: captures material, style, scent, weight, etc.
        additional_props = item.get("additionalProperty")
        if isinstance(additional_props, list):
            for prop in additional_props:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value"):
                    axis_key = normalized_variant_axis_key(prop["name"])
                    if axis_key:
                        option_values[axis_key] = str(prop["value"]).strip()
        if option_values:
            row["option_values"] = option_values
        if row:
            rows.append(row)
    return rows


def _structured_offer_variant_rows(
    offers: object, page_url: str
) -> list[dict[str, object]]:
    raw_offers = offers if isinstance(offers, list) else []
    if len(raw_offers) < 2:
        return []
    rows: list[dict[str, object]] = []
    for item in raw_offers:
        if not isinstance(item, dict):
            continue
        row: dict[str, object] = {}
        offered_item = item.get("itemOffered")
        offered_item = offered_item if isinstance(offered_item, dict) else {}
        title = coerce_text(item.get("name") or offered_item.get("name"))
        if title:
            row["title"] = title
            title_size = _offer_title_size(title)
            if title_size:
                row["size"] = title_size
            scent = _offer_title_scent(title, item, page_url)
            if scent:
                row["scent"] = scent
        sku = coerce_text(item.get("sku") or offered_item.get("sku"))
        if sku:
            row["sku"] = sku
        price = coerce_field_value("price", item, page_url)
        if price not in (None, "", [], {}):
            row["price"] = price
        currency = coerce_field_value("currency", item, page_url)
        if currency not in (None, "", [], {}):
            row["currency"] = currency
        availability = coerce_field_value("availability", item, page_url)
        if availability not in (None, "", [], {}):
            row["availability"] = availability
        image_url = coerce_field_value(
            "image_url",
            item.get("image") or offered_item.get("image"),
            page_url,
        )
        if image_url not in (None, "", [], {}):
            row["image_url"] = image_url
        variant_url = coerce_field_value("url", item, page_url)
        if variant_url not in (None, "", [], {}):
            row["url"] = variant_url
        option_values: dict[str, object] = {}
        if row.get("size"):
            option_values["size"] = row["size"]
        if row.get("scent"):
            option_values["scent"] = row["scent"]
        if option_values:
            row["option_values"] = option_values
        if row.get("url") or row.get("price"):
            rows.append(row)
    return rows


def _offer_title_size(title: str) -> str:
    match = _OFFER_TITLE_SIZE_RE.search(title)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).lower()


def _offer_title_scent(
    title: str,
    offer: dict[str, object],
    page_url: str,
) -> str:
    probe = " ".join(
        text
        for text in (
            title,
            text_or_none(offer.get("url")),
            page_url,
        )
        if text
    ).casefold()
    if not any(token in probe for token in ("scent", "fragrance", "body mist", "body-mist")):
        return ""
    parts = re.split(r"\s[-–—]\s", title, maxsplit=1)
    if len(parts) != 2:
        return ""
    value = text_or_none(parts[1])
    return value or ""


def _variant_axes_from_rows(variants: list[dict[str, object]]) -> dict[str, list[str]]:
    axes: dict[str, list[str]] = {}
    for row in variants:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, axis_value in option_values.items():
                cleaned = text_or_none(axis_value)
                if not cleaned:
                    continue
                axes.setdefault(str(axis_name), [])
                if cleaned not in axes[str(axis_name)]:
                    axes[str(axis_name)].append(cleaned)
        for axis_name in ("color", "size", "style", "material", "scent", "flavor"):
            cleaned = text_or_none(row.get(axis_name))
            if not cleaned:
                continue
            axes.setdefault(axis_name, [])
            if cleaned not in axes[axis_name]:
                axes[axis_name].append(cleaned)
    return axes


def _variation_attribute_labels(
    payload: dict[str, object],
) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    raw_attributes = payload.get("variationAttributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = payload.get("variation_attributes")
    for attribute in raw_attributes if isinstance(raw_attributes, list) else []:
        if not isinstance(attribute, dict):
            continue
        axis_key = normalized_variant_axis_key(
            attribute.get("id") or attribute.get("name") or attribute.get("label")
        )
        values = attribute.get("values")
        if not axis_key or not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            raw_value = text_or_none(item.get("value") or item.get("id"))
            display = text_or_none(
                item.get("name")
                or item.get("displayValue")
                or item.get("display_value")
                or item.get("label")
            )
            if raw_value and display:
                labels.setdefault(axis_key, {})[raw_value] = display
    return labels


def _public_variant_axis_key(value: object) -> str:
    axis_key = normalized_variant_axis_key(value)
    return axis_key if axis_key in public_variant_axis_fields else ""


def _structured_product_option_names(payload: dict[str, object]) -> list[str]:
    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        return []
    names: list[str] = []
    for item in raw_options:
        if isinstance(item, dict):
            name = text_or_none(item.get("name") or item.get("title") or item.get("label"))
        else:
            name = text_or_none(item)
        if name:
            names.append(name)
    return names


def _structured_selected_option_values(
    item: dict[str, object],
    *,
    labels: dict[str, dict[str, str]],
) -> dict[str, str]:
    raw_selected = item.get("selectedOptions")
    if not isinstance(raw_selected, list):
        raw_selected = item.get("selected_options")
    if not isinstance(raw_selected, list):
        return {}
    option_values: dict[str, str] = {}
    for selected in raw_selected:
        if not isinstance(selected, dict):
            continue
        axis_key = _public_variant_axis_key(
            selected.get("name") or selected.get("option") or selected.get("label")
        )
        cleaned = text_or_none(
            selected.get("value") or selected.get("displayValue") or selected.get("label")
        )
        if not axis_key or not cleaned:
            continue
        option_values[axis_key] = labels.get(axis_key, {}).get(cleaned, cleaned)
    return option_values


def _structured_option_index_values(
    item: dict[str, object],
    *,
    option_names: list[str],
) -> dict[str, str]:
    if not option_names:
        return {}
    option_values: dict[str, str] = {}
    for index, option_name in enumerate(option_names, start=1):
        axis_key = _public_variant_axis_key(option_name)
        cleaned = text_or_none(item.get(f"option{index}"))
        if not axis_key or not cleaned:
            continue
        option_values[axis_key] = cleaned
    return option_values


def _structured_variant_option_values(
    item: dict[str, object],
    *,
    payload: dict[str, object],
    labels: dict[str, dict[str, str]],
) -> dict[str, str]:
    variation_values = item.get("variationValues")
    if not isinstance(variation_values, dict):
        variation_values = item.get("variation_values")
    if isinstance(variation_values, dict):
        option_values: dict[str, str] = {}
        for axis_name, raw_value in variation_values.items():
            axis_key = _public_variant_axis_key(axis_name)
            cleaned = text_or_none(raw_value)
            if not axis_key or not cleaned:
                continue
            option_values[axis_key] = labels.get(axis_key, {}).get(cleaned, cleaned)
        if option_values:
            return option_values
    if option_values := _structured_selected_option_values(item, labels=labels):
        return option_values
    return _structured_option_index_values(
        item,
        option_names=_structured_product_option_names(payload),
    )


def _structured_variants_from_product_payload(
    payload: dict[str, object],
    page_url: str,
) -> list[dict[str, object]]:
    raw_variants = payload.get("variants")
    if not isinstance(raw_variants, list):
        return []
    labels = _variation_attribute_labels(payload)
    rows: list[dict[str, object]] = []
    for item in raw_variants:
        if not isinstance(item, dict):
            continue
        option_values = _structured_variant_option_values(
            item,
            payload=payload,
            labels=labels,
        )
        if not option_values:
            continue
        row: dict[str, object] = {"option_values": option_values}
        sku = text_or_none(
            item.get("sku") or item.get("productId") or item.get("product_id")
        )
        if sku:
            row["sku"] = sku
        variant_id = text_or_none(
            item.get("id") or item.get("productId") or item.get("product_id")
        )
        if variant_id:
            row["variant_id"] = variant_id
        price = _coerce_structured_candidate_value(
            "price",
            item.get("price"),
            page_url=page_url,
            payload=payload,
            source_key="price",
        )
        if price not in (None, "", [], {}):
            row["price"] = price
        availability = coerce_field_value(
            "availability",
            item.get("availability")
            if item.get("availability") not in (None, "", [], {})
            else item.get("available")
            if item.get("available") not in (None, "", [], {})
            else item.get("availableForSale"),
            page_url,
        )
        if availability not in (None, "", [], {}):
            row["availability"] = availability
        image_url = coerce_field_value(
            "image_url",
            item.get("image") or item.get("featured_image") or item.get("featuredImage"),
            page_url,
        )
        if image_url not in (None, "", [], {}):
            row["image_url"] = image_url
        variant_url = coerce_field_value("url", item.get("url"), page_url)
        if variant_url in (None, "", [], {}) and variant_id:
            variant_url = _variant_url_from_id(page_url, variant_id)
        if variant_url not in (None, "", [], {}):
            row["url"] = variant_url
        for axis_key, axis_value in option_values.items():
            if axis_key in public_variant_axis_fields:
                row[axis_key] = axis_value
        rows.append(row)
    return rows
