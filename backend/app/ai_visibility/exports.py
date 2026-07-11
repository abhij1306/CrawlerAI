"""CSV and Markdown exports for a completed AI-visibility run.

The Markdown export leads with an explicit methodology block so the evidence can
be dropped into a client deck without over-claiming.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.models.ai_visibility import AiVisibilityExecution, AiVisibilityRun

_CSV_COLUMNS = [
    "run_id",
    "prompt_index",
    "prompt_text",
    "theme",
    "intent",
    "repetition",
    "randomized_position",
    "status",
    "search_used",
    "search_query_count",
    "search_queries",
    "prompt_class",
    "prompt_contains_brand",
    "prompt_contains_competitor",
    "brand_mentioned",
    "brand_injected_in_search",
    "owned_domain_cited",
    "owned_citation_count",
    "unintended_domain_cited",
    "citation_count",
    "citation_domains",
    "competitors_mentioned",
    "competitor_domains_cited",
    "fanout_features",
    "latency_ms",
    "error_code",
]


def _join(values: Any) -> str:
    if not values:
        return ""
    return json.dumps(values, ensure_ascii=False)


def run_to_csv(run: AiVisibilityRun, executions: list[AiVisibilityExecution]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for e in sorted(executions, key=lambda x: (x.prompt_index, x.repetition)):
        score = e.score or {}
        queries = [ev.get("query") for ev in (e.search_events or [])]
        citation_domains = [
            c.get("domain") for c in (e.citations or []) if c.get("domain")
        ]
        writer.writerow(
            {
                "run_id": run.id,
                "prompt_index": e.prompt_index,
                "prompt_text": e.prompt_text_snapshot,
                "theme": e.prompt_theme_snapshot,
                "intent": e.prompt_intent_snapshot,
                "repetition": e.repetition,
                "randomized_position": e.randomized_position,
                "status": e.status,
                "search_used": e.search_used,
                "search_query_count": score.get("search_query_count", 0),
                "search_queries": _join(queries),
                "prompt_class": score.get("prompt_class", ""),
                "prompt_contains_brand": score.get("prompt_contains_brand", False),
                "prompt_contains_competitor": score.get(
                    "prompt_contains_competitor", False
                ),
                "brand_mentioned": score.get("brand_mentioned", False),
                "brand_injected_in_search": score.get(
                    "brand_injected_in_search", False
                ),
                "owned_domain_cited": score.get("owned_domain_cited", False),
                "owned_citation_count": score.get("owned_citation_count", 0),
                "unintended_domain_cited": score.get("unintended_domain_cited", False),
                "citation_count": score.get("citation_count", 0),
                "citation_domains": _join(citation_domains),
                "competitors_mentioned": _join(score.get("competitors_mentioned")),
                "competitor_domains_cited": _join(
                    score.get("competitor_domains_cited")
                ),
                "fanout_features": _join(score.get("fanout_features")),
                "latency_ms": e.latency_ms,
                "error_code": e.error_code,
            }
        )
    return buffer.getvalue()


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _usd(value: Any) -> str:
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return "—"


def run_to_markdown(
    run: AiVisibilityRun, executions: list[AiVisibilityExecution]
) -> str:
    config = run.configuration or {}
    summary = run.summary or {}
    brand = config.get("brand_name", "Brand")
    lines: list[str] = []

    lines.append(f"# AI Search Visibility Benchmark — {brand}")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    provider_labels = {
        "gemini": "Google Gemini grounded API direct",
        "openrouter_openai": "OpenAI grounded API via OpenRouter",
        "openrouter_anthropic": "Anthropic grounded API via OpenRouter",
    }
    lines.append(
        f"- **Provider / model:** {provider_labels.get(run.provider, run.provider)} "
        f"— `{run.model}`"
    )
    if run.provider == "gemini":
        surface = (
            "Gemini API with Google Search grounding. This is NOT the Gemini "
            "consumer app and NOT Google AI Overviews."
        )
    else:
        surface = (
            "OpenRouter API with the provider-native web-search engine requested. "
            "This is NOT the ChatGPT or Claude consumer application."
        )
    lines.append(f"- **Surface:** {surface} It is a reproducible API surface.")
    if run.provider == "gemini":
        statelessness = "`store=false`, no previous interaction"
    else:
        statelessness = "fresh one-turn request with no prior messages"
    lines.append(
        "- **Statelessness:** every prompt is a fresh, independent request "
        f"({statelessness}). No account history or chat context influences any answer."
    )
    mode = str(config.get("benchmark_mode") or "forced_grounded")
    mode_text = {
        "consumer_like": "exact visible prompt; no system instruction",
        "controlled_localized": "visible prompt plus disclosed market/language context",
        "forced_grounded": "disclosed market/language context plus forced current-web citations",
    }.get(mode, mode)
    lines.append(f"- **Benchmark mode:** `{mode}` — {mode_text}.")
    if mode != "consumer_like":
        lines.append(
            "- **Localization:** benchmark context supplied country "
            f"`{config.get('country_code', '')}` and language "
            f"`{config.get('language_code', '')}` to the model; it was not inferred "
            "from device or account location."
        )
    classes = summary.get("prompt_class_counts", {})
    class_names = [name for name, count in classes.items() if count]
    if not class_names:
        panel_label = "Prompt classification unavailable until executions complete."
    elif set(class_names) == {"non_branded"}:
        panel_label = "All prompts are unaided/non-branded."
    else:
        panel_label = (
            "Mixed panel: "
            + ", ".join(
                f"{name}={count}" for name, count in sorted(classes.items()) if count
            )
            + "."
        )
    lines.append(
        f"- **Prompt panel:** {panel_label} Brand and competitor data is applied "
        "only during scoring."
    )
    lines.append(
        f"- **Panel fingerprint:** `{config.get('panel_id', 'unavailable')}`; prompt "
        "text hashes are frozen in the run configuration."
    )
    lines.append(
        f"- **Design:** {run.requested_count} executions "
        f"({run.repetitions} repetition(s) per prompt), execution order "
        f"randomized (seed `{run.random_seed}`)."
    )
    lines.append(
        "- **Citations:** only explicit source citations returned by the API are "
        "counted. Publisher domains prefer resolved/direct URLs and use the citation "
        "title only as fallback; this is not "
        "a complete ledger of every page the model read."
    )
    if run.provider != "gemini":
        lines.append(
            "- **Search fanout:** OpenRouter exposes native web-search request count "
            "but does not guarantee provider-generated query strings; query-text "
            "fanout metrics are unavailable for this surface."
        )
    lines.append(
        f"- **Result:** {summary.get('total_completed', 0)} completed, "
        f"{run.failed_count} failed."
    )
    lines.append("")

    lines.append("## Headline Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Brand mention rate | {_pct(summary.get('brand_mention_rate'))} |")
    lines.append(
        f"| Owned-domain citation rate | {_pct(summary.get('owned_citation_rate'))} |"
    )
    lines.append(
        "| Mention → owned-citation conversion | "
        f"{_pct(summary.get('mention_to_owned_citation_conversion'))} |"
    )
    lines.append(f"| Search-use rate | {_pct(summary.get('search_use_rate'))} |")
    lines.append(
        f"| Avg. search queries / answer | {summary.get('avg_queries_per_execution', 0)} |"
    )
    lines.append(
        "| Brand injected into search fanout | "
        f"{_pct(summary.get('brand_fanout_injection_rate'))} |"
    )
    lines.append(
        "| Unintended-domain citation rate | "
        f"{_pct(summary.get('unintended_domain_citation_rate'))} |"
    )
    cost = summary.get("cost") or {}
    lines.append(
        "| Paid-list token cost estimate | "
        f"{_usd(cost.get('paid_list_token_estimate_usd'))} |"
    )
    lines.append(
        "| Grounding cost if outside free allowance | "
        f"{_usd(cost.get('grounding_cost_if_billable_usd'))} |"
    )
    if float(cost.get("provider_reported_cost_usd") or 0) > 0:
        lines.append(
            "| Provider-reported cost | "
            f"{_usd(cost.get('provider_reported_cost_usd'))} |"
        )
    lines.append(f"| Grounded requests | {cost.get('grounded_requests', 0)} |")
    lines.append("")

    competitors = [c.get("name") for c in (config.get("competitors") or [])]
    if competitors:
        lines.append("## Competitor Comparison")
        lines.append("")
        lines.append("| Competitor | Mention rate | Citation rate |")
        lines.append("|---|---|---|")
        mention = summary.get("competitor_mention_rate", {})
        citation = summary.get("competitor_citation_rate", {})
        lines.append(
            f"| **{brand}** | {_pct(summary.get('brand_mention_rate'))} | "
            f"{_pct(summary.get('owned_citation_rate'))} |"
        )
        for name in competitors:
            lines.append(
                f"| {name} | {_pct(mention.get(name))} | {_pct(citation.get(name))} |"
            )
        lines.append("")

    lines.append("## Per-Prompt Results (with immediate binary consistency)")
    lines.append("")
    lines.append(
        "| # | Prompt | Theme | Brand mentioned | Owned cited | Immediate consistency |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in summary.get("per_prompt", []):
        reps = row.get("repetitions", 0)
        lines.append(
            f"| {row.get('prompt_index')} | {row.get('prompt_text')} | "
            f"{row.get('theme')} | {row.get('brand_mentioned_count')}/{reps} | "
            f"{row.get('owned_cited_count')}/{reps} | "
            f"{_pct(row.get('mention_stability'))} |"
        )
    lines.append("")

    share = summary.get("citation_annotation_share_by_domain", {})
    if share:
        lines.append("## Top Domains by Inline Citation-Annotation Share")
        lines.append("")
        lines.append("| Domain | Share of citations |")
        lines.append("|---|---|")
        for domain, value in share.items():
            lines.append(f"| {domain} | {_pct(value)} |")
        lines.append("")

    failures = [e for e in executions if e.status == "failed"]
    if failures:
        lines.append("## Failed Executions")
        lines.append("")
        lines.append("| Prompt | Repetition | Error |")
        lines.append("|---|---|---|")
        for e in failures:
            lines.append(
                f"| {e.prompt_text_snapshot} | {e.repetition} | {e.error_code} |"
            )
        lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- A single grounded API surface is not a proxy for all "
        "AI answer engines; provider APIs and consumer applications retrieve and "
        "route differently."
    )
    lines.append(
        "- Grounded answers vary by date, index freshness and location; results "
        "are a point-in-time snapshot. Immediate repetitions measure short-term "
        "binary consistency, not statistical confidence or day-to-day volatility."
    )
    lines.append(
        "- Only explicit citations are scored; a mention without a citation is "
        "recorded as a mention, not a source."
    )
    lines.append("")

    return "\n".join(lines)
