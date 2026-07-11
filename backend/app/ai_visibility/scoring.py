"""Deterministic mention/citation/domain/fanout scoring.

No LLM is used for headline metrics. Matching is alias-based and transparent so
every classification in the UI/exports is explainable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import urlparse

from app.ai_visibility.normalization import (
    alias_present,
    domain_matches,
    first_alias_offset,
    normalize_alias,
    normalize_domain,
)
from app.core.config.ai_visibility import AI_VISIBILITY_AMBIGUOUS_ALIASES
from app.core.config.ai_visibility import (
    AI_VISIBILITY_GEMINI_25_FLASH_INPUT_PER_MILLION_USD,
    AI_VISIBILITY_GEMINI_25_FLASH_OUTPUT_PER_MILLION_USD,
    AI_VISIBILITY_GEMINI_25_GROUNDED_PROMPT_USD,
)

# Transparent keyword rules for search-query fanout classification (proposal
# §13.3). Each entry: feature -> tuple of substrings (matched on the normalized,
# lowercased query).
FANOUT_FEATURE_RULES: dict[str, tuple[str, ...]] = {
    "community": ("reddit", "forum", "discussion", "experiences"),
    "review": ("review", "reviews", "rating", "ratings", "customer feedback"),
    "comparison": (
        "vs",
        "versus",
        "alternative",
        "alternatives",
        "compare",
        "best",
    ),
    "commercial": (
        "price",
        "prices",
        "cheap",
        "affordable",
        "budget",
        "sale",
        "under",
    ),
    "local": (
        "near me",
        "nearby",
        "store",
        "sydney",
        "melbourne",
        "brisbane",
        "perth",
    ),
    "service": ("click and collect", "delivery", "returns", "shipping"),
    "freshness": ("latest", "current", "today", "2026"),
    "product_evidence": (
        "material",
        "fabric",
        "size",
        "multipack",
        "availability",
        "stock",
    ),
}


@dataclass(frozen=True)
class CompetitorConfig:
    name: str
    aliases: tuple[str, ...]
    domains: tuple[str, ...]


@dataclass(frozen=True)
class ScoringConfig:
    brand_name: str
    brand_aliases: tuple[str, ...]
    owned_domains: tuple[str, ...]
    unintended_domains: tuple[str, ...]
    country_code: str = ""
    language_code: str = ""
    benchmark_mode: str = ""
    provider: str = ""
    model: str = ""
    competitors: tuple[CompetitorConfig, ...] = field(default_factory=tuple)

    @classmethod
    def from_project(cls, config: dict[str, Any]) -> "ScoringConfig":
        brand_name = str(config.get("brand_name") or "")
        aliases = [brand_name, *(config.get("brand_aliases") or [])]
        competitors = tuple(
            CompetitorConfig(
                name=str(item.get("name") or ""),
                aliases=tuple(
                    str(a)
                    for a in ([item.get("name"), *(item.get("aliases") or [])])
                    if a
                ),
                domains=tuple(str(d) for d in (item.get("domains") or []) if d),
            )
            for item in (config.get("competitors") or [])
        )
        return cls(
            brand_name=brand_name,
            brand_aliases=tuple(a for a in aliases if a),
            owned_domains=tuple(config.get("owned_domains") or []),
            unintended_domains=tuple(config.get("unintended_domains") or []),
            country_code=str(config.get("country_code") or ""),
            language_code=str(config.get("language_code") or ""),
            benchmark_mode=str(config.get("benchmark_mode") or ""),
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            competitors=competitors,
        )


def classify_fanout(query: str) -> list[str]:
    normalized = str(query or "").lower()
    features: list[str] = []
    for feature, needles in FANOUT_FEATURE_RULES.items():
        for needle in needles:
            # Multi-word needles are substring-matched; single tokens use word
            # boundaries via surrounding spaces on a padded haystack.
            if " " in needle:
                if needle in normalized:
                    features.append(feature)
                    break
            elif f" {needle} " in f" {normalized} ":
                features.append(feature)
                break
    return features


def _any_alias_present(aliases: tuple[str, ...], normalized_haystack: str) -> bool:
    return any(
        alias_present(normalize_alias(alias), normalized_haystack) for alias in aliases
    )


def _entity_alias_present(
    aliases: tuple[str, ...], text: str, normalized_haystack: str
) -> bool:
    for alias in aliases:
        normalized_alias = normalize_alias(alias)
        if normalized_alias not in AI_VISIBILITY_AMBIGUOUS_ALIASES:
            if alias_present(normalized_alias, normalized_haystack):
                return True
            continue
        if re.search(rf"\b{re.escape(alias)}\s+Australia\b", text, re.IGNORECASE):
            return True
        # A retailer-style proper noun is accepted, except common semantic uses.
        if re.search(
            rf"\b{re.escape(alias)}\b(?!\s+(?:audience|price|market|demographic))",
            text,
        ):
            return True
    return False


def _first_offset(aliases: tuple[str, ...], normalized_haystack: str) -> int | None:
    offsets = [
        offset
        for alias in aliases
        if (offset := first_alias_offset(normalize_alias(alias), normalized_haystack))
        is not None
    ]
    return min(offsets) if offsets else None


def _domain_in(domain: str, targets: tuple[str, ...]) -> bool:
    return any(domain_matches(domain, target) for target in targets)


def _url_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return normalize_domain(urlparse(raw).hostname or "")
    except ValueError:
        return ""


def _is_google_redirect(value: Any) -> bool:
    raw = str(value or "").lower()
    return "grounding-api-redirect" in raw or "vertexaisearch.cloud.google.com" in raw


def citation_domain(citation: dict[str, Any]) -> str:
    """Resolve publisher identity using strongest available URL evidence."""
    resolved = _url_domain(citation.get("resolved_url"))
    if resolved:
        return resolved
    annotation_url = citation.get("redirect_url") or citation.get("url")
    direct = _url_domain(annotation_url)
    if direct and not _is_google_redirect(annotation_url):
        return direct
    return normalize_domain(citation.get("domain") or citation.get("title"))


def classify_citation(
    citation: dict[str, Any], config: ScoringConfig
) -> dict[str, Any]:
    """Annotate a raw citation dict with ownership/competitor classification."""
    domain = citation_domain(citation)
    matched_competitor = None
    for competitor in config.competitors:
        if _domain_in(domain, competitor.domains):
            matched_competitor = competitor.name
            break
    return {
        **citation,
        "domain": domain,
        "is_owned": _domain_in(domain, config.owned_domains),
        "is_unintended": _domain_in(domain, config.unintended_domains),
        "matched_competitor": matched_competitor,
    }


def score_execution(
    *,
    answer_text: str,
    search_events: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    search_used: bool,
    config: ScoringConfig,
    prompt_text: str = "",
    query_text_available: bool = True,
) -> dict[str, Any]:
    """Per-execution deterministic score (proposal §13.2)."""
    normalized_answer = normalize_alias(answer_text)

    # Brand in answer
    brand_mentioned = _entity_alias_present(
        config.brand_aliases, answer_text, normalized_answer
    )
    brand_first_offset = _first_offset(config.brand_aliases, normalized_answer)

    # Brand / competitor injection into generated search queries
    query_text = " ".join(str(event.get("query") or "") for event in search_events)
    query_blob = normalize_alias(query_text)
    normalized_prompt = normalize_alias(prompt_text)
    prompt_contains_brand = _entity_alias_present(
        config.brand_aliases, prompt_text, normalized_prompt
    )
    prompt_competitors = [
        competitor.name
        for competitor in config.competitors
        if _entity_alias_present(competitor.aliases, prompt_text, normalized_prompt)
    ]
    if prompt_contains_brand and prompt_competitors:
        prompt_class = "comparison_branded"
    elif prompt_contains_brand:
        prompt_class = "branded"
    elif prompt_competitors:
        prompt_class = "mixed"
    else:
        prompt_class = "non_branded"

    brand_injected = (
        (
            not prompt_contains_brand
            and _entity_alias_present(config.brand_aliases, query_text, query_blob)
        )
        if query_text_available
        else None
    )

    competitors_mentioned: list[str] = []
    competitors_injected: list[str] = []
    for competitor in config.competitors:
        if _entity_alias_present(competitor.aliases, answer_text, normalized_answer):
            competitors_mentioned.append(competitor.name)
        if query_text_available and (
            competitor.name not in prompt_competitors
            and _entity_alias_present(competitor.aliases, query_text, query_blob)
        ):
            competitors_injected.append(competitor.name)

    # Citations
    classified = [classify_citation(c, config) for c in citations]
    owned_count = sum(1 for c in classified if c["is_owned"])
    unintended_cited = any(c["is_unintended"] for c in classified)
    competitor_domains_cited = sorted(
        {c["matched_competitor"] for c in classified if c["matched_competitor"]}
    )

    # Fanout features across all queries
    fanout_features = sorted(
        {
            feature
            for event in search_events
            for feature in classify_fanout(str(event.get("query") or ""))
        }
    )

    return {
        "search_used": bool(search_used),
        "search_query_count": len(search_events),
        "search_query_text_available": query_text_available,
        "brand_mentioned": brand_mentioned,
        "brand_first_offset": brand_first_offset,
        "brand_injected_in_search": brand_injected,
        "prompt_contains_brand": prompt_contains_brand,
        "prompt_contains_competitor": bool(prompt_competitors),
        "prompt_competitors": prompt_competitors,
        "prompt_class": prompt_class,
        "owned_domain_cited": owned_count > 0,
        "owned_citation_count": owned_count,
        "unintended_domain_cited": unintended_cited,
        "citation_count": len(classified),
        "competitors_mentioned": competitors_mentioned,
        "competitors_injected_in_search": competitors_injected,
        "competitor_domains_cited": competitor_domains_cited,
        "fanout_features": fanout_features,
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def aggregate_run(
    executions: list[dict[str, Any]], config: ScoringConfig
) -> dict[str, Any]:
    """Run-level aggregates (proposal §13.4 + §13.5 stability)."""
    completed = [
        e for e in executions if (e.get("score") and e.get("status") == "completed")
    ]
    total = len(completed)
    scores = [e["score"] for e in completed]

    mention = sum(1 for s in scores if s.get("brand_mentioned"))
    owned = sum(1 for s in scores if s.get("owned_domain_cited"))
    mention_and_owned = sum(
        1 for s in scores if s.get("brand_mentioned") and s.get("owned_domain_cited")
    )
    search_used = sum(1 for s in scores if s.get("search_used"))
    non_branded_scores = [s for s in scores if s.get("prompt_class") == "non_branded"]
    query_text_scores = [
        s for s in non_branded_scores if s.get("search_query_text_available", True)
    ]
    all_query_text_scores = [
        s for s in scores if s.get("search_query_text_available", True)
    ]
    brand_injected = sum(
        1 for s in query_text_scores if s.get("brand_injected_in_search")
    )
    competitor_injected = sum(
        1 for s in scores if s.get("competitors_injected_in_search")
    )
    unintended = sum(1 for s in scores if s.get("unintended_domain_cited"))
    total_queries = sum(int(s.get("search_query_count") or 0) for s in scores)

    # Citation metrics use separate denominators. Annotation share counts inline
    # annotations; execution rate counts answers; URL share deduplicates URLs.
    domain_counter: Counter[str] = Counter()
    domain_executions: Counter[str] = Counter()
    domain_prompts: dict[str, set[int]] = {}
    unique_urls_by_domain: dict[str, set[str]] = {}
    for e in completed:
        execution_domains: set[str] = set()
        for citation in e.get("citations") or []:
            domain = citation_domain(citation)
            if domain:
                domain_counter[domain] += 1
                execution_domains.add(domain)
                domain_prompts.setdefault(domain, set()).add(
                    int(e.get("prompt_index", 0))
                )
                url = str(
                    citation.get("resolved_url")
                    or citation.get("redirect_url")
                    or citation.get("url")
                    or ""
                )
                if url:
                    unique_urls_by_domain.setdefault(domain, set()).add(url)
        domain_executions.update(execution_domains)
    total_citations = sum(domain_counter.values())
    top_domains = domain_counter.most_common(25)
    citation_share = {
        domain: _rate(count, total_citations) for domain, count in top_domains
    }
    shown = sum(count for _, count in top_domains)
    if total_citations > shown:
        citation_share["Other"] = _rate(total_citations - shown, total_citations)
    unique_url_total = (
        len(set().union(*unique_urls_by_domain.values()))
        if unique_urls_by_domain
        else 0
    )
    distinct_prompt_count = len({int(e.get("prompt_index", 0)) for e in completed})
    domain_execution_rate = {
        domain: _rate(domain_executions[domain], total) for domain, _ in top_domains
    }
    domain_unique_url_share = {
        domain: _rate(len(unique_urls_by_domain.get(domain, set())), unique_url_total)
        for domain, _ in top_domains
    }
    domain_prompt_coverage = {
        domain: _rate(len(domain_prompts.get(domain, set())), distinct_prompt_count)
        for domain, _ in top_domains
    }

    # Competitor mention/citation rates
    competitor_names = [c.name for c in config.competitors]
    competitor_mention_rate = {
        name: _rate(
            sum(1 for s in scores if name in (s.get("competitors_mentioned") or [])),
            total,
        )
        for name in competitor_names
    }
    competitor_citation_rate = {
        name: _rate(
            sum(1 for s in scores if name in (s.get("competitor_domains_cited") or [])),
            total,
        )
        for name in competitor_names
    }

    # Per-prompt repetition stability (§13.5)
    per_prompt = _per_prompt_stability(completed)

    # Token usage across completed executions (from the provider ``usage`` block,
    # already snapshotted into provider_metadata). Purely observational.
    token_usage = _aggregate_token_usage(completed)
    cost = _aggregate_cost(completed, token_usage, config)

    return {
        "total_completed": total,
        "brand_mention_rate": _rate(mention, total),
        "owned_citation_rate": _rate(owned, total),
        "mention_to_owned_citation_conversion": _rate(mention_and_owned, mention),
        "brand_fanout_injection_rate": (
            _rate(brand_injected, len(query_text_scores)) if query_text_scores else None
        ),
        "search_query_text_coverage_rate": _rate(
            sum(1 for s in scores if s.get("search_query_text_available", True)), total
        ),
        "competitor_fanout_injection_rate": (
            _rate(competitor_injected, len(all_query_text_scores))
            if all_query_text_scores
            else None
        ),
        "search_use_rate": _rate(search_used, total),
        "avg_queries_per_execution": (
            round(total_queries / total, 2) if total else 0.0
        ),
        "unintended_domain_citation_rate": _rate(unintended, total),
        "citation_share_by_domain": citation_share,
        "citation_annotation_share_by_domain": citation_share,
        "domain_execution_citation_rate": domain_execution_rate,
        "domain_unique_url_share": domain_unique_url_share,
        "domain_prompt_coverage": domain_prompt_coverage,
        "prompt_class_counts": dict(
            Counter(s.get("prompt_class", "unknown") for s in scores)
        ),
        "competitor_mention_rate": competitor_mention_rate,
        "competitor_citation_rate": competitor_citation_rate,
        "per_prompt": per_prompt,
        "token_usage": token_usage,
        "cost": cost,
    }


def _aggregate_cost(
    completed: list[dict[str, Any]],
    token_usage: dict[str, int],
    config: ScoringConfig,
) -> dict[str, Any]:
    grounded_requests = sum(
        1 for execution in completed if execution["score"].get("search_used")
    )
    provider_reported = 0.0
    for execution in completed:
        usage = (execution.get("provider_metadata") or {}).get("usage") or {}
        provider_reported += float(usage.get("provider_cost_usd") or 0)

    token_estimate = 0.0
    grounding_if_billable = 0.0
    # ``gemini-flash-latest`` is an alias that currently resolves to the 2.5-flash
    # generation, so it shares the same public paid-list pricing.
    if config.provider == "gemini" and config.model in (
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ):
        token_estimate = (
            token_usage["input_tokens"]
            * AI_VISIBILITY_GEMINI_25_FLASH_INPUT_PER_MILLION_USD
            / 1_000_000
            + token_usage["output_tokens"]
            * AI_VISIBILITY_GEMINI_25_FLASH_OUTPUT_PER_MILLION_USD
            / 1_000_000
        )
        grounding_if_billable = (
            grounded_requests * AI_VISIBILITY_GEMINI_25_GROUNDED_PROMPT_USD
        )
    return {
        "currency": "USD",
        "grounded_requests": grounded_requests,
        "paid_list_token_estimate_usd": round(token_estimate, 6),
        "grounding_cost_if_billable_usd": round(grounding_if_billable, 6),
        "provider_reported_cost_usd": round(provider_reported, 6),
        "free_allowance_applied": False,
        "note": (
            "Estimates use public paid-list prices. Actual cost may be zero or lower "
            "within provider free allowances."
        ),
    }


def _aggregate_token_usage(completed: list[dict[str, Any]]) -> dict[str, int]:
    """Sum provider token counts across completed executions.

    Reads the Gemini ``usage`` block snapshotted into ``provider_metadata``. All
    keys default to 0 so a run with no usage data still reports a stable shape.
    """
    input_tokens = output_tokens = total_tokens = 0
    for e in completed:
        usage = (e.get("provider_metadata") or {}).get("usage") or {}
        input_tokens += int(usage.get("total_input_tokens") or 0)
        output_tokens += int(usage.get("total_output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _per_prompt_stability(completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for e in completed:
        grouped.setdefault(int(e.get("prompt_index", 0)), []).append(e)

    rows: list[dict[str, Any]] = []
    for prompt_index in sorted(grouped):
        group = grouped[prompt_index]
        reps = len(group)
        mention_true = sum(1 for e in group if e["score"].get("brand_mentioned"))
        owned_true = sum(1 for e in group if e["score"].get("owned_domain_cited"))
        rows.append(
            {
                "prompt_index": prompt_index,
                "prompt_text": group[0].get("prompt_text_snapshot", ""),
                "theme": group[0].get("prompt_theme_snapshot", ""),
                "repetitions": reps,
                "brand_mentioned_count": mention_true,
                "owned_cited_count": owned_true,
                "mention_stability": _stability(mention_true, reps),
                "owned_stability": _stability(owned_true, reps),
            }
        )
    return rows


def _stability(true_count: int, reps: int) -> float:
    if reps <= 0:
        return 0.0
    false_count = reps - true_count
    return round(max(true_count, false_count) / reps, 4)
