"""Value transforms shared by the mechanical recipe executor."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.config.extraction_rules import (
    LISTING_MARKET_LOCALE_GENDER_SEGMENTS,
    LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
    LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS,
)
from app.core.config.locale_format_rules import (
    currency_hint_from_page_url,
    locale_hint_from_page_url,
    parse_money,
)
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.recipe_contracts import RecipeBinding
from app.core.records.normalizers import normalize_decimal_price, normalize_value
from app.core.records.url_identity import detail_title_from_url
from app.core.shared.field_coerce_price import extract_currency_code
from app.core.shared.text_coerce import clean_text, strip_html_tags
from app.core.shared.url_utils import largest_srcset_url, public_asset_delivery_url
from app.extraction.contracts import ExtractionRequest

ValueTransform = Callable[[Any], Any]
ContextTransform = Callable[[ExtractionRequest, Any], Any]
PrefixTransform = Callable[[Any, str], Any]


def transform_value(
    request: ExtractionRequest, value: Any, binding: RecipeBinding
) -> Any:
    transform = binding.transform or ""
    if transform == "identity":
        return value
    context_handler = _CONTEXT_TRANSFORMS.get(transform)
    value_handler = _VALUE_TRANSFORMS.get(transform)
    if context_handler is not None:
        value = context_handler(request, value)
    elif value_handler is not None:
        value = value_handler(value)
    else:
        value = _parameterized_transform(value, transform)
    return _normalize_field(request, value, binding)


def url_component(url: str, component: str) -> str | None:
    parsed = urlsplit(url)
    components = {"final_url": url, "path": parsed.path, "host": parsed.hostname}
    if component in components:
        return components[component]
    if component.startswith("query."):
        values = parse_qs(parsed.query).get(component.removeprefix("query."), ())
        return next(iter(values), None)
    return None


def _parameterized_transform(value: Any, transform: str) -> Any:
    for prefix, handler in _PREFIX_TRANSFORMS.items():
        if transform.startswith(prefix):
            return handler(value, transform.removeprefix(prefix))
    return value


def _normalize_field(
    request: ExtractionRequest, value: Any, binding: RecipeBinding
) -> Any:
    field = binding.field
    if field in {"url", "apply_url", "image_url", "additional_images"} and isinstance(
        value, str
    ):
        value = urljoin(request.capture.final_url, value)
    if field in {"image_url", "additional_images"}:
        value = public_asset_delivery_url(value)
    if field == "additional_images" and isinstance(value, str) or field == "variants":
        return value
    if field in {"title", "brand", "description"}:
        value = clean_text(strip_html_tags(value))
    if field in {"variant_id", "sku", "gtin"} and value is not None:
        value = str(value).strip()
    price = _normalized_price(value, binding)
    if price is not None:
        return price
    if field == "currency" and isinstance(value, str):
        return value.strip().upper()
    return normalize_value(field or "", value) if binding.transform or field else value


def _normalized_price(value: Any, binding: RecipeBinding) -> Any | None:
    field = binding.field or ""
    if "price" not in field or binding.unit not in {"minor", "major"}:
        return None
    if binding.unit == "minor":
        value = normalize_decimal_price(value, interpret_integral_as_cents=True)
    try:
        return f"{Decimal(str(value).replace(',', '')).quantize(Decimal('0.01')):f}"
    except (InvalidOperation, ValueError):
        return normalize_decimal_price(value)


def _registered_prefix(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = re.match(r"^(.+?®)(?:\s|$)", value.strip())
    return match.group(1) if match else None


def _stock_availability(value: Any) -> str | None:
    try:
        return "in_stock" if Decimal(str(value)) > 0 else "out_of_stock"
    except (InvalidOperation, ValueError):
        return None


def _job_location(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return ", ".join(
        str(value.get(key) or "").strip()
        for key in ("addressLocality", "addressRegion", "addressCountry")
        if str(value.get(key) or "").strip()
    )


def _attribute_availability(value: Any) -> str | None:
    if not isinstance(value, str):
        return value
    try:
        state = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    selectable = state.get("selectable") if isinstance(state, dict) else None
    if selectable in {False, "0", "false", "False"}:  # bool==int: False also matches 0
        return "out_of_stock"
    if selectable in {True, "1", "true", "True"}:  # True also matches 1
        return "in_stock"
    return None


def _host_words(value: Any, raw_lengths: str) -> str:
    ignored = {
        "",
        "www",
        "shop",
        "store",
        "us",
        "usa",
        "uk",
        "in",
        "com",
        "co",
        "net",
        "org",
    }
    labels = [
        label for label in str(value).casefold().split(".") if label not in ignored
    ]
    compact = re.sub(r"[^a-z0-9]", "", max(labels, key=len) if labels else "")
    for suffix in ("beauty", "cosmetics", "official", "online", "shop", "store"):
        if compact.endswith(suffix):
            compact = compact[: -len(suffix)]
            break
    return _segments(compact, raw_lengths, str.title)


def _slug_words(value: Any, arguments: str, *, upper: bool = False) -> str:
    start, raw_lengths = arguments.split(":", 1)
    words = re.findall(r"[a-z0-9]+", str(value).casefold())
    count = len(raw_lengths.split(","))
    result = " ".join(words[int(start) : int(start) + count])
    return result.upper() if upper else result.title()


def _slice(value: Any, arguments: str, *, upper: bool = False) -> str:
    start, length = (int(item) for item in arguments.split(":", 1))
    result = str(value)[start : start + length]
    return result.upper() if upper else result


def _query_param(value: Any, name: str) -> Any:
    if not isinstance(value, str):
        return None
    values = parse_qs(urlsplit(value).query).get(name, ())
    return values[0] if values else None


def _segments(compact: str, raw_lengths: str, convert: Callable[[str], str]) -> str:
    pieces: list[str] = []
    offset = 0
    for length in (int(item) for item in raw_lengths.split(",")):
        pieces.append(convert(compact[offset : offset + length]))
        offset += length
    return " ".join(pieces)


def _restore_market_locale(page_url: str, href: str) -> str:
    product_url = urljoin(page_url, href)
    page, product = urlsplit(page_url), urlsplit(product_url)
    if normalize_domain(page_url) != normalize_domain(product_url):
        return product_url
    page_parts = tuple(part for part in page.path.split("/") if part)
    product_parts = tuple(part for part in product.path.split("/") if part)
    category_index = next(
        (
            i
            for i, part in enumerate(page_parts)
            if part.casefold() in LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS
        ),
        None,
    )
    if category_index is None:
        return product_url
    prefix = page_parts[:category_index]
    if not prefix or product_parts[: len(prefix)] == prefix or not product_parts:
        return product_url
    first = product_parts[0].casefold()
    if first == LISTING_MARKET_LOCALE_PRODUCT_PREFIX:
        parts = (*prefix, *product_parts)
    elif first in LISTING_MARKET_LOCALE_GENDER_SEGMENTS:
        parts = (*prefix, LISTING_MARKET_LOCALE_PRODUCT_PREFIX, *product_parts)
    else:
        return product_url
    return product._replace(path="/" + "/".join(parts)).geturl()


_VALUE_TRANSFORMS: dict[str, ValueTransform] = {
    "after_colon": lambda value: (
        value.partition(":")[2].strip() if isinstance(value, str) else value
    ),
    "registered_prefix": _registered_prefix,
    "first_token": lambda value: (
        value.strip().split(" ", 1)[0].strip("'\"") if isinstance(value, str) else value
    ),
    "last_token": lambda value: (
        value.strip().rsplit(" ", 1)[-1].strip("'\"")
        if isinstance(value, str)
        else value
    ),
    "strip_quotes": lambda value: (
        value.strip("'\"") if isinstance(value, str) else value
    ),
    "strip_leading_symbols": lambda value: (
        re.sub(r"^[^A-Za-z0-9]+", "", value).strip()
        if isinstance(value, str)
        else value
    ),
    "largest_srcset": lambda value: (
        largest_srcset_url(value) if isinstance(value, str) else value
    ),
    "semantic_url_title": lambda value: (
        detail_title_from_url(value) if isinstance(value, str) else value
    ),
    "dom_currency": extract_currency_code,
    "casefold": lambda value: (
        value.strip("'\"").casefold() if isinstance(value, str) else value
    ),
    "path_leaf_title": lambda value: (
        value.rsplit("/", 1)[-1].title() if isinstance(value, str) else value
    ),
    "brand_path_leaf": lambda value: (
        value.rsplit("/", 1)[-1].replace("-", " ").title()
        if isinstance(value, str)
        else value
    ),
    "currency_from_price_symbol": extract_currency_code,
    "availability_from_stock_quantity": _stock_availability,
    "job_location": _job_location,
    "attribute_json_availability": _attribute_availability,
}
_CONTEXT_TRANSFORMS: dict[str, ContextTransform] = {
    "restore_market_locale": lambda request, value: (
        _restore_market_locale(request.capture.final_url, value)
        if isinstance(value, str)
        else value
    ),
    "dom_price": lambda request, value: parse_money(
        value, locale_hint=locale_hint_from_page_url(request.capture.final_url)
    ),
    "currency_from_page_url": lambda request, value: currency_hint_from_page_url(
        request.capture.final_url
    ),
}
_PREFIX_TRANSFORMS: dict[str, PrefixTransform] = {
    "value_url_template:": lambda value, template: template.replace(
        "{value}", str(value)
    ),
    "prefix_words:": lambda value, count: " ".join(str(value).split()[: int(count)]),
    "host_words:": _host_words,
    "slug_words:": _slug_words,
    "uppercase_slug_words:": lambda value, args: _slug_words(value, args, upper=True),
    "selected_slice:": _slice,
    "selected_slice_upper:": lambda value, args: _slice(value, args, upper=True),
    "substring:": _slice,
    "query_param:": _query_param,
}
