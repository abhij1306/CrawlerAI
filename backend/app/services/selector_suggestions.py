from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import EXTRACTION_RULES, SELECTOR_NOISE_VALUES
from app.services.config.selectors import CARD_SELECTORS, LISTING_FIELD_SELECTORS
from app.services.shared.field_coerce import PRICE_RE, clean_text
from app.services.dom.xpath_service import build_absolute_xpath, extract_selector_value


selector_noise_values = frozenset(
    str(v).strip().lower() for v in (SELECTOR_NOISE_VALUES or []) if str(v).strip()
)


def selector_suggestion_from_record(record: dict[str, object]) -> dict[str, object]:
    return {
        "field_name": str(record.get("field_name") or "").strip().lower(),
        "css_selector": record.get("css_selector"),
        "xpath": record.get("xpath"),
        "regex": record.get("regex"),
        "sample_value": record.get("sample_value"),
        "source": record.get("source") or "domain_memory",
    }


def deterministic_suggestions(
    soup: BeautifulSoup,
    *,
    html: str,
    url: str,
    field_name: str,
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    selector = str((EXTRACTION_RULES.get("dom_patterns") or {}).get(field_name) or "").strip()
    if selector:
        matched_value, count, _selector_used = extract_selector_value(html, css_selector=selector)
        if count > 0:
            suggestions.append(
                {
                    "field_name": field_name,
                    "css_selector": selector,
                    "sample_value": matched_value,
                    "source": "auto_css",
                }
            )

    for node in _candidate_nodes_for_field(soup, field_name):
        suggestion = _build_node_suggestion(node, field_name, html)
        if suggestion and not suggestion_exists(suggestions, suggestion):
            suggestions.append(suggestion)
    if field_name == "price":
        price_match = PRICE_RE.search(clean_text(soup.get_text(" ", strip=True)))
        if price_match:
            suggestions.append(
                {
                    "field_name": field_name,
                    "regex": PRICE_RE.pattern,
                    "sample_value": price_match.group(0),
                    "source": "auto_regex",
                }
            )
    return suggestions


def listing_card_suggestions(
    soup: BeautifulSoup,
    *,
    html: str,
    field_name: str,
) -> list[dict[str, object]]:
    card_selectors = CARD_SELECTORS.get("ecommerce") or []
    first_card = None
    for card_sel in card_selectors:
        cards = soup.select(str(card_sel))
        if cards:
            first_card = cards[0]
            break
    if not first_card:
        return []
    field_selectors = LISTING_FIELD_SELECTORS.get(field_name, [])
    if not field_selectors:
        return []
    suggestions: list[dict[str, object]] = []
    for sel in field_selectors:
        nodes = first_card.select(sel)
        if not nodes:
            continue
        node = nodes[0]
        xpath = build_absolute_xpath(node)
        if not xpath:
            continue
        sample_value, count, selector_used = extract_selector_value(html, xpath=xpath)
        if count <= 0:
            continue
        suggestion: dict[str, object] = {
            "field_name": field_name,
            "xpath": selector_used or xpath,
            "sample_value": sample_value,
            "source": "listing_card_xpath",
        }
        if not suggestion_exists(suggestions, suggestion):
            suggestions.append(suggestion)
    return suggestions


def is_noise_value(value: str | None, field_name: str) -> bool:
    if not value:
        return False
    cleaned = " ".join(str(value).split()).strip().lower()
    if len(cleaned) < 3:
        return True
    if cleaned in selector_noise_values:
        return True
    return False


def suggestion_exists(
    rows: list[dict[str, object]],
    candidate: dict[str, object],
) -> bool:
    candidate_key = (
        str(candidate.get("field_name") or ""),
        str(candidate.get("css_selector") or ""),
        str(candidate.get("xpath") or ""),
        str(candidate.get("regex") or ""),
    )
    return any(
        (
            str(row.get("field_name") or ""),
            str(row.get("css_selector") or ""),
            str(row.get("xpath") or ""),
            str(row.get("regex") or ""),
        )
        == candidate_key
        for row in rows
    )


def _candidate_nodes_for_field(soup: BeautifulSoup, field_name: str) -> list[Tag]:
    selectors_by_field = {
        "title": ["h1", "[itemprop='name']", "meta[property='og:title']"],
        "price": [
            "[itemprop='price']",
            "[class*='price']",
            "[data-test*='price']",
        ],
        "brand": ["[itemprop='brand']", "[class*='brand']", "[data-test*='brand']"],
        "sku": ["[itemprop='sku']", "[data-sku]", "[class*='sku']"],
        "rating": ["[itemprop='ratingValue']", "[class*='rating']"],
        "availability": ["[itemprop='availability']", "[class*='stock']"],
        "in_stock": ["button:not([disabled])", "[itemprop='availability']"],
    }
    nodes: list[Tag] = []
    for selector in selectors_by_field.get(field_name, []):
        for node in soup.select(selector):
            if isinstance(node, Tag):
                nodes.append(node)
    return nodes[:3]


def _build_node_suggestion(
    node: Tag,
    field_name: str,
    html: str,
) -> dict[str, object] | None:
    if node.name == "meta":
        prop = str(node.get("property") or node.get("itemprop") or "").strip()
        if prop:
            sample_value, count, _selector_used = extract_selector_value(
                html,
                css_selector=f"meta[property='{prop}'], meta[itemprop='{prop}']",
            )
            if count > 0:
                return {
                    "field_name": field_name,
                    "css_selector": f"meta[property='{prop}'], meta[itemprop='{prop}']",
                    "sample_value": sample_value,
                    "source": "auto_meta",
                }
    xpath = build_absolute_xpath(node)
    if not xpath:
        return None
    sample_value, count, selector_used = extract_selector_value(html, xpath=xpath)
    if count <= 0:
        return None
    return {
        "field_name": field_name,
        "xpath": selector_used or xpath,
        "sample_value": sample_value,
        "source": "auto_xpath",
    }
