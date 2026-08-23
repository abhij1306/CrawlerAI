"""Detail-expansion candidate snapshot and admission policy."""

from __future__ import annotations

from typing import NamedTuple

from app.core.config.extraction_rules import (
    BROWSER_REQUESTED_DETAIL_GENERIC_TOGGLE_LABELS,
    DETAIL_BLOCKED_TOKENS,
)


class _CandidateSignals(NamedTuple):
    label: str
    probe: str
    aria_controls: str
    aria_expanded: str
    data_qa_action: str
    class_name: str
    tag_name: str
    href: str
    target: str


def candidate_is_admitted(
    snapshot: dict[str, object],
    *,
    selector: str,
    keywords: tuple[str, ...],
    requested_keywords: tuple[str, ...],
    requested_fields: list[str] | None,
) -> tuple[bool, tuple[str, str, str], str]:
    signals = _CandidateSignals(
        *(
            str(snapshot.get(key) or "").strip().lower()
            for key in _CandidateSignals._fields
        )
    )
    matches = _candidate_matches(signals, keywords, requested_keywords)
    requested_match, fallback_match, generic_match, size_toggle = matches
    blocked = _candidate_blocked(
        snapshot,
        signals,
        requested_fields=requested_fields,
        requested_match=requested_match,
        fallback_match=fallback_match,
        generic_match=generic_match,
        size_toggle=size_toggle,
    )
    expandable = _candidate_expandable(
        selector,
        signals,
        requested_match=requested_match,
        generic_match=generic_match,
    )
    admitted = bool(
        snapshot.get("visible")
        and snapshot.get("actionable")
        and not blocked
        and expandable
    )
    key = (signals.label or signals.probe, signals.aria_controls, signals.tag_name)
    return admitted, key, signals.label or signals.probe


def _candidate_matches(
    signals: _CandidateSignals,
    keywords: tuple[str, ...],
    requested_keywords: tuple[str, ...],
) -> tuple[bool, bool, bool, bool]:
    requested_probe = " ".join(
        part
        for part in (signals.label, signals.aria_controls, signals.data_qa_action)
        if part
    )
    keyword_probe = " ".join(
        part
        for part in (
            signals.label,
            signals.probe,
            signals.data_qa_action,
            signals.class_name,
        )
        if part
    )
    size_toggle = any(
        token in f"{signals.data_qa_action} {signals.class_name}"
        for token in ("size selector", "size-selector", "open-size-selector")
    )
    return (
        bool(
            requested_keywords
            and any(word in requested_probe for word in requested_keywords)
        ),
        any(word in requested_probe for word in keywords),
        any(word in keyword_probe for word in keywords),
        size_toggle,
    )


def _candidate_blocked(
    snapshot: dict[str, object],
    signals: _CandidateSignals,
    *,
    requested_fields: list[str] | None,
    requested_match: bool,
    fallback_match: bool,
    generic_match: bool,
    size_toggle: bool,
) -> bool:
    keyword_probe = " ".join(
        part
        for part in (
            signals.label,
            signals.probe,
            signals.data_qa_action,
            signals.class_name,
        )
        if part
    )
    real_link = all(
        (
            bool(signals.href),
            not signals.href.startswith(("#", "javascript:", "mailto:", "tel:")),
        )
    )
    navigational = all(
        (
            signals.tag_name == "a",
            signals.target in {"_blank", "_new"} or real_link,
            not size_toggle,
        )
    )
    token_blocked = all(
        (
            any(token in keyword_probe for token in DETAIL_BLOCKED_TOKENS),
            not size_toggle,
        )
    )
    unwanted = any(
        token in keyword_probe
        for token in (
            "add-to-wishlist",
            "gallery",
            "media-zoom",
            "thumbnail",
            "wishlist",
        )
    )
    in_chrome = any(
        snapshot.get(key) for key in ("inside_header", "inside_nav", "inside_footer")
    )
    scope_evidence = any(
        (
            signals.aria_controls,
            signals.aria_expanded == "false",
            requested_match,
            fallback_match,
            generic_match,
            size_toggle,
        )
    )
    aside_blocked = bool(snapshot.get("inside_aside")) and not scope_evidence
    generic_toggle = all(
        (
            bool(requested_fields),
            bool(signals.aria_controls),
            signals.label in BROWSER_REQUESTED_DETAIL_GENERIC_TOGGLE_LABELS,
        )
    )
    requested_blocked = bool(requested_fields) and not any(
        (requested_match, fallback_match, generic_toggle, size_toggle)
    )
    return bool(
        navigational
        or token_blocked
        or unwanted
        or (in_chrome and not snapshot.get("inside_main"))
        or aside_blocked
        or requested_blocked
    )


def _candidate_expandable(
    selector: str,
    signals: _CandidateSignals,
    *,
    requested_match: bool,
    generic_match: bool,
) -> bool:
    expandable_selectors = {
        "summary",
        "details > summary",
        "[aria-expanded='false']",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
    }
    return bool(
        selector in expandable_selectors
        or signals.aria_expanded == "false"
        or signals.aria_controls
        or signals.tag_name == "summary"
        or requested_match
        or generic_match
    )


__all__ = ["candidate_is_admitted"]
