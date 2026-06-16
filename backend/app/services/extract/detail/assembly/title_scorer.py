from __future__ import annotations

__all__ = (
    "promote_detail_title",
    "title_needs_promotion",
)

import re
from collections.abc import Callable
from urllib.parse import urlparse
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_LOW_SIGNAL_TITLE_VALUES,
    TITLE_PROMOTION_EXACT_VALUES,
    TITLE_PROMOTION_PREFIXES,
    TITLE_PROMOTION_SEPARATOR,
    TITLE_PROMOTION_SUBSTRINGS,
)
from app.services.shared.field_coerce import is_title_noise, text_or_none
from app.services.extract.contracts import CandidateSet, RawCandidate

_low_signal_title_values = frozenset(
    str(value).strip().lower()
    for value in tuple(DETAIL_LOW_SIGNAL_TITLE_VALUES or ())
    if str(value).strip()
)
_title_promotion_exact_values = frozenset(
    str(value).strip().lower()
    for value in tuple(TITLE_PROMOTION_EXACT_VALUES or ())
    if str(value).strip()
)


def promote_detail_title(
    record: dict[str, Any],
    *,
    page_url: str,
    candidate_set: CandidateSet,
    source_rank: Callable[[str, str, str | None], int],
) -> RawCandidate | None:
    title = text_or_none(record.get("title"))
    if not title or not title_needs_promotion(title, page_url=page_url):
        return None
    force_semantic_replacement = (
        title.strip().lower() in _title_promotion_exact_values
        or _title_is_host_shell(title, page_url=page_url)
    )
    ranked_candidates = candidate_set.ordered(
        "title",
        source_rank=lambda source: source_rank(
            "ecommerce_detail",
            "title",
            source,
        ),
    )
    current_rank = min(
        (
            source_rank("ecommerce_detail", "title", candidate.source)
            for candidate in ranked_candidates
            if text_or_none(candidate.value) == title
        ),
        default=source_rank("ecommerce_detail", "title", "dom_h1"),
    )
    replacement = next(
        (
            candidate
            for candidate in ranked_candidates
            if (candidate_text := text_or_none(candidate.value))
            and candidate_text != title
            and not is_title_noise(candidate_text)
            and (
                source_rank("ecommerce_detail", "title", candidate.source) < current_rank
                or (
                    source_rank("ecommerce_detail", "title", candidate.source)
                    == current_rank
                    and len(candidate_text) > len(title)
                )
                or (force_semantic_replacement and len(candidate_text) > len(title))
            )
        ),
        None,
    )
    if replacement:
        record["title"] = replacement.value
        return replacement
    return None


def title_needs_promotion(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    if not normalized_title:
        return False
    if normalized_title in _low_signal_title_values:
        return not _title_supported_by_url(normalized_title, page_url=page_url)
    if is_title_noise(normalized_title):
        return True
    if normalized_title in _title_promotion_exact_values:
        return not _title_supported_by_url(normalized_title, page_url=page_url)
    if any(normalized_title.startswith(prefix) for prefix in TITLE_PROMOTION_PREFIXES):
        return True
    if TITLE_PROMOTION_SEPARATOR in normalized_title:
        return True
    if any(substring in normalized_title for substring in TITLE_PROMOTION_SUBSTRINGS):
        return True
    return _title_is_host_shell(normalized_title, page_url=page_url)


def _title_is_host_shell(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    host = str(urlparse(page_url).hostname or "").strip().lower()
    if not normalized_title or not host:
        return False
    normalized_host = host.removeprefix("www.")
    host_label = normalized_host.split(".", 1)[0]
    compact_title = re.sub(r"[^a-z0-9]+", "", normalized_title)
    compact_host = re.sub(r"[^a-z0-9]+", "", host_label)
    compact_full_host = re.sub(r"[^a-z0-9]+", "", normalized_host)
    return compact_title in {compact_host, compact_full_host}


def _title_supported_by_url(title: str, *, page_url: str) -> bool:
    title_tokens = {
        token for token in re.split(r"[^a-z0-9]+", title.lower()) if len(token) >= 3
    }
    if not title_tokens:
        return False
    segments = [
        segment
        for segment in urlparse(page_url).path.lower().strip("/").split("/")
        if segment
    ]
    path_segment = segments[-1] if segments else ""
    path_tokens = {
        token for token in re.split(r"[^a-z0-9]+", path_segment) if len(token) >= 3
    }
    return bool(path_tokens) and title_tokens <= path_tokens
