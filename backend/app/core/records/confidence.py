from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from app.core.config.extraction_rules import SOURCE_TIERS
from app.core.config.field_mappings import CANONICAL_SCHEMAS
from app.core.records.field_policy import (
    get_surface_field_aliases,
    normalize_field_key,
    repair_target_fields_for_surface,
)

_GENERIC_TITLE_RE = re.compile(
    r"^(product|item|details?|job|career opportunity|untitled|listing)$",
    re.I,
)
_PRICEISH_RE = re.compile(r"\d")
_URLISH_RE = re.compile(r"^https?://", re.I)


def score_record_confidence(
    record: dict[str, Any],
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate an explainable record-confidence percentage.

    Score composition:
    - 65% field coverage
    - 25% source reliability
    - 10% value validity

    Unknown provenance receives zero source-reliability points rather than a
    fabricated fallback score.
    """
    normalized_surface = str(surface or "").strip().lower()
    weights = _surface_field_weights(
        normalized_surface,
        requested_fields=requested_fields,
    )
    field_sources = _normalized_field_sources(record)
    present_fields: list[str] = []
    missing_fields: list[str] = []
    penalties: list[dict[str, Any]] = []
    source_scores: list[float] = []
    source_tier_weights: defaultdict[str, float] = defaultdict(float)

    total_weight = sum(weights.values()) or 1.0
    present_weight = 0.0
    valid_weight = 0.0

    for field_name, weight in weights.items():
        value = _resolved_field_value(record, field_name, normalized_surface)
        if value in (None, "", [], {}):
            missing_fields.append(field_name)
            continue

        present_fields.append(field_name)
        present_weight += weight
        field_penalties = _field_penalties(
            surface=normalized_surface,
            field_name=field_name,
            value=value,
            sources=field_sources.get(field_name),
        )
        penalty_total = min(
            sum(float(item.get("weight") or 0.0) for item in field_penalties),
            1.0,
        )
        valid_weight += weight * (1.0 - penalty_total)
        penalties.extend(field_penalties)

        source_result = _field_source_quality_or_none(
            field_sources.get(field_name),
            fallback_source=record.get("_source"),
        )
        if source_result is not None:
            source_quality, tier_name = source_result
            source_scores.append(source_quality)
            source_tier_weights[tier_name] += weight

    coverage_ratio = present_weight / total_weight
    validity_ratio = valid_weight / present_weight if present_weight else 0.0
    source_ratio = sum(source_scores) / len(source_scores) if source_scores else 0.0

    coverage_points = 65.0 * coverage_ratio
    source_points = 25.0 * source_ratio
    validity_points = 10.0 * validity_ratio
    normalized_score = round(
        max(0.0, min((coverage_points + source_points + validity_points) / 100.0, 1.0)),
        4,
    )

    raw_requested = [
        " ".join(str(field or "").split()).strip()
        for field in requested_fields or []
        if " ".join(str(field or "").split()).strip()
    ]
    requested = repair_target_fields_for_surface(normalized_surface, raw_requested)
    requested_found_total = sum(
        1
        for field_name in requested
        if _resolved_field_value(record, field_name, normalized_surface)
        not in (None, "", [], {})
    )

    return {
        "score": normalized_score,
        "level": _confidence_level(normalized_score),
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "requested_fields_total": len(raw_requested) if raw_requested else len(requested),
        "requested_fields_found_best": requested_found_total,
        "penalties": [
            {
                "field": str(item["field"]),
                "kind": str(item["kind"]),
                "weight": round(float(item["weight"]), 3),
            }
            for item in penalties
        ],
        "source_tier": _source_reasoning(source_tier_weights),
        "components": {
            "coverage": {
                "weight": 0.65,
                "ratio": round(coverage_ratio, 4),
                "points": round(coverage_points, 2),
            },
            "source_reliability": {
                "weight": 0.25,
                "ratio": round(source_ratio, 4),
                "points": round(source_points, 2),
                "fields_with_provenance": len(source_scores),
                "applicable": bool(source_scores),
            },
            "value_validity": {
                "weight": 0.10,
                "ratio": round(validity_ratio, 4),
                "points": round(validity_points, 2),
            },
        },
        "formula": "65% field coverage + 25% source reliability + 10% value validity",
    }


def _surface_field_weights(
    normalized_surface: str,
    *,
    requested_fields: list[str] | None,
) -> dict[str, float]:
    requested = repair_target_fields_for_surface(
        normalized_surface,
        requested_fields or [],
    )
    fields = requested or list(CANONICAL_SCHEMAS.get(normalized_surface) or [])
    if not fields:
        fields = ["title", "description", "image_url", "price", "company", "location"]
    return dict.fromkeys(fields, 1.0)


def _score_weighted_fields(
    record: dict[str, Any],
    normalized_surface: str,
    weights: dict[str, float],
    field_sources: dict[str, list[str]],
) -> tuple[
    float,
    float,
    list[str],
    list[str],
    list[dict[str, Any]],
    defaultdict[str, float],
]:
    total_weight = sum(weights.values()) or 1.0
    score = 0.0
    present_fields: list[str] = []
    missing_fields: list[str] = []
    penalties: list[dict[str, Any]] = []
    source_tier_weights: defaultdict[str, float] = defaultdict(float)
    for field_name, weight in weights.items():
        value = record.get(field_name)
        if value in (None, "", [], {}):
            missing_fields.append(field_name)
            continue
        present_fields.append(field_name)
        source_quality, tier_name = _field_source_quality(
            field_sources.get(field_name),
            fallback_source=record.get("_source"),
        )
        penalty_items = _field_penalties(
            surface=normalized_surface,
            field_name=field_name,
            value=value,
            sources=field_sources.get(field_name),
        )
        penalty_total = min(
            sum(float(item.get("weight") or 0.0) for item in penalty_items),
            0.85,
        )
        score += weight * source_quality * (1.0 - penalty_total)
        source_tier_weights[tier_name] += weight
        penalties.extend(penalty_items)
    return (
        score,
        total_weight,
        present_fields,
        missing_fields,
        penalties,
        source_tier_weights,
    )


def _apply_requested_field_bonus(
    *,
    record: dict[str, Any],
    normalized_surface: str,
    requested_fields: list[str] | None,
    field_sources: dict[str, list[str]],
    alias_map: dict[str, list[str]],
    field_sources_by_key: dict[str, str],
    score: float,
    total_weight: float,
    missing_fields: list[str],
) -> tuple[float, float, list[str], int, list[str], list[str]]:
    raw_requested = [
        " ".join(str(fn or "").split()).strip()
        for fn in requested_fields or []
        if " ".join(str(fn or "").split()).strip()
    ]
    requested = repair_target_fields_for_surface(normalized_surface, raw_requested)
    requested_match_keys = _requested_match_keys(
        requested=requested, raw_requested=raw_requested, alias_map=alias_map
    )
    requested_match_cache = {
        fn: _resolve_requested_field_match(
            record,
            field_name=fn,
            alias_map=alias_map,
            field_sources_by_key=field_sources_by_key,
        )
        for fn in dict.fromkeys((*requested_match_keys, *requested))
    }
    requested_matches = [
        match
        for fn in requested_match_keys
        if (match := requested_match_cache[fn]) is not None
    ]
    for fn in requested:
        if requested_match_cache[fn] is None and fn not in missing_fields:
            missing_fields.append(fn)
    requested_found_total = len(requested_matches)
    if requested:
        requested_bonus = sum(
            _field_source_quality(
                field_sources.get(actual_fn),
                fallback_source=record.get("_source"),
            )[0]
            / max(len(requested), 1)
            for _rk, actual_fn in requested_matches
        )
        score += 0.15 * requested_bonus
        total_weight += 0.15
    return (
        score,
        total_weight,
        missing_fields,
        requested_found_total,
        raw_requested,
        requested,
    )


def _assemble_confidence_result(
    *,
    score: float,
    total_weight: float,
    present_fields: list[str],
    missing_fields: list[str],
    penalties: list[dict[str, Any]],
    source_tier_weights: defaultdict[str, float],
    raw_requested: list[str],
    requested: list[str],
    requested_found_total: int,
) -> dict[str, Any]:
    normalized_score = round(max(0.0, min(score / total_weight, 1.0)), 4)
    return {
        "score": normalized_score,
        "level": _confidence_level(normalized_score),
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "requested_fields_total": len(raw_requested)
        if raw_requested
        else len(requested),
        "requested_fields_found_best": requested_found_total,
        "penalties": [
            {
                "field": str(item["field"]),
                "kind": str(item["kind"]),
                "weight": round(float(item["weight"]), 3),
            }
            for item in penalties
        ],
        "source_tier": _source_reasoning(source_tier_weights),
    }


def _requested_match_keys(
    *,
    requested: list[str],
    raw_requested: list[str],
    alias_map: dict[str, list[str]],
) -> list[str]:
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            alias_to_canonical.setdefault(normalized_canonical, normalized_canonical)
        for alias in aliases or []:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias:
                alias_to_canonical.setdefault(normalized_alias, normalized_canonical)
    ordered: list[str] = []
    seen: set[str] = set()
    for field_name in [*requested, *raw_requested]:
        normalized = normalize_field_key(field_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
        canonical_key = alias_to_canonical.get(normalized)
        if canonical_key and canonical_key not in seen:
            seen.add(canonical_key)
            ordered.append(canonical_key)
        for alias in alias_map.get(normalized) or []:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias and normalized_alias not in seen:
                seen.add(normalized_alias)
                ordered.append(normalized_alias)
    return ordered


def _resolve_requested_field_match(
    record: dict[str, Any],
    *,
    field_name: str,
    alias_map: dict[str, list[str]],
    field_sources_by_key: dict[str, str],
) -> tuple[str, str] | None:
    candidate_keys = [
        normalize_field_key(field_name),
        *[
            normalize_field_key(alias)
            for alias in alias_map.get(normalize_field_key(field_name)) or []
        ],
    ]
    seen: set[str] = set()
    for candidate_key in candidate_keys:
        if not candidate_key or candidate_key in seen:
            continue
        seen.add(candidate_key)
        if record.get(candidate_key) not in (None, "", [], {}):
            return (field_name, candidate_key)
        source_field_name = field_sources_by_key.get(candidate_key)
        if source_field_name and record.get(source_field_name) not in (
            None,
            "",
            [],
            {},
        ):
            return (field_name, source_field_name)
    return None


def _resolved_field_value(
    record: dict[str, Any],
    field_name: str,
    surface: str,
) -> Any:
    """Resolve a field without allowing aliases to hide an exact value."""
    normalized_field = normalize_field_key(field_name)
    exact = record.get(normalized_field)
    if exact not in (None, "", [], {}):
        return exact

    alias_map = get_surface_field_aliases(surface)
    for alias in alias_map.get(normalized_field) or []:
        alias_key = normalize_field_key(alias)
        if not alias_key or alias_key == normalized_field:
            continue
        value = record.get(alias_key)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalized_field_sources(record: dict[str, Any]) -> dict[str, list[str]]:
    raw = record.get("_field_sources")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for field_name, sources in raw.items():
        if not isinstance(sources, list):
            continue
        source_rows: list[str] = []
        for source in sources:
            normalized_source = str(source or "").strip()
            if normalized_source:
                source_rows.append(normalized_source)
        normalized[str(field_name)] = source_rows
    return normalized


_SOURCE_NAME_ALIASES = {
    "jsonld": "json_ld",
    "json-ld": "json_ld",
    "opengraph": "open_graph",
    "open-graph": "open_graph",
    "js_state": "script_state",
    "js-state": "script_state",
    "network_payload": "network",
    "dom_selector": "dom",
    "dom_sections": "dom",
    "css_recipe": "dom",
    "selector_rule": "dom",
}
_SOURCE_QUALITY_OVERRIDES = {
    "adapter": ("authoritative", 1.0),
    "llm": ("llm", 0.55),
    "url": ("text", 0.4),
}


def _normalized_source_name(source: Any) -> str:
    normalized = str(source or "").strip().lower()
    return _SOURCE_NAME_ALIASES.get(normalized, normalized)


def _field_source_quality_or_none(
    sources: list[str] | None,
    *,
    fallback_source: Any,
) -> tuple[float, str] | None:
    candidates = [
        _normalized_source_name(source)
        for source in sources or []
        if _normalized_source_name(source)
    ]
    fallback = _normalized_source_name(fallback_source)
    if fallback:
        candidates.append(fallback)
    scored = [
        _SOURCE_QUALITY_OVERRIDES.get(source) or SOURCE_TIERS.get(source)
        for source in candidates
    ]
    known = [item for item in scored if item is not None]
    if not known:
        return None
    tier, quality = max(known, key=lambda item: float(item[1]))
    return float(quality), str(tier)


def _field_source_quality(
    sources: list[str] | None,
    *,
    fallback_source: Any,
) -> tuple[float, str]:
    """Backward-compatible helper for older internal callers."""
    return _field_source_quality_or_none(
        sources,
        fallback_source=fallback_source,
    ) or (0.0, "unknown")


def _field_penalties(
    *,
    surface: str,
    field_name: str,
    value: Any,
    sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    penalties: list[dict[str, Any]] = []
    text = _text_value(value)
    lowered = text.lower()
    normalized_sources = {str(source or "").strip() for source in sources or []}

    if field_name == "title":
        if _GENERIC_TITLE_RE.match(text):
            penalties.append(
                {"field": field_name, "kind": "generic_title", "weight": 0.55}
            )
        elif "url_slug" in normalized_sources:
            penalties.append(
                {"field": field_name, "kind": "generic_title", "weight": 0.25}
            )
        elif len(text) < 4:
            penalties.append({"field": field_name, "kind": "too_short", "weight": 0.35})

    if field_name in {"description", "responsibilities", "qualifications"}:
        if len(text) < 40:
            penalties.append(
                {"field": field_name, "kind": "thin_content", "weight": 0.4}
            )

    if field_name in {"price", "salary"} and text and not _PRICEISH_RE.search(text):
        penalties.append(
            {"field": field_name, "kind": "non_numeric_value", "weight": 0.45}
        )

    if (
        field_name in {"image_url", "apply_url", "url"}
        and text
        and not _URLISH_RE.match(text)
    ):
        penalties.append({"field": field_name, "kind": "non_url_value", "weight": 0.45})

    if surface == "ecommerce_detail" and field_name == "availability":
        if lowered in {"maybe", "unknown", "n/a"}:
            penalties.append(
                {"field": field_name, "kind": "ambiguous_availability", "weight": 0.35}
            )

    if surface == "job_detail" and field_name == "posted_date":
        if text and len(text) < 8:
            penalties.append(
                {"field": field_name, "kind": "partial_date", "weight": 0.25}
            )

    return penalties


def _source_reasoning(source_tier_weights: dict[str, float]) -> dict[str, Any]:
    if not source_tier_weights:
        return {
            "dominant": "unknown",
            "coverage": {},
            "reason": "no field provenance was recorded",
        }
    total = sum(source_tier_weights.values()) or 1.0
    coverage = {
        tier: round(weight / total, 4)
        for tier, weight in sorted(
            source_tier_weights.items(),
            key=lambda item: (-item[1], item[0]),
        )
    }
    dominant = next(iter(coverage), "text")
    if dominant == "authoritative":
        reason = "coverage is primarily from adapter or network sources"
    elif dominant == "structured":
        reason = "coverage is primarily from JS state or structured metadata"
    elif dominant == "dom":
        reason = "coverage is primarily from DOM selectors and visible page structure"
    elif dominant == "llm":
        reason = "coverage depends on missing-field LLM enrichment"
    else:
        reason = "coverage depends mostly on raw DOM text heuristics"
    return {
        "dominant": dominant,
        "coverage": coverage,
        "reason": reason,
    }


def _text_value(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(
            str(item or "").strip() for item in value if str(item or "").strip()
        ).strip()
    if isinstance(value, dict):
        return " ".join(
            str(item or "").strip()
            for item in value.values()
            if str(item or "").strip()
        ).strip()
    return str(value or "").strip()


def _confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"
