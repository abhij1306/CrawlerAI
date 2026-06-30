from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.acquisition.browser_readiness import analyze_extractable_content, analyze_html
from app.core.config.block_signatures import BLOCK_SIGNATURES
from app.core.config.extraction_rules._detail import DETAIL_SHELL_TITLE_KEYS
from app.core.db_utils import mapping_or_empty
from app.core.shared.text_coerce import slug_tokens
from app.extraction.documents import HtmlAnalysis, HtmlDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BlockPageClassification:
    blocked: bool
    outcome: str
    evidence: list[str] = field(default_factory=list)
    provider_hits: list[str] = field(default_factory=list)
    active_provider_hits: list[str] = field(default_factory=list)
    strong_hits: list[str] = field(default_factory=list)
    weak_hits: list[str] = field(default_factory=list)
    title_matches: list[str] = field(default_factory=list)
    challenge_element_hits: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _BlockEvidence:
    forced_blocked: bool
    forced_outcome: str
    base_evidence: list[str]
    has_extractable_content: bool
    has_listing_content: bool
    has_product_identity: bool
    shell_title: str
    title_matches: list[str]
    strong_hits: set[str]
    weak_hits: set[str]
    provider_hits: set[str]
    active_provider_hits: set[str]
    challenge_element_hits: set[str]
    hard_strong_hits: set[str]


