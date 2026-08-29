from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.acquisition.browser_runtime import (
    SharedBrowserRuntime,
    _display_proxy,
    get_browser_runtime,
    shutdown_browser_runtime,
)
from app.core.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS as BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS,
    BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS,
    BROWSER_SURFACE_PROBE_RETRY_BACKOFF_MS,
    BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES,
    BROWSER_SURFACE_PROBE_TARGETS,
)
from app.crawl.crud import get_run
from browser_surface_probe import signal_extractor as _signal_extractor
from browser_surface_probe.report_rendering import (
    build_agent_summary,
    build_findings,
    render_markdown,
)
from browser_surface_probe.signal_extractor import (
    _collect_baseline,
    _collect_behavioral_smoke,
    _collect_page_snapshot,
    _extract_creepjs,
    _extract_generic_site,
    _extract_pixelscan,
    _sannysoft_signal_rows,
)
from browser_surface_probe.target_diagnostics import (
    RuntimeSource,
    _capture_probe_artifacts,
    _failed_target_diagnostic,
    _navigate_probe_target,
    _run_target_diagnostic,
    _target_root_cause,
    _validated_target_url,
)

from browser_surface_probe.value_coercion import (
    coalesce as _coalesce,
    normalize_space as _normalize_space,
    object_dict,
    object_list,
)

load_baseline_probe_script = _signal_extractor.load_baseline_probe_script

