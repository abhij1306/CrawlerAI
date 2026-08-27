from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser

from app.connectors.adapters.base import BaseAdapter, node_attr, node_text
from app.core.config.extraction_rules import (
    AMAZON_DETAIL_PRICE_SELECTORS,
    AMAZON_DETAIL_TABLE_IGNORED_LABELS,
    AMAZON_IMAGE_CDN_HOSTS,
    AMAZON_IMAGE_LOW_RES_SUFFIX_PATTERN,
    AMAZON_PRICE_CONTAINER_SELECTOR,
    AMAZON_PRICE_FRACTION_SELECTOR,
    AMAZON_PRICE_OFFSCREEN_SELECTOR,
    AMAZON_PRICE_SYMBOL_SELECTOR,
    AMAZON_PRICE_WHOLE_SELECTOR,
)
from app.core.shared.field_coerce import extract_currency_code

_DOMAINS = (
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.ca",
    "amazon.in",
    "amazon.co.jp",
    "amazon.com.au",
    "amazon.com.br",
)


def _clean_text(value: object) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _clean_brand(value: str) -> str | None:
    cleaned = re.sub(r"^\s*Brand:\s*", "", value or "", flags=re.I).strip()
    store = re.match(r"^\s*Visit\s+the\s+(.+?)\s+Store\s*$", cleaned, flags=re.I)
    return _clean_text(store.group(1) if store else cleaned)


def _price_text(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    match = re.search(
        r"(?:(?:[$€£₹]|[A-Z]{3})\s*)?\d[\d,]*(?:\.\d{1,3})?(?:\s*(?:[$€£₹]|[A-Z]{3}))?",
        text,
        re.I,
    )
    return match.group(0) if match else None


def _price_from_node(node: object) -> str | None:
    css_first = getattr(node, "css_first", None)
    if not callable(css_first):
        return None
    offscreen = _price_text(node_text(css_first(AMAZON_PRICE_OFFSCREEN_SELECTOR)))
    if offscreen:
        return offscreen
    whole = re.sub(r"[^\d,]+", "", node_text(css_first(AMAZON_PRICE_WHOLE_SELECTOR)))
    if not whole:
        return None
    fraction = re.sub(r"\D+", "", node_text(css_first(AMAZON_PRICE_FRACTION_SELECTOR)))[
        :2
    ].ljust(2, "0")
    symbol = node_text(css_first(AMAZON_PRICE_SYMBOL_SELECTOR))
    return _price_text(f"{symbol}{whole}.{fraction}")


def _detail_price(parser: LexborHTMLParser) -> str | None:
    for selector in AMAZON_DETAIL_PRICE_SELECTORS:
        price = _price_text(node_text(parser.css_first(selector)))
        if price:
            return price
    for node in parser.css(AMAZON_PRICE_CONTAINER_SELECTOR):
        price = _price_from_node(node)
        if price:
            return price
    return None


def _asin(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url, re.I)
    return match.group(1).upper() if match else None


def _image_url(value: object) -> str | None:
    candidate = str(value or "").strip()
    host = (urlparse(candidate).hostname or "").lower()
    if not candidate or host not in AMAZON_IMAGE_CDN_HOSTS:
        return candidate or None
    return re.sub(AMAZON_IMAGE_LOW_RES_SUFFIX_PATTERN, "", candidate, flags=re.I)


def _rating(parser: LexborHTMLParser) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)",
        node_text(parser.css_first("#acrPopover .a-icon-alt, .a-icon-star span")),
    )
    return float(match.group(1)) if match else None


def _review_count(parser: LexborHTMLParser) -> int | None:
    match = re.search(
        r"([\d,]+)", node_text(parser.css_first("#acrCustomerReviewText"))
    )
    return int(match.group(1).replace(",", "")) if match else None


