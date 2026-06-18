from __future__ import annotations

import re
from dataclasses import dataclass
import logging
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.domain_profiles import LISTING_SURFACE_IDENTIFIER
from app.services.config.extraction_rules import (
    NOISE_CONTAINER_REMOVAL_SELECTOR,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.structured_sources import (
    harvest_js_state_objects,
    parse_embedded_json,
    parse_json_ld,
    parse_microdata,
    parse_opengraph,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    original_html: str
    cleaned_html: str
    dom_parser: LexborHTMLParser
    _soup: BeautifulSoup | None = None
    _original_soup: BeautifulSoup | None = None
    _original_dom_parser: LexborHTMLParser | None = None
    _js_state_objects: dict[str, Any] | None = None

    @property
    def soup(self) -> BeautifulSoup:
        current = self._soup
        if current is None:
            current = BeautifulSoup(self.cleaned_html, "html.parser")
            object.__setattr__(self, "_soup", current)
        return current

    @property
    def original_soup(self) -> BeautifulSoup:
        current = self._original_soup
        if current is None:
            current = BeautifulSoup(self.original_html, "html.parser")
            object.__setattr__(self, "_original_soup", current)
        return current

    @property
    def original_dom_parser(self) -> LexborHTMLParser:
        current = self._original_dom_parser
        if current is None:
            current = LexborHTMLParser(self.original_html)
            object.__setattr__(self, "_original_dom_parser", current)
        return current

    @property
    def js_state_objects(self) -> dict[str, Any]:
        current = self._js_state_objects
        if current is None:
            current = harvest_js_state_objects(None, self.cleaned_html)
            object.__setattr__(self, "_js_state_objects", current)
        return current


def prepare_extraction_context(html: str) -> ExtractionContext:
    parser = LexborHTMLParser(html)
    try:
        for node in parser.css(NOISE_CONTAINER_REMOVAL_SELECTOR):
            tag = str(getattr(node, "tag", "") or "").strip().lower()
            if tag in {"html", "body"}:
                continue
            node.decompose()
    except Exception as exc:
        logger.debug(
            "noise_removal_failed selector=%s error=%s",
            NOISE_CONTAINER_REMOVAL_SELECTOR,
            exc,
        )
    cleaned_html = parser.html
    return ExtractionContext(
        original_html=html,
        cleaned_html=cleaned_html or "",
        dom_parser=parser,
    )


def collect_structured_source_payloads(
    context: ExtractionContext,
    *,
    page_url: str,
    surface: str = "",
) -> tuple[tuple[str, list[dict[str, Any]]], ...]:
    json_ld_payloads = _dict_payloads(parse_json_ld(context.soup))
    is_listing_surface = LISTING_SURFACE_IDENTIFIER in str(surface or "").strip().lower()
    skip_extruct_fallbacks = is_listing_surface and _json_ld_listing_confident(
        json_ld_payloads
    )
    js_state_objects = context.js_state_objects
    js_state_payloads: list[dict[str, Any]] = []
    for payload in js_state_objects.values():
        if isinstance(payload, dict):
            js_state_payloads.append(payload)
            continue
        if isinstance(payload, list) and payload:
            js_state_payloads.append({"itemListElement": payload})
    # VTEX __STATE__ contains a normalized product cache. Extract product
    # items as embedded_json so the listing extractor can consume them.
    vtex_listing_payloads = _extract_vtex_state_listing_items(
        js_state_objects, page_url=page_url
    )
    embedded_json_payloads = _dict_payloads(
        parse_embedded_json(context.soup, context.cleaned_html)
    )
    if vtex_listing_payloads:
        embedded_json_payloads.extend(vtex_listing_payloads)
    return (
        ("json_ld", json_ld_payloads),
        (
            "microdata",
            []
            if skip_extruct_fallbacks
            else _dict_payloads(
                parse_microdata(context.soup, context.cleaned_html, page_url)
            ),
        ),
        (
            "opengraph",
            []
            if skip_extruct_fallbacks
            else _dict_payloads(
                parse_opengraph(context.soup, context.cleaned_html, page_url)
            ),
        ),
        ("embedded_json", embedded_json_payloads),
        ("js_state", js_state_payloads),
    )


def _dict_payloads(payloads: object) -> list[dict[str, Any]]:
    if not isinstance(payloads, list):
        return []
    return [payload for payload in payloads if isinstance(payload, dict)]


def _json_ld_listing_confident(payloads: list[dict[str, Any]]) -> bool:
    listing_like = 0
    for payload in payloads:
        if _looks_like_listing_payload(payload):
            listing_like += 1
        if _payload_has_item_list(payload):
            return True
    return listing_like >= max(3, int(crawler_runtime_settings.listing_min_items))


def _looks_like_listing_payload(payload: dict[str, Any]) -> bool:
    raw_type = payload.get("@type")
    normalized_type = (
        " ".join(str(item or "") for item in raw_type)
        if isinstance(raw_type, list)
        else str(raw_type or "")
    ).strip().lower()
    if "itemlist" in normalized_type:
        return True
    if any(token in normalized_type for token in ("product", "jobposting", "offer", "aggregateoffer")):
        return bool(payload.get("name") or payload.get("title") or payload.get("url"))
    return _payload_has_item_list(payload)


def _payload_has_item_list(payload: dict[str, Any]) -> bool:
    item_list = payload.get("itemListElement")
    if isinstance(item_list, list) and item_list:
        return True
    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        nested_items = main_entity.get("itemListElement")
        if isinstance(nested_items, list) and nested_items:
            return True
    return False


def _extract_vtex_state_listing_items(
    state_objects: dict[str, Any],
    *,
    page_url: str,
) -> list[dict[str, Any]]:
    """Extract product listing items from VTEX __STATE__ normalized cache.

    VTEX stores product data as ``"Product:sp-<id>": {productName, linkText, ...}``
    entries in a flat dict. This function collects them into structured listing
    payloads that the listing extractor can consume via the embedded_json path.
    """
    from urllib.parse import urlsplit

    state = state_objects.get("__STATE__")
    if not isinstance(state, dict):
        return []
    parsed_page = urlsplit(page_url)
    base_origin = f"{parsed_page.scheme}://{parsed_page.netloc}"
    items: list[dict[str, Any]] = []
    for key, value in state.items():
        if not isinstance(value, dict):
            continue
        if not str(key).startswith("Product:"):
            continue
        product_name = value.get("productName") or value.get("name")
        link_text = value.get("linkText") or value.get("slug")
        if not product_name or not link_text:
            continue
        # Normalize slug: strip whitespace, lowercase, replace spaces with hyphens,
        # percent-encode reserved chars while preserving international characters
        import unicodedata
        from urllib.parse import quote as url_quote

        normalized_slug = re.sub(r"\s+", "-", str(link_text).strip().lower())
        normalized_slug = unicodedata.normalize("NFC", normalized_slug)
        normalized_slug = url_quote(normalized_slug, safe="-_/")
        if not normalized_slug:
            continue
        url = f"{base_origin}/{normalized_slug}/p"
        item: dict[str, Any] = {
            "name": str(product_name),
            "url": url,
            "@type": "Product",
        }
        brand = value.get("brand")
        if brand:
            item["brand"] = str(brand)
        description = value.get("description") or value.get("metaTagDescription")
        if description:
            item["description"] = str(description)
        # Extract price from items/sellers structure
        price = _vtex_state_product_price(value, state)
        if price is not None:
            item["offers"] = {"price": price}
        image = _vtex_state_product_image(value, state)
        if image:
            item["image"] = image
        items.append(item)
    if len(items) < 2:
        return []
    return [{"@type": "ItemList", "itemListElement": [{"item": item} for item in items]}]


def _vtex_state_product_price(
    product: dict[str, Any],
    state: dict[str, Any],
) -> float | None:
    """Extract best price from VTEX product state entry.

    VTEX uses Apollo Client normalized cache with ``{type: "id", id: "..."}``
    references. Prices live at ``$Product:sp-XXX.priceRange.sellingPrice.lowPrice``.
    """
    product_id = product.get("productId") or product.get("cacheId")
    # Try Apollo-style priceRange reference resolution
    price_range_ref = product.get("priceRange")
    if isinstance(price_range_ref, dict):
        # Inline or resolved priceRange
        selling = _resolve_vtex_state_ref(price_range_ref.get("sellingPrice"), state)
        if isinstance(selling, dict):
            low = _coerce_positive_float(
                selling.get("lowPrice") or selling.get("highPrice")
            )
            if low is not None:
                return low
    # Try resolving via state key pattern: $Product:sp-XXX.priceRange.sellingPrice
    if product_id:
        for prefix in (f"$Product:sp-{product_id}", f"$Product:{product_id}"):
            selling_key = f"{prefix}.priceRange.sellingPrice"
            selling_obj = _resolve_vtex_state_ref(state.get(selling_key), state)
            if isinstance(selling_obj, dict):
                low = _coerce_positive_float(
                    selling_obj.get("lowPrice") or selling_obj.get("highPrice")
                )
                if low is not None:
                    return low
    # Fallback: items[0].sellers[0].commertialOffer
    if product_id:
        offer_key = next(
            (k for k in state if k.startswith(f"$Product:sp-{product_id}.items") and "commertialOffer" in k),
            None,
        )
        if offer_key:
            offer = _resolve_vtex_state_ref(state.get(offer_key), state)
            if isinstance(offer, dict):
                price = _coerce_positive_float(offer.get("Price") or offer.get("price"))
                if price is not None:
                    return price
    return None


def _vtex_state_product_image(
    product: dict[str, Any],
    state: dict[str, Any],
) -> str | None:
    """Extract first image URL from VTEX product state entry."""
    items_ref = product.get("items")
    if not isinstance(items_ref, list):
        return None
    for item_ref in items_ref:
        item = _resolve_vtex_state_ref(item_ref, state)
        if not isinstance(item, dict):
            continue
        images = item.get("images")
        if not isinstance(images, list):
            continue
        for img_ref in images:
            img = _resolve_vtex_state_ref(img_ref, state)
            if isinstance(img, dict):
                url = img.get("imageUrl") or img.get("url")
                if url and isinstance(url, str):
                    return url
    return None


def _resolve_vtex_state_ref(value: object, state: dict[str, Any]) -> object:
    if isinstance(value, dict):
        ref_id = value.get("id") if value.get("type") == "id" else None
        if ref_id:
            return state.get(str(ref_id), value)
        return value
    if value is None:
        return None
    return state.get(str(value), value)


def _coerce_positive_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None