_BUNDLE_DIRNAME = "browser_surface_probe"
logger = logging.getLogger(__name__)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, default=str)


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _coerce_proxy_profile(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


_object_dict = object_dict
_object_list = object_list


def _dict_rows(value: object) -> list[dict[str, object]]:
    return [
        _object_dict(item) for item in _object_list(value) if isinstance(item, dict)
    ]


def _coerce_locality_profile(
    *,
    geo_country: object = None,
    language_hint: object = None,
    currency_hint: object = None,
) -> dict[str, object]:
    normalized_geo = _normalize_space(geo_country).upper() or "auto"
    if len(normalized_geo) != 2 or not normalized_geo.isalpha():
        normalized_geo = "auto"
    normalized_language = _normalize_space(language_hint) or None
    normalized_currency = _normalize_space(currency_hint) or None
    return {
        "geo_country": normalized_geo,
        "language_hint": normalized_language,
        "currency_hint": normalized_currency,
    }


async def _load_run_runtime_source(
    run_id: int, *, browser_engine: str
) -> RuntimeSource:
    async with SessionLocal() as session:
        run = await get_run(session, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    settings_view = run.settings_view
    proxy_list = settings_view.proxy_list()
    proxy_profile = settings_view.proxy_profile()
    locality_profile = settings_view.locality_profile()
    enabled = bool(proxy_profile.get("enabled"))
    selected_proxy = proxy_list[0] if enabled and proxy_list else None
    selected_proxy_index = 0 if selected_proxy is not None else None
    return RuntimeSource(
        source_kind="run",
        run_id=run.id,
        identity_run_id=run.id,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        selected_proxy=selected_proxy,
        selected_proxy_index=selected_proxy_index,
        browser_engine=browser_engine,
    )


def _load_explicit_runtime_source(
    *,
    proxies: list[str],
    proxy_profile_path: str | None,
    locality_profile: dict[str, object],
    browser_engine: str,
) -> RuntimeSource:
    proxy_profile: dict[str, object] = {}
    if proxy_profile_path:
        raw = json.loads(Path(proxy_profile_path).read_text(encoding="utf-8"))
        proxy_profile = _coerce_proxy_profile(raw)
    proxy_list = [
        _normalize_space(value) for value in proxies if _normalize_space(value)
    ]
    enabled = bool(proxy_list) or bool(proxy_profile.get("enabled"))
    if enabled:
        proxy_profile = dict(proxy_profile)
        proxy_profile["enabled"] = True
        proxy_profile["proxy_list"] = proxy_list
    selected_proxy = proxy_list[0] if proxy_list else None
    selected_proxy_index = 0 if selected_proxy is not None else None
    identity_run_id = time.time_ns()
    return RuntimeSource(
        source_kind="explicit_proxy" if proxy_list else "direct",
        run_id=None,
        identity_run_id=identity_run_id,
        proxy_list=proxy_list,
        proxy_profile=proxy_profile,
        locality_profile=locality_profile,
        selected_proxy=selected_proxy,
        selected_proxy_index=selected_proxy_index,
        browser_engine=browser_engine,
    )


async def _resolve_runtime_source(args: argparse.Namespace) -> RuntimeSource:
    explicit_proxies = list(args.proxy or [])
    if args.run_id is not None and (explicit_proxies or args.proxy_profile_json):
        raise ValueError("Provide either --run-id or explicit proxy flags, not both")
    if args.run_id is not None:
        return await _load_run_runtime_source(
            args.run_id, browser_engine=args.browser_engine
        )
    return _load_explicit_runtime_source(
        proxies=explicit_proxies,
        proxy_profile_path=args.proxy_profile_json,
        locality_profile=_coerce_locality_profile(
            geo_country=args.geo_country,
            language_hint=args.language_hint,
            currency_hint=args.currency_hint,
        ),
        browser_engine=args.browser_engine,
    )


def _masked_proxy_inventory(proxy_list: list[str]) -> list[str]:
    return [_display_proxy(value) for value in proxy_list]


def _report_root(base_dir: str | None) -> Path:
    base = (
        Path(base_dir)
        if base_dir
        else Path(__file__).resolve().parent / "artifacts" / _BUNDLE_DIRNAME
    )
    return base


def _consensus_baseline(per_site: dict[str, dict[str, object]]) -> dict[str, object]:
    if not per_site:
        return {"consensus": {}, "drift": {}}
    keys = (
        "user_agent",
        "user_agent_data",
        "webdriver",
        "locale",
        "languages",
        "timezone",
        "platform",
        "vendor",
        "plugins_count",
        "plugin_names",
        "hardware_concurrency",
        "device_memory",
        "screen",
        "viewport",
        "webgl",
        "canvas",
        "audio",
        "fonts",
        "connection",
        "screen_orientation",
        "max_touch_points",
        "pdf_viewer_enabled",
        "cookie_enabled",
        "do_not_track",
        "automation_globals",
        "timing_jitter",
        "iframe_leak",
        "permissions",
        "behavioral_smoke",
        "webrtc_ips",
    )
    consensus: dict[str, object] = {}
    drift: dict[str, list[object]] = {}
    for key in keys:
        values = [payload.get(key) for payload in per_site.values()]
        normalized_values = [
            value for value in values if value not in (None, "", [], {})
        ]
        consensus[key] = _coalesce(normalized_values)
        unique_values = []
        seen_serialized: set[str] = set()
        for value in normalized_values:
            marker = json.dumps(value, sort_keys=True, default=str)
            if marker in seen_serialized:
                continue
            seen_serialized.add(marker)
            unique_values.append(value)
        if len(unique_values) > 1:
            drift[key] = unique_values
    return {
        "consensus": consensus,
        "drift": drift,
    }


def _site_artifacts(base_dir: Path, site_id: str) -> dict[str, Path]:
    return {
        "screenshot": base_dir / f"{site_id}.png",
        "html": base_dir / f"{site_id}.html",
    }


def _site_signal_payload(
    site_id: str, snapshot: dict[str, object]
) -> dict[str, object]:
    if site_id == "sannysoft":
        return _sannysoft_signal_rows(_dict_rows(snapshot.get("rows")))
    if site_id == "pixelscan":
        return _extract_pixelscan(snapshot)
    if site_id == "creepjs":
        return _extract_creepjs(snapshot)
    return _extract_generic_site(snapshot)


def _site_validation_warnings(site_id: str, snapshot: dict[str, object]) -> list[str]:
    lines = _object_list(snapshot.get("lines"))
    rows = _object_list(snapshot.get("rows"))
    warnings: list[str] = []
    if not lines and not rows:
        warnings.append("no_visible_text_or_rows")
    if site_id == "sannysoft" and not rows:
        warnings.append("missing_sannysoft_rows")
    if site_id == "creepjs" and not bool(snapshot.get("has_creep_object")):
        warnings.append("missing_creepjs_object")
    return warnings


def _failed_site_payload(
    *,
    site_id: str,
    site_label: str,
    url: str,
    artifacts: dict[str, Path],
    attempts: int,
    error: str,
) -> dict[str, object]:
    return {
        "site_id": site_id,
        "label": site_label,
        "url": url,
        "site_status": "failed",
        "attempts": attempts,
        "error": error,
        "error_message": error,
        "artifacts": {
            "screenshot": artifacts["screenshot"].name
            if artifacts["screenshot"].exists()
            else None,
            "html": artifacts["html"].name if artifacts["html"].exists() else None,
        },
        "baseline": {},
        "snapshot_summary": {},
        "extracted": {},
    }


async def _probe_site(
    runtime: SharedBrowserRuntime,
    *,
    site_id: str,
    site_label: str,
    url: str,
    run_id: int,
    locality_profile: dict[str, object],
    artifacts_dir: Path,
) -> dict[str, object]:
    artifacts = _site_artifacts(artifacts_dir, site_id)
    max_attempts = max(1, int(BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES) + 1)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            async with runtime.page(
                run_id=run_id,
                locality_profile=locality_profile,
                allow_storage_state=False,
            ) as page:
                try:
                    await _navigate_probe_target(page, url)
                    behavioral_smoke = await _collect_behavioral_smoke(page)
                    baseline = await _collect_baseline(
                        page, behavioral_smoke=behavioral_smoke
                    )
                    snapshot = await _collect_page_snapshot(page)
                    html = await page.content()
                    await page.screenshot(
                        path=str(artifacts["screenshot"]), full_page=True
                    )
                    artifacts["html"].write_text(html, encoding="utf-8")
                    extracted = _site_signal_payload(site_id, snapshot)
                    validation_warnings = _site_validation_warnings(site_id, snapshot)
                    return {
                        "site_id": site_id,
                        "label": site_label,
                        "url": url,
                        "site_status": "degraded" if validation_warnings else "ok",
                        "attempts": attempt,
                        "validation_warnings": validation_warnings,
                        "final_url": _normalize_space(page.url),
                        "title": _normalize_space(await page.title()),
                        "artifacts": {
                            "screenshot": artifacts["screenshot"].name,
                            "html": artifacts["html"].name,
                        },
                        "baseline": baseline,
                        "snapshot_summary": {
                            "line_count": snapshot.get("line_count", 0),
                            "line_count_raw": snapshot.get(
                                "line_count_raw", snapshot.get("line_count", 0)
                            ),
                            "lines": _object_list(snapshot.get("lines")),
                            "row_count": snapshot.get("row_count", 0),
                            "row_count_raw": snapshot.get(
                                "row_count_raw", snapshot.get("row_count", 0)
                            ),
                            "rows": _object_list(snapshot.get("rows")),
                            "has_creep_object": bool(snapshot.get("has_creep_object")),
                            "has_fingerprint_object": bool(
                                snapshot.get("has_fingerprint_object")
                            ),
                        },
                        "extracted": extracted,
                    }
                except Exception:
                    await _capture_probe_artifacts(page, artifacts)
                    raise
        except Exception as exc:  # noqa: BLE001 - probe records arbitrary browser failures
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Browser surface probe failed site=%s attempt=%s/%s: %s",
                site_id,
                attempt,
                max_attempts,
                last_error,
            )
            if attempt < max_attempts:
                backoff_ms = max(0, int(BROWSER_SURFACE_PROBE_RETRY_BACKOFF_MS))
                if backoff_ms:
                    await asyncio.sleep((backoff_ms * attempt) / 1000)
    return _failed_site_payload(
        site_id=site_id,
        site_label=site_label,
        url=url,
        artifacts=artifacts,
        attempts=max_attempts,
        error=last_error or "unknown probe failure",
    )


async def build_report(
    *,
    runtime_source: RuntimeSource,
    report_dir: Path,
    target_urls: list[str] | None = None,
    runtime_provider=get_browser_runtime,
) -> dict[str, object]:
    report_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded setup I/O
    runtime = await runtime_provider(
        proxy=runtime_source.selected_proxy,
        browser_engine=runtime_source.browser_engine,
    )
    sites: dict[str, dict[str, object]] = {}
    for index, target in enumerate(BROWSER_SURFACE_PROBE_TARGETS):
        site_payload = await _probe_site(
            runtime,
            site_id=str(target["id"]),
            site_label=str(target["label"]),
            url=str(target["url"]),
            run_id=runtime_source.identity_run_id,
            locality_profile=runtime_source.locality_profile,
            artifacts_dir=report_dir,
        )
        sites[str(target["id"])] = site_payload
        delay_ms = max(0, int(BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS))
        if delay_ms and index < len(BROWSER_SURFACE_PROBE_TARGETS) - 1:
            await asyncio.sleep(delay_ms / 1000)
    baseline = _consensus_baseline(
        {
            site_id: _object_dict(site_payload.get("baseline"))
            for site_id, site_payload in sites.items()
            if isinstance(site_payload, dict)
        }
    )
    consensus = _object_dict(baseline.get("consensus"))
    target_diagnostics: list[dict[str, object]] = []
    for raw_url in list(target_urls or []):
        raw = _normalize_space(raw_url)
        if not raw:
            continue
        try:
            url = _validated_target_url(raw)
        except ValueError as exc:
            target_diagnostics.append(
                _failed_target_diagnostic(url=raw, error=f"{type(exc).__name__}: {exc}")
            )
            continue
        try:
            diagnostic = await _run_target_diagnostic(
                runtime,
                url=url,
                runtime_source=runtime_source,
                artifacts_dir=report_dir,
            )
        except Exception as exc:  # noqa: BLE001 - each probe target is isolated
            diagnostic = _failed_target_diagnostic(
                url=url,
                error=f"{type(exc).__name__}: {exc}",
            )
        diagnostic["root_cause"] = _target_root_cause(
            consensus=consensus,
            diagnostic=diagnostic,
        )
        target_diagnostics.append(diagnostic)
    site_statuses = {
        site_id: str(site_payload.get("site_status") or "unknown")
        for site_id, site_payload in sites.items()
    }
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_kind": runtime_source.source_kind,
        "source_run_id": runtime_source.run_id,
        "identity_run_id": runtime_source.identity_run_id,
        "browser_engine": runtime_source.browser_engine,
        "selected_proxy_mask": _display_proxy(runtime_source.selected_proxy),
        "selected_proxy_index": runtime_source.selected_proxy_index,
        "proxy_inventory_masked": _masked_proxy_inventory(runtime_source.proxy_list),
        "proxy_profile": runtime_source.proxy_profile,
        "locality_profile": runtime_source.locality_profile,
        "runtime_snapshot": runtime.snapshot(),
        "site_statuses": site_statuses,
        "degraded": any(status != "ok" for status in site_statuses.values()),
    }
    report: dict[str, object] = {
        "metadata": metadata,
        "connection_source": {
            "source_kind": runtime_source.source_kind,
            "run_id": runtime_source.run_id,
            "selected_proxy_mask": _display_proxy(runtime_source.selected_proxy),
            "proxy_inventory_masked": _masked_proxy_inventory(
                runtime_source.proxy_list
            ),
            "proxy_profile": runtime_source.proxy_profile,
            "locality_profile": runtime_source.locality_profile,
        },
        "baseline": baseline,
        "sites": sites,
        "target_diagnostics": target_diagnostics,
    }
    report["findings"] = build_findings(report)
    report["agent_summary"] = build_agent_summary(report)
    (report_dir / "report.json").write_text(_json_dump(report), encoding="utf-8")
    (report_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--proxy", action="append", default=[])
    parser.add_argument("--proxy-profile-json", default=None)
    parser.add_argument("--target-url", action="append", default=[])
    parser.add_argument("--geo-country", default=None)
    parser.add_argument("--language-hint", default=None)
    parser.add_argument("--currency-hint", default=None)
    parser.add_argument(
        "--browser-engine",
        choices=("chromium", "real_chrome", "patchright"),
        default="chromium",
    )
    parser.add_argument("--report-dir", default=None)
    return parser


async def async_main(args: argparse.Namespace) -> Path:
    runtime_source = await _resolve_runtime_source(args)
    bundle_dir = _report_root(args.report_dir) / _utc_stamp()
    await build_report(
        runtime_source=runtime_source,
        report_dir=bundle_dir,
        target_urls=list(args.target_url or []),
    )
    return bundle_dir


async def _run(args: argparse.Namespace) -> int:
    bundle_dir: Path | None = None
    try:
        bundle_dir = await async_main(args)
    finally:
        await shutdown_browser_runtime()
    if bundle_dir is None:
        raise RuntimeError("Fingerprint report bundle was not created")
    print(_json_dump({"report_dir": str(bundle_dir)}))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