def _mapping_sequence(value: object) -> list[dict[object, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _marker_map_from_config(
    source: Mapping[str, object],
    key: str,
) -> dict[str, str]:
    return {
        str(marker or "").strip().lower(): str(hit or "").strip()
        for marker, hit in mapping_or_empty(source.get(key)).items()
        if str(marker or "").strip() and str(hit or "").strip()
    }


def _challenge_element_hits(
    document: HtmlDocument,
    lowered_html: str,
    *,
    signatures: Mapping[str, object],
) -> list[str]:
    config = mapping_or_empty(signatures.get("challenge_elements"))
    iframe_src = _marker_map_from_config(config, "iframe_src_markers")
    iframe_title = _marker_map_from_config(config, "iframe_title_markers")
    script_src = _marker_map_from_config(config, "script_src_markers")
    html_markers = _marker_map_from_config(config, "html_markers")
    hits: list[str] = []
    for iframe in document.css("iframe"):
        src = str(iframe.attribute("src") or "").strip().lower()
        title = str(iframe.attribute("title") or "").strip().lower()
        hits.extend(hit for marker, hit in iframe_src.items() if marker in src)
        hits.extend(hit for marker, hit in iframe_title.items() if marker in title)
    for script in document.css("script"):
        src = str(script.attribute("src") or "").strip().lower()
        hits.extend(hit for marker, hit in script_src.items() if marker in src)
    hits.extend(hit for marker, hit in html_markers.items() if marker in lowered_html)
    return hits


def _status_block_state(
    status_code: int,
) -> tuple[BlockPageClassification | None, bool, str, list[str]]:
    code = int(status_code or 0)
    if code == 401:
        return (
            BlockPageClassification(
                blocked=False,
                outcome="auth_wall",
                evidence=[f"http_status:{code}"],
            ),
            False,
            "",
            [],
        )
    if code == 429:
        return None, True, "rate_limited", [f"http_status:{code}"]
    if code == 403:
        return None, True, "challenge_page", [f"http_status:{code}"]
    return None, False, "", []


def _title_block_matches(
    title_text: str,
    shell_title: str,
    *,
    signatures: Mapping[str, object],
) -> list[str]:
    matches: list[str] = []
    for pattern in _string_sequence(signatures.get("title_regexes")):
        raw_pattern = str(pattern or "").strip()
        if not raw_pattern:
            continue
        try:
            if re.search(raw_pattern, title_text, re.IGNORECASE):
                matches.append(raw_pattern)
        except re.error as exc:
            logger.warning(
                "Skipping invalid block signature title regex %r: %s",
                raw_pattern,
                exc,
            )
    if shell_title and shell_title not in matches:
        matches.append(shell_title)
    return matches


def _configured_marker_hits(
    config_key: str,
    *,
    visible_text: str,
    title_text: str,
    signatures: Mapping[str, object],
) -> set[str]:
    markers = mapping_or_empty(signatures.get(config_key)).keys()
    return {
        normalized
        for marker in markers
        if (normalized := str(marker or "").strip().lower())
        and (normalized in visible_text or normalized in title_text)
    }


def _has_product_identity_content(analysis: HtmlAnalysis) -> bool:
    heading = analysis.document.css_first("main h1, article h1, [role='main'] h1, h1")
    heading_text = " ".join(slug_tokens(heading.text() if heading else ""))
    if heading_text and not any(
        marker in heading_text
        for marker in (
            "captcha",
            "access denied",
            "access forbidden",
            "human verification",
            "just a moment",
            "security check",
        )
    ):
        return True
    product_types = {"product", "productmodel"}
    for script in analysis.document.safe_css('script[type*="ld+json"]'):
        try:
            payload = script.json()
        except (TypeError, ValueError):
            continue
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_type = row.get("@type")
            values = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(
                str(value or "").strip().lower() in product_types for value in values
            ):
                return True
    return any(
        str(node.attribute("content") or "").strip().lower() == "product"
        for node in analysis.document.safe_css('[property="og:type"][content]')
    )


def _collect_block_evidence(
    html: str,
    *,
    analysis: HtmlAnalysis,
    signatures: Mapping[str, object],
    forced_blocked: bool,
    forced_outcome: str,
    base_evidence: list[str],
) -> _BlockEvidence:
    lowered = str(html or "").lower()
    visible_text = analysis.visible_text.lower()
    title_text = analysis.title_text.lower()
    normalized_title = " ".join(slug_tokens(title_text))
    shell_title = (
        normalized_title if normalized_title in DETAIL_SHELL_TITLE_KEYS else ""
    )
    content_signals = analyze_extractable_content(html, analysis=analysis)
    strong_hits = _configured_marker_hits(
        "browser_challenge_strong_markers",
        visible_text=visible_text,
        title_text=title_text,
        signatures=signatures,
    )
    weak_hits = _configured_marker_hits(
        "browser_challenge_weak_markers",
        visible_text=visible_text,
        title_text=title_text,
        signatures=signatures,
    )
    provider_hits = {
        normalized
        for marker in _string_sequence(signatures.get("provider_markers"))
        if (normalized := str(marker or "").strip().lower()) and normalized in lowered
    }
    active_provider_hits = {
        normalized
        for item in _mapping_sequence(signatures.get("active_provider_markers"))
        if (normalized := str(item.get("marker") or "").strip().lower())
        and normalized in lowered
    }
    content_tolerant = {
        str(marker or "").strip().lower()
        for marker in _string_sequence(
            signatures.get("content_tolerant_strong_markers")
        )
        if str(marker or "").strip()
    }
    return _BlockEvidence(
        forced_blocked=forced_blocked,
        forced_outcome=forced_outcome,
        base_evidence=base_evidence,
        has_extractable_content=content_signals.detail or content_signals.listing,
        has_listing_content=content_signals.listing,
        has_product_identity=_has_product_identity_content(analysis),
        shell_title=shell_title,
        title_matches=_title_block_matches(
            title_text,
            shell_title,
            signatures=signatures,
        ),
        strong_hits=strong_hits,
        weak_hits=weak_hits,
        provider_hits=provider_hits,
        active_provider_hits=active_provider_hits,
        challenge_element_hits=set(
            _challenge_element_hits(
                analysis.document,
                lowered,
                signatures=signatures,
            )
        ),
        hard_strong_hits=strong_hits - content_tolerant,
    )


def _block_policy_matches(evidence: _BlockEvidence) -> bool:
    strong = evidence.strong_hits
    hard = evidence.hard_strong_hits
    providers = evidence.provider_hits
    active = evidence.active_provider_hits
    elements = evidence.challenge_element_hits
    titles = evidence.title_matches
    return evidence.forced_blocked or bool(
        len(hard) >= 2
        or (hard and (providers or active or elements or titles))
        or (evidence.shell_title and not evidence.has_extractable_content)
        or "access denied" in strong
        or (
            "just a moment" in strong
            and (
                "cloudflare" in providers
                or "cf-challenge" in providers
                or "cf-browser-verification" in active
            )
        )
        or (elements and (providers or active))
        or (active and strong and not evidence.has_extractable_content)
        or (titles and elements)
        or (
            titles
            and not evidence.has_extractable_content
            and not evidence.has_product_identity
        )
        or (hard and evidence.weak_hits and providers)
        or (
            "captcha" in strong
            and providers
            and (not evidence.has_extractable_content or bool(titles))
        )
    )


def _classification_from_evidence(evidence: _BlockEvidence) -> BlockPageClassification:
    blocked = _block_policy_matches(evidence)
    if (
        blocked
        and evidence.has_extractable_content
        and not evidence.title_matches
        and (not evidence.hard_strong_hits or evidence.hard_strong_hits <= {"captcha"})
    ):
        blocked = False
    evidence_rows = [
        *evidence.base_evidence,
        *sorted(f"title:{item}" for item in evidence.title_matches),
        *sorted(f"strong:{item}" for item in evidence.strong_hits),
        *sorted(f"weak:{item}" for item in evidence.weak_hits),
        *sorted(f"provider:{item}" for item in evidence.provider_hits),
        *sorted(f"active_provider:{item}" for item in evidence.active_provider_hits),
        *sorted(
            f"challenge_element:{item}" for item in evidence.challenge_element_hits
        ),
    ]
    outcome = (
        evidence.forced_outcome
        if blocked and evidence.forced_blocked
        else "challenge_page"
        if blocked
        else "ok"
    )
    return BlockPageClassification(
        blocked=blocked,
        outcome=outcome,
        evidence=evidence_rows,
        provider_hits=sorted(evidence.provider_hits),
        active_provider_hits=sorted(evidence.active_provider_hits),
        strong_hits=sorted(evidence.strong_hits),
        weak_hits=sorted(evidence.weak_hits),
        title_matches=evidence.title_matches,
        challenge_element_hits=sorted(evidence.challenge_element_hits),
    )


def classify_blocked_page(
    html: str,
    status_code: int,
    *,
    analysis: HtmlAnalysis | None = None,
    signatures: Mapping[str, object] = BLOCK_SIGNATURES,
) -> BlockPageClassification:
    early, forced_blocked, forced_outcome, base_evidence = _status_block_state(
        status_code
    )
    if early is not None:
        return early
    if not str(html or "").strip():
        if forced_blocked:
            return BlockPageClassification(
                blocked=True,
                outcome=forced_outcome,
                evidence=base_evidence,
            )
        return BlockPageClassification(blocked=False, outcome="empty")
    resolved_analysis = analysis or analyze_html(html)
    return _classification_from_evidence(
        _collect_block_evidence(
            html,
            analysis=resolved_analysis,
            signatures=signatures,
            forced_blocked=forced_blocked,
            forced_outcome=forced_outcome,
            base_evidence=base_evidence,
        )
    )


__all__ = ["BlockPageClassification", "classify_blocked_page"]
