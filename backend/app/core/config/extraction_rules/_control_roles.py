"""Generic semantic roles for form controls that are *not* product options.

The old DOM selector collector admitted every ``<select><option>`` on a
page as a size axis. Real pages carry many
selects that have nothing to do with product variants — review sorters, country
/ currency / language pickers, quantity steppers, pagination, address fields —
and each one became a bogus size axis (crawl-run-95 audit: results 10, 17, 21,
58, 70, 79, 95).

These rules classify a select by *semantic role* using tokens that appear in its
identifying attributes (``name``/``id``/``class``/``aria-label``/``data-*``).
They are deliberately site-agnostic: roles, never host names, so the
``test_extraction_carries_no_retailer_domain_literals`` genericness ratchet
stays green.
"""

from __future__ import annotations

import re

# Tokens (matched as discrete identifier tokens, see ``control_signal_tokens``)
# whose presence marks a select as a non-product control. Grouped by role for
# readability; the collector only needs "is this a rejected control?".
SELECT_CONTROL_REJECT_ROLE_TOKENS: dict[str, frozenset[str]] = {
    "sort": frozenset({"sort", "sortby", "orderby"}),
    "pagination": frozenset({"pagination", "paginate", "perpage", "pagesize"}),
    "quantity": frozenset({"qty", "quantity"}),
    "geography": frozenset(
        {
            "country",
            "countries",
            "region",
            "province",
            "state",
            "locale",
            "currency",
            "language",
            "lang",
            "timezone",
            "postcode",
            "zipcode",
            "salutation",
        }
    ),
    "review": frozenset({"review", "reviews", "rating", "ratings"}),
    "filter": frozenset({"filter", "search"}),
}
# Flattened reject set for O(1) membership tests.
SELECT_CONTROL_REJECT_TOKENS: frozenset[str] = frozenset(
    token for tokens in SELECT_CONTROL_REJECT_ROLE_TOKENS.values() for token in tokens
)
# Multi-word reject phrases that a single token split would miss.
SELECT_CONTROL_REJECT_PHRASES: tuple[str, ...] = (
    "per page",
    "page size",
    "items per page",
    "sort by",
    "order by",
    "ship to",
)
# Tokens that positively signal a genuine product-option control. A select must
# carry at least one of these (or the axis name itself) to become an axis.
SELECT_PRODUCT_OPTION_SIGNAL_TOKENS: frozenset[str] = frozenset(
    {
        "option",
        "options",
        "variant",
        "variants",
        "attribute",
        "attributes",
        "swatch",
        "swatches",
        "sku",
        "product",
    }
)
# --- Value-level option gating -------------------------------------------
# The tokens above classify a *control* (the whole select). These reject
# individual option *values* that are navigation/menu entries masquerading as a
# variant value, e.g. Petco "Shop by tank size", Birkenstock "Shop By Color",
# Clinique "Travel Sizes + Minis" (crawl-run-2 audit: results 190, 186, 134).
# Site-agnostic English merchandising phrases, never host names.
OPTION_VALUE_REJECT_PHRASES: tuple[str, ...] = (
    "shop by",
    "browse by",
    "filter by",
    "sort by",
    "view all",
    "see all",
    "show all",
    "more colors",
    "more colours",
    "true to size",
)
# Multi-token menu labels: a value is rejected when one of these token *sets* is
# a subset of its tokens ("Travel Sizes + Minis" -> {travel, sizes, minis}).
OPTION_VALUE_REJECT_TOKEN_SETS: tuple[frozenset[str], ...] = (
    frozenset({"travel", "size"}),
    frozenset({"travel", "sizes"}),
    frozenset({"gift", "set"}),
)
# Standalone tokens/exact values that are never a real option value.
OPTION_VALUE_REJECT_TOKENS: frozenset[str] = frozenset({"minis"})
OPTION_VALUE_REJECT_EXACT: frozenset[str] = frozenset(
    {"compare", "select", "choose", "none"}
)
# A bare all-digit value with at least this many digits is an opaque platform id
# (e.g. Shopify variant ids like "42434363129927"), not a size. Legitimate sizes
# (waist 44, EU shoe 50) are well under this, so the axis is preserved.
OPTION_VALUE_OPAQUE_NUMERIC_MIN_DIGITS: int = 8

