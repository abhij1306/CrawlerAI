from __future__ import annotations

import logging
import re

from app.core.config.extraction_rules import (
    DETAIL_NON_PRODUCT_IMAGE_URL_HINTS,
    MATERIAL_KEYWORDS,
    ORG_SUFFIXES,
    PLACEHOLDER_IMAGE_URL_PATTERNS,
    WAF_QUEUE_PATTERNS,
)
from app.core.shared.regex_patterns import compile_regex_patterns

logger = logging.getLogger(__name__)

MAX_STRUCTURED_TEXT_LENGTH = 20_000

UUID_LIKE_PATTERN = re.compile(r"(?i)^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
MERCH_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+\b", re.I)
PLACEHOLDER_IMAGE_URL_PATTERNS_LOWER = tuple(
    str(pattern).lower()
    for pattern in tuple(PLACEHOLDER_IMAGE_URL_PATTERNS or ())
    if str(pattern).strip()
)
NON_PRODUCT_IMAGE_HINTS_LOWER = tuple(
    str(pattern).lower()
    for pattern in tuple(DETAIL_NON_PRODUCT_IMAGE_URL_HINTS or ())
    if str(pattern).strip()
)
DETAIL_STATIC_NOT_FOUND_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^404$"),
    re.compile(r"^(?:error\s*)?404\b", re.I),
    re.compile(r"^error\s+page$", re.I),
    re.compile(r"^your\s+ai-generated\s+outfit$", re.I),
    re.compile(r"^oops,?\s+something\s+went\s+wrong\.?$", re.I),
    re.compile(r"^oops!? the page you['’]re looking for can['’]t be found\.?$", re.I),
    re.compile(r"\bpage\s+not\s+found\b", re.I),
    re.compile(r"\bnothing\s+to\s+see\s+here\b", re.I),
    re.compile(r"\bproduct\s+not\s+found\b", re.I),
    re.compile(r"^page not found$", re.I),
    re.compile(r"^not found$", re.I),
)
DETAIL_BASE_PLACEHOLDER_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    *DETAIL_STATIC_NOT_FOUND_TITLE_PATTERNS,
    re.compile(r"^access denied$", re.I),
    re.compile(r"^adding\s+to\s+cart\.{0,3}$", re.I),
)


def compile_detail_waf_queue_title_patterns() -> tuple[re.Pattern[str], ...]:
    return compile_regex_patterns(
        tuple(WAF_QUEUE_PATTERNS or ()),
        logger=logger,
        warning_message="Skipping invalid WAF queue title pattern: %r",
    )


DETAIL_WAF_QUEUE_TITLE_PATTERNS = compile_detail_waf_queue_title_patterns()
MATERIAL_KEYWORD_TOKENS = frozenset(
    str(token).strip().lower()
    for token in tuple(MATERIAL_KEYWORDS or ())
    if str(token).strip()
)
DETAIL_PLACEHOLDER_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    *DETAIL_BASE_PLACEHOLDER_TITLE_PATTERNS,
    *DETAIL_WAF_QUEUE_TITLE_PATTERNS,
)
# Static fallback includes only deterministic not-found page titles; WAF and
# transient shell titles stay out of this subset.
STATIC_DETAIL_NOT_FOUND_TITLE_PATTERNS = DETAIL_STATIC_NOT_FOUND_TITLE_PATTERNS
STATIC_DETAIL_SHELL_HEADING_PHRASES = (
    "added to cart",
    "new arrivals",
    "men",
    "mens",
    "women",
    "womens",
    "sale",
)
STATIC_DETAIL_SHELL_HEADING_MIN_MATCHES = 2
ORG_SUFFIX_PATTERN = (
    re.compile(
        r"\b(?:"
        + "|".join(re.escape(token) for token in sorted(ORG_SUFFIXES))
        + r")\b",
        re.I,
    )
    if ORG_SUFFIXES
    else None
)
