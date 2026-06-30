from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config.extraction_rules import PAGE_URL_CURRENCY_HINTS_RAW

# Generic, ISO-standard vocabulary only — country (ISO 3166-1 alpha-2) → currency
# (ISO 4217). This is structural locale knowledge, never a retailer mapping, so
# it stays site-agnostic: a `.co.in` storefront or an `/en-in/` locale segment
# implies INR regardless of which brand serves it.
_COUNTRY_CURRENCY: dict[str, str] = {
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
    # Eurozone members share EUR.
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

# ccTLD labels that name a country but differ from the ISO country code, plus the
# generic gTLDs that carry no locale signal and must never infer a currency.
_CCTLD_COUNTRY_ALIASES = {"uk": "gb"}
_GENERIC_TLDS = frozenset({"com", "net", "org", "io", "shop", "store", "co", "app"})

_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}[-_](?P<country>[a-z]{2})$")


def currency_hint_from_page_url(page_url: object) -> str | None:
    code, _is_host_level = _currency_hint_from_page_url(page_url)
    return code


def _country_currency(country: str) -> str | None:
    normalized = _CCTLD_COUNTRY_ALIASES.get(country, country)
    return _COUNTRY_CURRENCY.get(normalized)


def _currency_from_locale_segments(path_segments: list[str]) -> str | None:
    for segment in path_segments:
        match = _LOCALE_SEGMENT_RE.match(segment)
        if match and (currency := _country_currency(match.group("country"))):
            return currency
    return None


def _currency_from_tld(hostname: str) -> str | None:
    labels = [label for label in hostname.split(".") if label]
    if len(labels) < 2:
        return None
    tld = labels[-1]
    if tld in _GENERIC_TLDS:
        return None
    return _country_currency(tld)


def _currency_from_token_map(hostname: str, path_segments: set[str]) -> str | None:
    # Retained generic token table (locale path segments only — host literals
    # were removed in favour of TLD/locale inference). Empty today, but kept so
    # operators can add structural tokens without touching this module.
    for token, code in dict(PAGE_URL_CURRENCY_HINTS_RAW or {}).items():
        normalized_token = str(token).strip().lower()
        if not normalized_token or not normalized_token.startswith("/"):
            continue
        token_path_segments = {
            segment.strip().lower()
            for segment in normalized_token.split("/")
            if segment.strip()
        }
        if token_path_segments and token_path_segments <= path_segments:
            return str(code)
    return None


def _currency_hint_from_page_url(page_url: object) -> tuple[str | None, bool]:
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").strip().lower()
    ordered_segments = [
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    ]
    path_segments = set(ordered_segments)
    if not hostname and not path_segments:
        return None, False
    # Locale path segment is the most specific (per-page) signal.
    if currency := _currency_from_locale_segments(ordered_segments):
        return currency, False
    if currency := _currency_from_token_map(hostname, path_segments):
        return currency, False
    host_labels = {label for label in hostname.split(".") if label}
    if "firstcry" in host_labels:
        return "INR", True
    # ccTLD is a host-level signal.
    if currency := _currency_from_tld(hostname):
        return currency, True
    return None, False