_OPTION_VALUE_COUNTED_MORE_PATTERN = re.compile(r"\b\d+\s+more\b")

# Attribute names whose *keys* and values contribute identifying tokens.
SELECT_CONTROL_SIGNAL_ATTRIBUTES: tuple[str, ...] = (
    "name",
    "id",
    "class",
    "aria-label",
    "title",
    "data-option-name",
    "data-attribute",
    "data-selector",
    "data-testid",
    "placeholder",
)

_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")
_CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def control_signal_tokens(values: object) -> frozenset[str]:
    """Split identifying attribute values into discrete lowercase tokens.

    Splits on non-alphanumeric separators *and* camelCase boundaries so that
    ``sortSelect``, ``country_code`` and ``super-attribute-select`` all yield the
    role-bearing tokens (``sort``, ``country``, ``attribute``).
    """
    tokens: set[str] = set()
    parts = values if isinstance(values, (list, tuple)) else (values,)
    for part in parts:
        text = str(part or "")
        if not text:
            continue
        camel_split = _CAMEL_BOUNDARY_PATTERN.sub(" ", text)
        for token in _TOKEN_SPLIT_PATTERN.split(camel_split.casefold()):
            if token:
                tokens.add(token)
    return frozenset(tokens)


def is_rejected_control(tokens: frozenset[str], *, signal: str = "") -> bool:
    """True when a select's tokens/signal mark it as a non-product control."""
    if tokens & SELECT_CONTROL_REJECT_TOKENS:
        return True
    haystack = signal.casefold()
    return any(phrase in haystack for phrase in SELECT_CONTROL_REJECT_PHRASES)


def is_rejected_option_value(value: object) -> bool:
    """True when an option *value* is navigation/menu/opaque noise, not a variant.

    Rejects merchandising phrases ("shop by tank size", "more colors"), category
    /travel-size menu labels ("Travel Sizes + Minis"), informational controls
    ("compare", "select") and opaque platform ids (bare all-digit tokens with
    >= ``OPTION_VALUE_OPAQUE_NUMERIC_MIN_DIGITS`` digits). Genuine size/color
    values ("Size 4-4.5", "44", "Heritage Royal") are preserved.
    """
    text = str(value or "").strip()
    if not text:
        return False
    haystack = text.casefold()
    if any(phrase in haystack for phrase in OPTION_VALUE_REJECT_PHRASES):
        return True
    if _OPTION_VALUE_COUNTED_MORE_PATTERN.search(haystack):
        return True
    tokens = control_signal_tokens(text)
    if tokens & OPTION_VALUE_REJECT_TOKENS:
        return True
    if any(token_set <= tokens for token_set in OPTION_VALUE_REJECT_TOKEN_SETS):
        return True
    if haystack in OPTION_VALUE_REJECT_EXACT:
        return True
    digits = "".join(char for char in text if char.isdigit())
    if (
        digits == re.sub(r"\s+", "", text)
        and len(digits) >= OPTION_VALUE_OPAQUE_NUMERIC_MIN_DIGITS
    ):
        return True
    return False


def has_product_option_signal(tokens: frozenset[str], *, axis: str = "") -> bool:
    """True when a select positively signals a product option (never a control)."""
    if tokens & SELECT_PRODUCT_OPTION_SIGNAL_TOKENS:
        return True
    if axis.casefold() == "color" and "colour" in tokens:
        return True
    return bool(axis) and axis.casefold() in tokens


__all__ = [
    "SELECT_CONTROL_REJECT_ROLE_TOKENS",
    "SELECT_CONTROL_REJECT_TOKENS",
    "SELECT_CONTROL_REJECT_PHRASES",
    "SELECT_PRODUCT_OPTION_SIGNAL_TOKENS",
    "SELECT_CONTROL_SIGNAL_ATTRIBUTES",
    "OPTION_VALUE_REJECT_PHRASES",
    "OPTION_VALUE_REJECT_TOKEN_SETS",
    "OPTION_VALUE_REJECT_TOKENS",
    "OPTION_VALUE_REJECT_EXACT",
    "OPTION_VALUE_OPAQUE_NUMERIC_MIN_DIGITS",
    "control_signal_tokens",
    "is_rejected_control",
    "is_rejected_option_value",
    "has_product_option_signal",
]
