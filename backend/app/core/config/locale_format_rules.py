from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from app.core.config.extraction_rules import CURRENCY_SYMBOL_MAP

COUNTRY_CURRENCY: dict[str, str] = {
    "us": "USD",
    "gb": "GBP",
    "in": "INR",
    "ca": "CAD",
    "au": "AUD",
    "nz": "NZD",
    "jp": "JPY",
    "cn": "CNY",
    "ch": "CHF",
    "se": "SEK",
    "no": "NOK",
    "dk": "DKK",
    "pl": "PLN",
    "cz": "CZK",
    "hu": "HUF",
    "ru": "RUB",
    "br": "BRL",
    "mx": "MXN",
    "za": "ZAR",
    "ae": "AED",
    "sa": "SAR",
    "sg": "SGD",
    "hk": "HKD",
    "kr": "KRW",
    "th": "THB",
    "my": "MYR",
    "id": "IDR",
    "ph": "PHP",
    "vn": "VND",
    "tr": "TRY",
    "il": "ILS",
    "de": "EUR",
    "fr": "EUR",
    "it": "EUR",
    "es": "EUR",
    "nl": "EUR",
    "be": "EUR",
    "at": "EUR",
    "ie": "EUR",
    "pt": "EUR",
    "fi": "EUR",
    "gr": "EUR",
    "sk": "EUR",
    "si": "EUR",
    "lv": "EUR",
    "lt": "EUR",
    "ee": "EUR",
    "lu": "EUR",
    "mt": "EUR",
    "cy": "EUR",
}

COUNTRY_ALIASES = {"uk": "gb"}
GENERIC_TLDS = frozenset({"com", "net", "org", "io", "shop", "store", "co", "app"})
HOST_CURRENCY_HINTS: dict[str, str] = {
    "firstcry.com": "INR",
}
COMMA_DECIMAL_COUNTRIES = frozenset(
    {
        "at",
        "be",
        "br",
        "de",
        "dk",
        "es",
        "fi",
        "fr",
        "gr",
        "it",
        "nl",
        "no",
        "pl",
        "pt",
        "ru",
        "se",
    }
)
DOT_DECIMAL_COUNTRIES = frozenset(
    {"au", "ca", "gb", "hk", "in", "jp", "nz", "sg", "us", "za"}
)
CURRENCY_SYMBOL_TO_ISO: dict[str, str] = dict(CURRENCY_SYMBOL_MAP)
GTIN_LENGTHS = frozenset({8, 12, 13, 14})
PRICE_CONTEXT_TOKENS = frozenset(
    {"cost", "from", "mrp", "msrp", "now", "price", "sale", "starting"}
)

_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}[-_](?P<country>[a-z]{2})$")


def parse_money(value: object, *, locale_hint: str | None = None) -> Decimal | None:
    text = _money_text(value)
    if not text:
        return None
    decimal_separator = _decimal_separator(text, locale_hint=locale_hint)
    if decimal_separator == ",":
        normalized = text.replace(".", "").replace(",", ".")
    elif decimal_separator == ".":
        normalized = text.replace(",", "")
    else:
        normalized = text.replace(",", "").replace(".", "")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def money_has_ambiguous_decimal(
    value: object, *, locale_hint: str | None = None
) -> bool:
    text = _money_text(value)
    return bool(
        text
        and not _locale_resolves_decimal_ambiguity(locale_hint)
        and "," in text
        and "." in text
        and _last_group_length(
            text,
            "," if text.rfind(",") > text.rfind(".") else ".",
        )
        in {1, 2}
    )


def validate_gtin(digits: object) -> bool:
    text = re.sub(r"\D+", "", str(digits or ""))
    if len(text) not in GTIN_LENGTHS:
        return False
    payload, check_digit = text[:-1], int(text[-1])
    total = 0
    for index, digit in enumerate(reversed(payload), start=1):
        total += int(digit) * (3 if index % 2 else 1)
    return (10 - total % 10) % 10 == check_digit


