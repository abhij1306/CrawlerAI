from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition.policy import AcquisitionPolicy
from app.services.acquisition_plan import AcquisitionPlan
from app.services.config.design_system import (
    DESIGN_SYSTEM_COLOR_ROLE_HINTS,
    DESIGN_SYSTEM_DEFAULT_SAMPLE_URLS,
    DESIGN_SYSTEM_EXPORT_FILENAME,
    DESIGN_SYSTEM_INTERNAL_VARIABLE_PREFIXES,
    DESIGN_SYSTEM_LLM_SYSTEM_PROMPT,
    DESIGN_SYSTEM_MARKDOWN_TASK,
    DESIGN_SYSTEM_RECORD_TYPE,
    DESIGN_SYSTEM_ROUNDED_TOKEN_NAMES,
    DESIGN_SYSTEM_SITEMAP_SCAN_MULTIPLIER,
    DESIGN_SYSTEM_SOURCE,
    DESIGN_SYSTEM_SPACING_TOKEN_NAMES,
    DESIGN_SYSTEM_SURFACE,
)
from app.services.crawl.events import append_log_event
from app.services.crawl.sitemap_resolver import resolve_category_urls_from_sitemap
from app.services.crawl.state import CrawlStatus, update_run_status
from app.services.crawl.utils import normalize_target_url
from app.services.domain_utils import normalize_domain
from app.services.llm.runtime import run_prompt_task
from app.services.pipeline.runtime_helpers import STAGE_ACQUIRE, STAGE_EXTRACT, STAGE_PERSIST, set_stage
from app.services.publish import VERDICT_EMPTY, VERDICT_SUCCESS, build_url_metrics
from app.services.robots_policy import check_url_crawlability

logger = logging.getLogger(__name__)


async def process_design_system_run(session: AsyncSession, run: CrawlRun) -> None:
    if str(run.surface or "").strip().lower() != DESIGN_SYSTEM_SURFACE:
        raise ValueError("process_design_system_run requires design_system surface")
    update_run_status(run, CrawlStatus.RUNNING)
    await set_stage(session, run, STAGE_ACQUIRE, current_url=run.url)
    await session.commit()

    sample_urls = await sample_design_system_urls(run.url)
    run.update_summary(url_count=len(sample_urls), resolved_url_list=sample_urls)
    await append_log_event(
        run.id,
        "info",
        f"Design crawl sampling {len(sample_urls)} URL(s)",
        session=session,
    )
    await session.commit()

    snapshots: list[dict[str, Any]] = []
    url_metrics: list[dict[str, object]] = []
    for index, url in enumerate(sample_urls, start=1):
        await set_stage(
            session,
            run,
            STAGE_ACQUIRE,
            current_url=url,
            current_url_index=index,
            total_urls=len(sample_urls),
        )
        await session.commit()
        if run.settings_view.respect_robots_txt():
            robots = await check_url_crawlability(url)
            if not robots.allowed:
                await append_log_event(
                    run.id,
                    "warning",
                    f"[ROBOTS] Blocked by robots.txt: {url}",
                    session=session,
                )
                continue
        try:
            acquisition = await acquire(_build_design_acquisition_request(run, url))
        except Exception as exc:
            logger.warning("Design crawl acquisition failed for run=%s url=%s", run.id, url, exc_info=True)
            await append_log_event(
                run.id,
                "warning",
                f"Design acquisition failed for {url}: {type(exc).__name__}: {exc}",
                session=session,
            )
            continue
        url_metrics.append(build_url_metrics(acquisition, requested_fields=list(run.requested_fields or [])))
        snapshot = _snapshot_from_acquisition(acquisition)
        if snapshot:
            snapshots.append(snapshot)

    await set_stage(session, run, STAGE_EXTRACT, current_url=run.url)
    await session.commit()
    tokens = build_design_tokens(snapshots)
    deterministic_markdown = build_design_markdown(
        tokens=tokens,
        source_urls=sample_urls,
        llm_sections=None,
    )
    markdown, llm_status = await _shape_design_markdown(
        session,
        run=run,
        tokens=tokens,
        source_urls=sample_urls,
        deterministic_markdown=deterministic_markdown,
    )
    await append_log_event(
        run.id,
        "info",
        f"Design deterministic extraction complete; LLM shaping {llm_status}",
        session=session,
    )

    await set_stage(session, run, STAGE_PERSIST, current_url=run.url)
    await _replace_design_record(
        session,
        run=run,
        markdown=markdown,
        tokens=tokens,
        source_urls=sample_urls,
        llm_status=llm_status,
    )
    verdict = VERDICT_SUCCESS if snapshots else VERDICT_EMPTY
    update_run_status(run, CrawlStatus.COMPLETED)
    run.update_summary(
        record_count=1,
        progress=100,
        completed_urls=len(sample_urls),
        processed_urls=len(sample_urls),
        current_stage=STAGE_PERSIST,
        extraction_verdict=verdict,
        url_metrics=url_metrics,
        design_system={
            "sampled_urls": len(sample_urls),
            "snapshots": len(snapshots),
            "llm_status": llm_status,
            "filename": DESIGN_SYSTEM_EXPORT_FILENAME,
        },
    )
    await append_log_event(
        run.id,
        "info",
        f"Design crawl complete. output={DESIGN_SYSTEM_EXPORT_FILENAME}",
        session=session,
    )
    await session.commit()


