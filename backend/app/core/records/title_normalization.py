"""Detail title display normalization.

Owns the rules that turn a raw source title into the value published as product
identity: site-name boilerplate derived from the page host, marketplace prefixes
and breadcrumb separators, and trademark notation. Kept apart from URL identity
so title display rules have one owner.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config.extraction_rules import (
    DETAIL_HOST_GENERIC_LABELS,
    DETAIL_IDENTITY_TRADEMARK_SYMBOL_PATTERN,
    DETAIL_NON_LOWER_ALNUM_PATTERN,
    DETAIL_TITLE_MARKETPLACE_CATEGORY_SUFFIX_PATTERN,
    DETAIL_TITLE_MARKETPLACE_PREFIX_PATTERN,
    DETAIL_TITLE_SITE_SUFFIX_MAX_WORDS,
    DETAIL_TITLE_SITE_SUFFIX_MIN_REMAINDER_WORDS,
    DETAIL_TITLE_SITE_SUFFIX_SEPARATOR_PATTERN,
)

__all__ = [
    "host_identity_keys",
    "normalize_detail_marketplace_title",
    "strip_detail_title_site_suffix",
    "strip_identity_trademark_symbols",
]


def host_identity_keys(url: str) -> frozenset[str]:
    """Alphanumeric keys that a site's own name would collapse to.

    Both the whole registrable host and each meaningful label are returned, so a
    title suffix can match either the full site name (``bhphotovideo``) or a
    single label of a subdomain host (``canon`` from ``usa.canon.com``).
    """
    host = str(urlparse(url).hostname or "").casefold()
    labels = [
        re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", label)
        for label in host.split(".")
        if label not in DETAIL_HOST_GENERIC_LABELS
    ]
    keys = {"".join(labels), *(label for label in labels if len(label) >= 3)}
    return frozenset(key for key in keys if key)


def _is_site_identity_segment(segment: str, host_keys: frozenset[str]) -> bool:
    key = re.sub(DETAIL_NON_LOWER_ALNUM_PATTERN, "", segment.casefold())
    if (
        len(key) < 2
        or len(re.findall(r"\w+", segment)) > DETAIL_TITLE_SITE_SUFFIX_MAX_WORDS
    ):
        return False
    # ``key.startswith`` covers a site name carrying a region/legal tail
    # ("Karen Millen ROW", "Canon U.S.A., Inc."); the reverse covers an
    # abbreviated site name ("B&H" for bhphotovideo).
    return any(
        key == host or key.startswith(host) or host.startswith(key)
        for host in host_keys
    )


def strip_detail_title_site_suffix(value: str, *, page_url: str) -> str:
    """Drop trailing segments that merely repeat the site's own name."""
    host_keys = host_identity_keys(page_url)
    if not host_keys:
        return value
    remaining = value
    while separators := list(
        re.finditer(DETAIL_TITLE_SITE_SUFFIX_SEPARATOR_PATTERN, remaining)
    ):
        tail = remaining[separators[-1].end() :]
        if not _is_site_identity_segment(tail, host_keys):
            return remaining
        head = remaining[: separators[-1].start()].strip()
        # Never strip the product name itself away.
        if len(re.findall(r"\w+", head)) < DETAIL_TITLE_SITE_SUFFIX_MIN_REMAINDER_WORDS:
            return remaining
        remaining = head
    return remaining


def strip_identity_trademark_symbols(value: str) -> str:
    """Drop trademark/service-mark symbols from an identity value.

    ``Millennium Falcon® 75192`` and ``Millennium Falcon 75192`` name the same
    product; whether the symbol survives depends on which source a site happens
    to expose, not on the product. Removing it makes title/brand values stable
    across sources without touching any site-specific vocabulary. Whitespace is
    recollapsed so a symbol that stood alone between words does not leave a gap.
    """
    stripped = re.sub(DETAIL_IDENTITY_TRADEMARK_SYMBOL_PATTERN, "", value)
    return re.sub(r"\s+", " ", stripped).strip()


def normalize_detail_marketplace_title(value: str, *, page_url: str = "") -> str:
    normalized = re.sub(
        DETAIL_TITLE_MARKETPLACE_PREFIX_PATTERN, "", value, flags=re.IGNORECASE
    )
    normalized = re.sub(r"^\s*\+\s+", "", normalized)
    pipe_parts = [part.strip() for part in normalized.split("|") if part.strip()]
    if len(pipe_parts) >= 3:
        # Three or more pipe segments are almost always a breadcrumb-style
        # title ("Product | Category | Site"). The first segment is the
        # canonical product name; the rest are taxonomy/site context.
        normalized = pipe_parts[0]
    elif len(pipe_parts) == 2:
        # Two pipe segments can be either "Title | Site" or part of the product
        # name itself ("Soleil Pant | Smoked Walnut"). Shape alone cannot tell
        # them apart - a colour or edition is also short - so the trailing
        # segment is only dropped when the page host confirms it is the site's
        # own name. Shape still gates it, to keep a long tail from being read
        # as a suffix.
        trailing = pipe_parts[-1]
        trailing_words = len(re.findall(r"\w+", trailing))
        if (
            trailing_words <= 2
            and len(trailing) < len(pipe_parts[0])
            and _is_site_identity_segment(trailing, host_identity_keys(page_url))
        ):
            normalized = pipe_parts[0]
    normalized = _strip_marketplace_site_suffix(normalized)
    normalized = re.sub(
        DETAIL_TITLE_MARKETPLACE_CATEGORY_SUFFIX_PATTERN,
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    # Runs last so the breadcrumb/pipe rules above still see the full title; it
    # only removes what those rules leave behind and the host confirms is a site
    # name.
    normalized = strip_detail_title_site_suffix(normalized, page_url=page_url)
    return strip_identity_trademark_symbols(normalized)


def _strip_marketplace_site_suffix(value: str) -> str:
    title, separator, raw_suffix = value.rpartition(" - ")
    if not separator:
        return value
    suffix = raw_suffix.strip()
    terminal = next(
        (
            candidate
            for candidate in (
                "Official Site",
                "Watches",
                "India",
                "USA",
                "US",
                "UK",
            )
            if suffix.endswith(candidate)
        ),
        "",
    )
    body = suffix[: -len(terminal)] if terminal else ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789&'.- ")
    if (
        suffix[:1].isupper()
        and 3 <= len(body) <= 41
        and all(character in allowed for character in body)
    ):
        return title.rstrip()
    return value