def currency_hint_from_page_url(page_url: object) -> str | None:
    code, _host_level = currency_hint_from_page_url_with_scope(page_url)
    return code


def currency_hint_from_page_url_with_scope(page_url: object) -> tuple[str | None, bool]:
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").strip().lower()
    segments = [
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    ]
    if currency := _currency_from_locale_segments(segments):
        return currency, False
    if currency := _currency_from_host_hint(hostname):
        return currency, True
    if currency := _currency_from_tld(hostname):
        return currency, True
    return None, False


def locale_hint_from_page_url(page_url: object) -> str | None:
    parsed = urlparse(str(page_url or "").strip())
    for segment in str(parsed.path or "").split("/"):
        normalized = segment.strip().lower()
        if _LOCALE_SEGMENT_RE.match(normalized):
            return normalized.replace("_", "-")
    hostname = str(parsed.hostname or "").strip().lower()
    labels = [label for label in hostname.split(".") if label]
    if len(labels) < 2 or labels[-1] in GENERIC_TLDS:
        return None
    return COUNTRY_ALIASES.get(labels[-1], labels[-1])


def _country_currency(country: str) -> str | None:
    return COUNTRY_CURRENCY.get(COUNTRY_ALIASES.get(country, country))


def _currency_from_locale_segments(path_segments: list[str]) -> str | None:
    if path_segments and (currency := _country_currency(path_segments[0])):
        return currency
    for segment in path_segments:
        match = _LOCALE_SEGMENT_RE.match(segment)
        if match and (currency := _country_currency(match.group("country"))):
            return currency
    return None


def _currency_from_tld(hostname: str) -> str | None:
    labels = [label for label in hostname.split(".") if label]
    if len(labels) < 2 or labels[-1] in GENERIC_TLDS:
        return None
    return _country_currency(labels[-1])


def _currency_from_host_hint(hostname: str) -> str | None:
    return next(
        (
            currency
            for host, currency in HOST_CURRENCY_HINTS.items()
            if hostname == host or hostname.endswith(f".{host}")
        ),
        None,
    )


def _money_text(value: object) -> str:
    return re.sub(r"[^0-9.,-]", "", str(value or "")).strip()


def _decimal_separator(text: str, *, locale_hint: str | None) -> str | None:
    country = _country_from_locale_hint(locale_hint)
    if "," in text and "." in text:
        if country in COMMA_DECIMAL_COUNTRIES:
            return ","
        if country in DOT_DECIMAL_COUNTRIES:
            return "."
        return "," if text.rfind(",") > text.rfind(".") else "."
    if "," in text:
        return "," if _separator_is_decimal(text, ",") else None
    if "." in text:
        return "." if _separator_is_decimal(text, ".") else None
    return None


def _separator_is_decimal(text: str, separator: str) -> bool:
    final_group_length = _last_group_length(text, separator)
    if final_group_length in {1, 2}:
        return True
    # A grouping (thousands) separator only ever produces groups of exactly
    # three digits. A separator that occurs once with a trailing group of four
    # or more digits (e.g. "128.000000" from an ERP/JSON feed) therefore cannot
    # be grouping — it is an over-precise decimal point. Treat it as the decimal
    # separator instead of deleting it, which would multiply the value by 10ⁿ.
    return final_group_length >= 4 and text.count(separator) == 1


def _last_group_length(text: str, separator: str) -> int:
    return len(text.rsplit(separator, 1)[-1]) if separator in text else 0


def _country_from_locale_hint(locale_hint: str | None) -> str | None:
    normalized = str(locale_hint or "").strip().lower().replace("_", "-")
    if not normalized:
        return None
    parts = [part for part in normalized.split("-") if part]
    return COUNTRY_ALIASES.get(parts[-1], parts[-1]) if parts else None


def _locale_resolves_decimal_ambiguity(locale_hint: str | None) -> bool:
    country = _country_from_locale_hint(locale_hint)
    return country in COMMA_DECIMAL_COUNTRIES or country in DOT_DECIMAL_COUNTRIES
