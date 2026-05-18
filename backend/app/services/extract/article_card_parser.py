from __future__ import annotations

__all__ = (
    "article_card_text",
    "article_card_date",
    "article_card_summary",
)

from bs4 import BeautifulSoup

from app.services.shared.field_coerce import clean_text


def article_card_text(card_soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = card_soup.select_one(selector)
        value = clean_text(node.get_text(" ", strip=True) if node else "")
        if value:
            return value
    return ""


def article_card_date(card_soup: BeautifulSoup) -> str:
    for selector in (
        "time[datetime]",
        "[itemprop='datePublished']",
        ".post-date",
        ".published",
    ):
        node = card_soup.select_one(selector)
        if node is None:
            continue
        value = clean_text(
            node.get("datetime")
            or node.get("content")
            or node.get_text(" ", strip=True)
        )
        if value:
            return value
    return ""


def article_card_summary(card_soup: BeautifulSoup, title: str) -> str:
    for selector in ("p", ".summary", ".excerpt", ".description"):
        node = card_soup.select_one(selector)
        value = clean_text(node.get_text(" ", strip=True) if node else "")
        if value and value != clean_text(title) and len(value) >= 24:
            return value
    return ""