class AmazonAdapter(BaseAdapter):
    name = "amazon"

    async def can_handle(self, url: str, html: str) -> bool:
        del html
        host = (urlparse(url).hostname or "").lower()
        return any(host == domain or host.endswith(f".{domain}") for domain in _DOMAINS)

    async def extract(
        self,
        url: str,
        html: str,
        surface: str,
        proxy: str | None = None,
    ):
        del proxy
        parser = LexborHTMLParser(html)
        if surface == "ecommerce_detail":
            record = self._detail(parser, url)
            return self.result([record] if record else [])
        if surface == "ecommerce_listing":
            return self.result(self._listing(parser, url))
        return self.result([])

    def _detail(self, parser: LexborHTMLParser, url: str) -> dict[str, object] | None:
        title = _clean_text(node_text(parser.css_first("#productTitle")))
        if not title:
            return None
        detail_table = self._detail_table(parser)
        asin = _asin(url) or self._table_value(detail_table, "asin")
        price = _detail_price(parser)
        images = self._images(parser)
        features = self._features(parser)
        description = self._description(parser)
        specifications = self._specifications(detail_table)
        record: dict[str, object] = {
            "title": title,
            "url": url,
            "brand": _clean_brand(
                node_text(
                    parser.css_first("#bylineInfo, .po-brand .a-span9 .a-size-base")
                )
            ),
            "price": price,
            "currency": extract_currency_code(price),
            "availability": _clean_text(
                node_text(parser.css_first("#availability span"))
            ),
            "description": description or (" ".join(features) if features else None),
            "image": images[0] if images else None,
            "images": images or None,
            "rating": _rating(parser),
            "review_count": _review_count(parser),
            "productId": asin,
            "sku": asin,
            "mpn": self._table_value(detail_table, "item model number"),
            "gtin": self._table_value(detail_table, "upc")
            or self._table_value(detail_table, "ean"),
            "category": self._product_type(parser),
            "features": features or None,
            "specifications": specifications,
            "product_details": " ".join(
                value
                for value in (description, " ".join(features), specifications)
                if value
            )
            or None,
        }
        return {
            key: value for key, value in record.items() if value not in (None, "", [])
        }

    def _images(self, parser: LexborHTMLParser) -> list[str]:
        values: list[str] = []
        for node in parser.css(
            "#landingImage, #imgBlkFront, #altImages img, #imageBlock img"
        ):
            candidates = [node_attr(node, "data-old-hires"), node_attr(node, "src")]
            dynamic = node_attr(node, "data-a-dynamic-image")
            if dynamic:
                try:
                    payload = json.loads(dynamic)
                except json.JSONDecodeError:
                    payload = {}
                if isinstance(payload, Mapping):
                    candidates.extend(str(value) for value in payload)
            for candidate in candidates:
                normalized = _image_url(candidate)
                if normalized and normalized not in values:
                    values.append(normalized)
        return values

    def _features(self, parser: LexborHTMLParser) -> list[str]:
        values: list[str] = []
        for node in parser.css("#feature-bullets li, #feature-bullets .a-list-item"):
            value = _clean_text(node_text(node, separator=" "))
            if (
                value
                and value.casefold() != "see more product details"
                and value not in values
            ):
                values.append(value)
        return values

    def _description(self, parser: LexborHTMLParser) -> str | None:
        parts = [
            _clean_text(node_text(node, separator=" "))
            for node in parser.css(
                "#productDescription p, #productDescription, #bookDescription_feature_div"
            )
        ]
        return " ".join(dict.fromkeys(part for part in parts if part)) or None

    def _detail_table(self, parser: LexborHTMLParser) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in parser.css(
            "#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr"
        ):
            key = _clean_text(node_text(row.css_first("th")))
            value = _clean_text(node_text(row.css_first("td")))
            if (
                key
                and value
                and key.casefold().removesuffix(":")
                not in AMAZON_DETAIL_TABLE_IGNORED_LABELS
            ):
                values[key] = value
        for item in parser.css("#detailBullets_feature_div li"):
            text = _clean_text(node_text(item, separator=" "))
            if not text or ":" not in text:
                continue
            key, value = (_clean_text(part) for part in text.split(":", 1))
            if (
                key
                and value
                and key.casefold().removesuffix(":")
                not in AMAZON_DETAIL_TABLE_IGNORED_LABELS
            ):
                values.setdefault(key, value)
        return values

    @staticmethod
    def _table_value(values: dict[str, str], label: str) -> str | None:
        target = label.casefold()
        return next(
            (
                value
                for key, value in values.items()
                if key.casefold().removesuffix(":") == target
            ),
            None,
        )

    @staticmethod
    def _specifications(values: dict[str, str]) -> str | None:
        return " ".join(f"{key}: {value}" for key, value in values.items()) or None

    @staticmethod
    def _product_type(parser: LexborHTMLParser) -> str | None:
        values = [
            _clean_text(node_text(node))
            for node in parser.css(
                "#wayfinding-breadcrumbs_feature_div li, #wayfinding-breadcrumbs_container li"
            )
        ]
        return next((value for value in reversed(values) if value), None)

    @staticmethod
    def _listing(parser: LexborHTMLParser, url: str) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for card in parser.css("[data-component-type='s-search-result']"):
            title = _clean_text(node_text(card.css_first("h2 a span")))
            href = node_attr(card.css_first("h2 a"), "href")
            if not title or not href:
                continue
            price = _price_from_node(card.css_first(AMAZON_PRICE_CONTAINER_SELECTOR))
            records.append(
                {
                    "title": title,
                    "url": urljoin(url, href),
                    "price": price,
                    "currency": extract_currency_code(price),
                    "image_url": _image_url(
                        node_attr(card.css_first(".s-image"), "src")
                    ),
                }
            )
        return records