async def sample_design_system_urls(url: str) -> list[str]:
    primary = normalize_target_url(url)
    if not primary:
        return []
    limit = _sample_limit()
    domain = normalize_domain(primary)
    urls = [primary]
    try:
        sitemap_urls = await resolve_category_urls_from_sitemap(
            _origin(primary),
            filter_keyword="",
            max_urls=limit * DESIGN_SYSTEM_SITEMAP_SCAN_MULTIPLIER,
        )
    except Exception:
        sitemap_urls = []
    for candidate in sitemap_urls:
        normalized = normalize_target_url(candidate)
        if not normalized or normalize_domain(normalized) != domain or normalized in urls:
            continue
        urls.append(normalized)
        if len(urls) >= limit:
            break
    return urls


def build_design_tokens(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    css_variables: dict[str, str] = {}
    components: dict[str, Counter[str]] = defaultdict(Counter)
    titles: list[str] = []
    for snapshot in snapshots:
        title = _text(snapshot.get("title"))
        if title:
            titles.append(title)
        for name, value in dict(snapshot.get("css_variables") or {}).items():
            text = _text(value)
            var_name = str(name)
            if text and _is_design_css_variable(var_name, text):
                css_variables[var_name] = text
        values = dict(snapshot.get("values") or {})
        for key in ("colors", "fonts", "fontSizes", "fontWeights", "lineHeights", "spacing", "radius", "shadows"):
            for value in _list(values.get(key)):
                text = _normalize_observed_value(key, value)
                if text:
                    counters[key][text] += 1
        for component in _list(snapshot.get("components")):
            if not isinstance(component, dict):
                continue
            kind = _text(component.get("kind"))
            if not kind:
                continue
            signature = json.dumps(
                {
                    "font_size": _text(component.get("font_size")),
                    "font_weight": _text(component.get("font_weight")),
                    "color": _text(component.get("color")),
                    "background": _text(component.get("background")),
                    "radius": _text(component.get("radius")),
                    "padding": _text(component.get("padding")),
                    "shadow": _text(component.get("shadow")),
                },
                sort_keys=True,
            )
            components[kind][signature] += 1
    color_tokens = _color_tokens(css_variables, counters["colors"])
    typography_tokens = _typography_tokens(counters)
    spacing_tokens = _scale_tokens(counters["spacing"], DESIGN_SYSTEM_SPACING_TOKEN_NAMES)
    rounded_tokens = _rounded_tokens(counters["radius"])
    component_tokens = _component_tokens(components, color_tokens, typography_tokens, rounded_tokens)
    return {
        "page_titles": titles[:5],
        "css_variables": _resolved_css_variables(css_variables),
        "frontmatter": {
            "version": "alpha",
            "colors": color_tokens,
            "typography": typography_tokens,
            "spacing": spacing_tokens,
            "rounded": rounded_tokens,
            "components": component_tokens,
        },
        "colors": _top(counters["colors"], 16),
        "typography": {
            "fonts": _top(counters["fonts"], 8),
            "font_sizes": _top(counters["fontSizes"], 12),
            "font_weights": _top(counters["fontWeights"], 8),
            "line_heights": _top(counters["lineHeights"], 8),
        },
        "spacing": _top(counters["spacing"], 16),
        "radii": _top(counters["radius"], 12),
        "shadows": _top(counters["shadows"], 10),
        "components": {
            kind: [_component_payload(signature, count) for signature, count in counter.most_common(6)]
            for kind, counter in sorted(components.items())
        },
    }


def build_design_markdown(
    *,
    tokens: dict[str, Any],
    source_urls: list[str],
    llm_sections: dict[str, Any] | None,
) -> str:
    sections = _clean_llm_sections(dict(llm_sections or {}), tokens)
    frontmatter = dict(tokens.get("frontmatter") or {})
    yaml = _frontmatter_yaml(
        name=_text(sections.get("name")) or _design_name(source_urls),
        description=_text(sections.get("description")) or "Generated from rendered website evidence. Token values are deterministic observations.",
        frontmatter=frontmatter,
    )
    lines = [
        "---",
        *yaml,
        "---",
        "",
        "# DESIGN.md",
        "",
        "## Overview",
        "",
        _text(sections.get("overview"))
        or "This file captures the observed website design system as deterministic tokens plus short application guidance. Treat YAML tokens as the source of truth; prose explains how to use them.",
        "",
        "## Sources",
        "",
        *[f"- {url}" for url in source_urls],
        "",
        "## Colors",
        "",
        *_color_token_rows(frontmatter.get("colors")),
        "",
        "## Typography",
        "",
        *_typography_token_rows(frontmatter.get("typography")),
        "",
        "## Layout",
        "",
        *_scale_rows("Spacing", frontmatter.get("spacing")),
        "",
        "## Elevation & Depth",
        "",
        *_elevation_rows(tokens.get("shadows")),
        "",
        "## Shapes",
        "",
        *_scale_rows("Rounded", frontmatter.get("rounded")),
        "",
        "## Components",
        "",
        *_component_rows(dict(frontmatter.get("components") or {})),
        "",
        "## Do's and Don'ts",
    ]
    notes = [str(item).strip() for item in _list(sections.get("usage_notes")) if str(item).strip()]
    if notes:
        lines.extend(["", *[f"- {note}" for note in notes]])
    else:
        lines.extend(
            [
                "",
                "- Do use the YAML token names when recreating UI elements.",
                "- Do validate interactive states separately when hover or focus styles were not visible in the sampled pages.",
                "- Don't introduce colors, type sizes, spacing, or radii that are not present in the YAML tokens unless deliberately extending the system.",
            ]
        )
    caveats = [str(item).strip() for item in _list(sections.get("caveats")) if str(item).strip()]
    if caveats:
        lines.extend(["", "### Caveats", "", *[f"- {note}" for note in caveats]])
    return "\n".join(lines).strip() + "\n"


async def design_markdown_for_run(session: AsyncSession, run_id: int) -> str:
    row = (
        await session.scalars(
            select(CrawlRecord)
            .where(CrawlRecord.run_id == run_id)
            .order_by(CrawlRecord.id.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        return ""
    raw = row.raw_data if isinstance(row.raw_data, dict) else {}
    markdown = raw.get("markdown")
    return str(markdown or "")


def _build_design_acquisition_request(run: CrawlRun, url: str) -> AcquisitionRequest:
    settings_view = run.settings_view
    profile = settings_view.acquisition_profile()
    profile.update({"fetch_mode": "browser_only", "prefer_browser": True, "requires_browser": True})
    policy = AcquisitionPolicy.from_profile(profile)
    return AcquisitionRequest(
        run_id=run.id,
        url=url,
        plan=AcquisitionPlan(
            surface=DESIGN_SYSTEM_SURFACE,
            proxy_list=tuple(settings_view.proxy_list()),
            traversal_mode=None,
            max_pages=1,
            max_scrolls=1,
            max_records=1,
            sleep_ms=settings_view.sleep_ms(),
        ),
        requested_fields=list(run.requested_fields or []),
        acquisition_profile=policy.to_profile(),
        policy=policy,
    )


def _snapshot_from_acquisition(acquisition: Any) -> dict[str, Any]:
    artifacts = dict(getattr(acquisition, "artifacts", {}) or {})
    snapshot = artifacts.get("design_system_snapshot")
    if isinstance(snapshot, dict):
        return dict(snapshot)
    return {}


async def _shape_design_markdown(
    session: AsyncSession,
    *,
    run: CrawlRun,
    tokens: dict[str, Any],
    source_urls: list[str],
    deterministic_markdown: str,
) -> tuple[str, str]:
    if not run.settings_view.llm_enabled():
        return deterministic_markdown, "skipped"
    result = await run_prompt_task(
        session,
        task_type=DESIGN_SYSTEM_MARKDOWN_TASK,
        run_id=run.id,
        domain=normalize_domain(run.url),
        variables={
            "system_policy": DESIGN_SYSTEM_LLM_SYSTEM_PROMPT,
            "source_urls_json": json.dumps(source_urls, ensure_ascii=True),
            "design_tokens_json": json.dumps(tokens, ensure_ascii=True, sort_keys=True),
            "deterministic_markdown": deterministic_markdown,
        },
        budget_scope=f"design_system:{run.id}",
        timeout_seconds=30,
    )
    if result.error_message or not isinstance(result.payload, dict):
        return deterministic_markdown, "fallback"
    return (
        build_design_markdown(
            tokens=tokens,
            source_urls=source_urls,
            llm_sections=result.payload,
        ),
        "used",
    )


async def _replace_design_record(
    session: AsyncSession,
    *,
    run: CrawlRun,
    markdown: str,
    tokens: dict[str, Any],
    source_urls: list[str],
    llm_status: str,
) -> None:
    await session.execute(delete(CrawlRecord).where(CrawlRecord.run_id == run.id))
    now = datetime.now(UTC).isoformat()
    data = {
        "title": f"Design System - {normalize_domain(run.url) or run.url}",
        "design_tokens": tokens,
        "source_urls": source_urls,
        "generation_metadata": {
            "source": DESIGN_SYSTEM_SOURCE,
            "llm_status": llm_status,
            "generated_at": now,
            "filename": DESIGN_SYSTEM_EXPORT_FILENAME,
        },
        "url": run.url,
    }
    raw_data = {
        **data,
        "markdown": markdown,
        "record_type": DESIGN_SYSTEM_RECORD_TYPE,
        "_source": DESIGN_SYSTEM_SOURCE,
    }
    session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data=data,
            raw_data=raw_data,
            discovered_data={"design_system": data["generation_metadata"]},
            source_trace={
                "field_discovery": {
                    "markdown": {"status": "found", "sources": [DESIGN_SYSTEM_SOURCE]},
                    "design_tokens": {"status": "found", "sources": [DESIGN_SYSTEM_SOURCE]},
                }
            },
        )
    )
    await session.flush()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _sample_limit() -> int:
    return max(1, int(DESIGN_SYSTEM_DEFAULT_SAMPLE_URLS))


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_observed_value(key: str, value: object) -> str:
    text = _text(value)
    if not text or text in {"none", "normal", "transparent", "rgba(0, 0, 0, 0)"}:
        return ""
    if key == "colors":
        return "" if _is_transparent_color(text) else text
    if key == "spacing":
        return _normalize_dimension(text, max_px=96, allow_negative=False)
    if key in {"fontSizes", "lineHeights"}:
        return _normalize_dimension(text, max_px=160, allow_negative=False)
    if key == "fontWeights":
        return text if re.fullmatch(r"[1-9]00|[1-9][0-9]{2}", text) else ""
    if key == "radius":
        return _normalize_radius(text)
    if key == "shadows":
        return "" if _is_empty_shadow(text) else text
    return text


def _top(counter: Counter[str], limit: int) -> list[dict[str, object]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def _component_payload(signature: str, count: int) -> dict[str, object]:
    try:
        payload = json.loads(signature)
    except json.JSONDecodeError:
        payload = {}
    return {**payload, "count": count}


def _value_list(values: object, *, empty: str) -> list[str]:
    rows = [item for item in _list(values) if isinstance(item, dict) and item.get("value")]
    if not rows:
        return [empty]
    return [f"- `{item.get('value')}`" for item in rows[:3]]


def _component_rows(components: dict[str, object]) -> list[str]:
    if not components:
        return ["No stable component tokens found."]
    lines: list[str] = ["| Component | Properties |", "|---|---|"]
    for kind, token in components.items():
        if not isinstance(token, dict):
            continue
        properties = ", ".join(f"{key}: `{value}`" for key, value in token.items())
        lines.append(f"| `{kind}` | {properties or 'No stable token mapping.'} |")
    return lines


def _frontmatter_yaml(*, name: str, description: str, frontmatter: dict[str, Any]) -> list[str]:
    lines = [
        "version: alpha",
        f"name: {_yaml_string(name)}",
        f"description: {_yaml_string(description)}",
    ]
    colors = dict(frontmatter.get("colors") or {})
    if colors:
        lines.append("colors:")
        for key, value in colors.items():
            lines.append(f"  {key}: {_yaml_string(str(value))}")
    typography = dict(frontmatter.get("typography") or {})
    if typography:
        lines.append("typography:")
        for key, value in typography.items():
            if not isinstance(value, dict):
                continue
            lines.append(f"  {key}:")
            for prop, prop_value in value.items():
                rendered = str(prop_value) if prop == "fontWeight" and str(prop_value).isdigit() else _yaml_string(str(prop_value))
                lines.append(f"    {prop}: {rendered}")
    rounded = dict(frontmatter.get("rounded") or {})
    if rounded:
        lines.append("rounded:")
        for key, value in rounded.items():
            lines.append(f"  {key}: {_yaml_string(str(value))}")
    spacing = dict(frontmatter.get("spacing") or {})
    if spacing:
        lines.append("spacing:")
        for key, value in spacing.items():
            lines.append(f"  {key}: {_yaml_string(str(value))}")
    components = dict(frontmatter.get("components") or {})
    if components:
        lines.append("components:")
        for key, value in components.items():
            if not isinstance(value, dict):
                continue
            lines.append(f"  {key}:")
            for prop, prop_value in value.items():
                lines.append(f"    {prop}: {_yaml_string(str(prop_value))}")
    return lines


def _color_token_rows(color_tokens: object) -> list[str]:
    colors = _dict_value(color_tokens)
    if not colors:
        return ["No stable color tokens found."]
    lines = ["| Token | Value | Guidance |", "|---|---|---|"]
    guidance = {
        "primary": "Core text, headings, and high-emphasis UI.",
        "secondary": "Secondary text, metadata, and subdued UI.",
        "tertiary": "Accent, CTA, or highlight color.",
        "neutral": "Page background or quiet base color.",
        "surface": "Cards, panels, and elevated backgrounds.",
        "border": "Rules, dividers, outlines, and input borders.",
        "muted": "Low-emphasis text or disabled treatments.",
    }
    for key, value in colors.items():
        lines.append(f"| `{key}` | `{value}` | {guidance.get(key, 'Observed reusable color role.')} |")
    return lines


def _typography_token_rows(typography_tokens: object) -> list[str]:
    typography = _dict_value(typography_tokens)
    if not typography:
        return ["No stable typography tokens found."]
    lines = ["| Token | Font | Size | Weight | Line Height |", "|---|---|---:|---:|---:|"]
    for key, value in typography.items():
        if not isinstance(value, dict):
            continue
        lines.append(
            f"| `{key}` | `{value.get('fontFamily', '')}` | `{value.get('fontSize', '')}` | "
            f"`{value.get('fontWeight', '')}` | `{value.get('lineHeight', '')}` |"
        )
    return lines


def _scale_rows(label: str, tokens: object) -> list[str]:
    values = _dict_value(tokens)
    lines = [f"### {label}", ""]
    if values:
        lines.extend(["| Token | Value |", "|---|---:|"])
        lines.extend(f"| `{key}` | `{value}` |" for key, value in values.items())
    else:
        lines.append(f"No stable {label.lower()} tokens found.")
    return lines


def _elevation_rows(shadows: object) -> list[str]:
    return [
        "Use these observed shadows only when elevation is needed. Prefer flat surfaces when no shadow token is present.",
        "",
        *_value_list(shadows, empty="No stable shadow token found."),
    ]


def _dict_value(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _sort_css_variables_for_role(
    css_variables: dict[str, str], hints: tuple[str, ...]
) -> list[tuple[str, str]]:
    def sort_key(item: tuple[str, str], role_hints: tuple[str, ...] = hints) -> tuple[int, str]:
        return _var_score(item[0], role_hints)

    return sorted(css_variables.items(), key=sort_key)


def _color_tokens(css_variables: dict[str, str], color_counter: Counter[str]) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for role, hints in DESIGN_SYSTEM_COLOR_ROLE_HINTS.items():
        for name, value in _sort_css_variables_for_role(css_variables, hints):
            if not _matches_hint(name, hints):
                continue
            resolved = _resolve_css_color(value, css_variables)
            if resolved:
                tokens[role] = resolved
                break
    fallback_roles = ["primary", "secondary", "tertiary", "neutral", "surface", "border"]
    for value, _count in color_counter.most_common(12):
        role = next((candidate for candidate in fallback_roles if candidate not in tokens), "")
        if not role:
            break
        color = _resolve_css_color(value, css_variables)
        if color and color not in tokens.values():
            tokens[role] = color
    return tokens


def _typography_tokens(counters: dict[str, Counter[str]]) -> dict[str, dict[str, object]]:
    font = _first_counter_value(counters["fonts"])
    body_size = _first_counter_value(counters["fontSizes"]) or "16px"
    body_weight = _first_counter_value(counters["fontWeights"]) or "400"
    body_line = _first_counter_value(counters["lineHeights"]) or body_size
    tokens: dict[str, dict[str, object]] = {}
    if font:
        tokens["body-md"] = {
            "fontFamily": font,
            "fontSize": body_size,
            "fontWeight": int(body_weight) if body_weight.isdigit() else body_weight,
            "lineHeight": body_line,
        }
        for size, _count in counters["fontSizes"].most_common(8):
            if size == body_size:
                continue
            px = _px_number(size)
            if px is None:
                continue
            name = "headline-md" if px >= 20 else "label-md"
            if name in tokens:
                continue
            tokens[name] = {
                "fontFamily": font,
                "fontSize": size,
                "fontWeight": int(body_weight) if body_weight.isdigit() else body_weight,
                "lineHeight": body_line,
            }
    return tokens


def _scale_tokens(counter: Counter[str], names: tuple[str, ...]) -> dict[str, str]:
    values: list[str] = []
    for value, _count in counter.most_common(24):
        if value not in values:
            values.append(value)
    values.sort(key=lambda item: _px_number(item) or 0)
    return {name: value for name, value in zip(names, values, strict=False)}


def _rounded_tokens(counter: Counter[str]) -> dict[str, str]:
    simple = [
        value
        for value, _count in counter.most_common(24)
        if _is_simple_dimension(value) and value != "9999px"
    ]
    simple = sorted(set(simple), key=lambda item: _px_number(item) or 0)
    tokens = {name: value for name, value in zip(DESIGN_SYSTEM_ROUNDED_TOKEN_NAMES, simple, strict=False)}
    if "9999px" in counter:
        tokens["full"] = "9999px"
    return tokens


def _component_tokens(
    components: dict[str, Counter[str]],
    colors: dict[str, str],
    typography: dict[str, dict[str, object]],
    rounded: dict[str, str],
) -> dict[str, dict[str, str]]:
    tokens: dict[str, dict[str, str]] = {}
    default_typography = "{typography.body-md}" if typography else ""
    rounded_name = "md" if "md" in rounded else next(iter(rounded), "")
    default_rounded = f"{{rounded.{rounded_name}}}" if rounded_name else ""
    for kind, counter in components.items():
        if kind not in {"button", "input", "card", "nav", "table"}:
            continue
        row = _component_payload(counter.most_common(1)[0][0], counter.most_common(1)[0][1])
        token: dict[str, str] = {}
        background = _resolve_css_color(_text(row.get("background")), {})
        color = _resolve_css_color(_text(row.get("color")), {})
        if background:
            ref = _color_ref_for_value(background, colors)
            if ref:
                token["backgroundColor"] = ref
        if color:
            ref = _color_ref_for_value(color, colors)
            if ref:
                token["textColor"] = ref
        if default_typography:
            token["typography"] = default_typography
        if default_rounded:
            token["rounded"] = default_rounded
        padding = _component_padding(_text(row.get("padding")))
        if padding:
            token["padding"] = padding
        if token:
            tokens[kind] = token
    return tokens


def _resolved_css_variables(css_variables: dict[str, str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, value in sorted(css_variables.items()):
        resolved = _resolve_css_color(value, css_variables)
        rows[name] = resolved or value
        if len(rows) >= 40:
            break
    return rows


def _design_name(source_urls: list[str]) -> str:
    domain = normalize_domain(source_urls[0]) if source_urls else ""
    return f"{domain or 'Website'} Design System"


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _is_design_css_variable(name: str, value: str) -> bool:
    if not name.startswith("--"):
        return False
    if any(name.startswith(prefix) for prefix in DESIGN_SYSTEM_INTERNAL_VARIABLE_PREFIXES):
        return False
    if any(f"var({prefix}" in value for prefix in DESIGN_SYSTEM_INTERNAL_VARIABLE_PREFIXES):
        return False
    return bool(_resolve_css_color(value, {}) or _normalize_dimension(value, max_px=240, allow_negative=True) or "font" in name.lower())


def _matches_hint(name: str, hints: tuple[str, ...]) -> bool:
    normalized = name.lower().lstrip("-").replace("_", "-")
    return any(hint in normalized for hint in hints)


def _var_score(name: str, hints: tuple[str, ...]) -> tuple[int, str]:
    normalized = name.lower().lstrip("-").replace("_", "-")
    for index, hint in enumerate(hints):
        if normalized == hint or normalized.endswith(f"-{hint}"):
            return (index, normalized)
    return (len(hints), normalized)


def _resolve_css_color(value: object, css_variables: dict[str, str], seen: set[str] | None = None) -> str:
    text = _text(value)
    if not text or _is_transparent_color(text):
        return ""
    match = re.fullmatch(r"var\((--[A-Za-z0-9_-]+)\)", text)
    if match:
        seen = seen or set()
        name = match.group(1)
        if name in seen:
            return ""
        seen.add(name)
        return _resolve_css_color(css_variables.get(name), css_variables, seen)
    hex_match = re.fullmatch(r"#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})", text)
    if hex_match:
        raw = hex_match.group(1)
        if len(raw) == 3:
            raw = "".join(char * 2 for char in raw)
        return f"#{raw.upper()}"
    rgb_match = re.fullmatch(r"rgba?\(([^)]+)\)", text)
    if rgb_match:
        parts = [part.strip() for part in rgb_match.group(1).split(",")]
        if len(parts) >= 3:
            return _rgb_to_hex(parts[:3])
    triplet = re.fullmatch(r"(\d{1,3})[,\s]+(\d{1,3})[,\s]+(\d{1,3})", text)
    if triplet:
        return _rgb_to_hex(list(triplet.groups()))
    return ""


def _rgb_to_hex(parts: list[str]) -> str:
    channels: list[int] = []
    for part in parts:
        try:
            channel = int(float(part))
        except ValueError:
            return ""
        if channel < 0 or channel > 255:
            return ""
        channels.append(channel)
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _color_ref_for_value(value: str, colors: dict[str, str]) -> str:
    for name, token_value in colors.items():
        if token_value.upper() == value.upper():
            return f"{{colors.{name}}}"
    return ""


def _normalize_dimension(value: str, *, max_px: float, allow_negative: bool) -> str:
    px = _px_number(value)
    if px is None:
        return ""
    if not allow_negative and px <= 0:
        return ""
    if abs(px) > max_px:
        return ""
    if px.is_integer():
        return f"{int(px)}px"
    return f"{px:.2f}".rstrip("0").rstrip(".") + "px"


def _normalize_radius(value: str) -> str:
    parts = value.split()
    if not parts:
        return ""
    normalized = [_normalize_dimension(part, max_px=9999, allow_negative=False) for part in parts]
    if not all(normalized):
        return ""
    if all(part == normalized[0] for part in normalized):
        return normalized[0]
    return " ".join(normalized)


def _px_number(value: str) -> float | None:
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", _text(value))
    if not match:
        return None
    return float(match.group(1))


def _is_simple_dimension(value: str) -> bool:
    return _px_number(value) is not None


def _is_transparent_color(value: str) -> bool:
    text = _text(value).lower()
    return text in {"transparent", "rgba(0, 0, 0, 0)"} or text.endswith(", 0)") or text.endswith(",0)")


def _is_empty_shadow(value: str) -> bool:
    text = _text(value).lower()
    return text in {"none", "rgba(0, 0, 0, 0) 0px 0px 0px 0px"} or "rgba(0, 0, 0, 0) 0px 0px 0px 0px" == text


def _first_counter_value(counter: Counter[str]) -> str:
    return counter.most_common(1)[0][0] if counter else ""


def _component_padding(value: str) -> str:
    parts = [_normalize_dimension(part, max_px=96, allow_negative=False) for part in value.split()]
    usable = [part for part in parts if part]
    if not usable:
        return ""
    counts = Counter(usable)
    return counts.most_common(1)[0][0]


def _clean_llm_sections(sections: dict[str, Any], tokens: dict[str, Any]) -> dict[str, Any]:
    allowed = _allowed_token_literals(tokens)
    cleaned: dict[str, Any] = {}
    for key in ("name", "description", "overview"):
        value = _text(sections.get(key))
        if value and not _contains_unknown_token_literal(value, allowed):
            cleaned[key] = value
    notes = [
        _text(item)
        for item in _list(sections.get("usage_notes"))
        if _text(item) and not _contains_unknown_token_literal(_text(item), allowed)
    ]
    caveats = [
        _text(item)
        for item in _list(sections.get("caveats"))
        if _text(item) and not _contains_unknown_token_literal(_text(item), allowed)
    ]
    if notes:
        cleaned["usage_notes"] = notes
    if caveats:
        cleaned["caveats"] = caveats
    return cleaned


def _allowed_token_literals(tokens: dict[str, Any]) -> set[str]:
    literals: set[str] = set()
    frontmatter = dict(tokens.get("frontmatter") or {})
    for value in dict(frontmatter.get("colors") or {}).values():
        text = _text(value).upper()
        if text:
            literals.add(text)
    for row in _list(tokens.get("colors")):
        if isinstance(row, dict):
            resolved = _resolve_css_color(row.get("value"), {})
            if resolved:
                literals.add(resolved.upper())
    return literals


def _contains_unknown_token_literal(text: str, allowed: set[str]) -> bool:
    for match in re.findall(r"#[0-9A-Fa-f]{3,6}", text):
        resolved = _resolve_css_color(match, {})
        if resolved and resolved.upper() not in allowed:
            return True
    for match in re.findall(r"rgba?\([^)]+\)", text):
        resolved = _resolve_css_color(match, {})
        if resolved and resolved.upper() not in allowed:
            return True
    return False
