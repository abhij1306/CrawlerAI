"""Generic semantic roles for form controls that are *not* product options.

The DOM variant collector previously admitted every ``<select><option>`` on a
page as a size axis (``collectors/dom.py`` catch-all). Real pages carry many
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


def has_product_option_signal(tokens: frozenset[str], *, axis: str = "") -> bool:
    """True when a select positively signals a product option (never a control)."""
    if tokens & SELECT_PRODUCT_OPTION_SIGNAL_TOKENS:
        return True
    return bool(axis) and axis.casefold() in tokens


__all__ = [
    "SELECT_CONTROL_REJECT_ROLE_TOKENS",
    "SELECT_CONTROL_REJECT_TOKENS",
    "SELECT_CONTROL_REJECT_PHRASES",
    "SELECT_PRODUCT_OPTION_SIGNAL_TOKENS",
    "SELECT_CONTROL_SIGNAL_ATTRIBUTES",
    "control_signal_tokens",
    "is_rejected_control",
    "has_product_option_signal",
]
