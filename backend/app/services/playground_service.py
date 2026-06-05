from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.playground import PlaygroundSession
from app.models.user import User
from app.services.config.aid_score import (
    AID_AUDIT_JOB_STATUS_COMPLETE,
    AID_AUDIT_JOB_STATUS_FAILED,
)
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_JOB_TERMINAL_STATUSES,
    ECOMMERCE_DETAIL_SURFACE,
    ECOMMERCE_LISTING_SURFACE,
)
from app.services.config.monitor_settings import MONITOR_PRIORITY_BACKGROUND
from app.services.config.product_intelligence import (
    PRODUCT_INTELLIGENCE_JOB_STATUS_COMPLETE,
    PRODUCT_INTELLIGENCE_JOB_STATUS_FAILED,
)
from app.services.config.sitemap import (
    PLAYGROUND_CATEGORY_DEFAULT_LIMIT,
    PLAYGROUND_CATEGORY_MAX_LIMIT,
)
from app.services.crawl.category_discovery import discover_category_urls
from app.services.crawl.ingestion_service import create_crawl_run_from_payload
from app.services.crawl.state import TERMINAL_STATUSES
from app.services.surface_resolver import resolve_auto_surface

logger = logging.getLogger(__name__)

_AUDIT_TERMINAL_STATUSES = {AID_AUDIT_JOB_STATUS_COMPLETE, AID_AUDIT_JOB_STATUS_FAILED}
_PI_TERMINAL_STATUSES = {PRODUCT_INTELLIGENCE_JOB_STATUS_COMPLETE, PRODUCT_INTELLIGENCE_JOB_STATUS_FAILED}
_ENRICH_TERMINAL_STATUSES = set(DATA_ENRICHMENT_JOB_TERMINAL_STATUSES)

MAX_PRODUCTS = 50


def _classify_input_url(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")
    if not path:
        return "sitemap"
    resolution = resolve_auto_surface(url=url)
    surface = resolution.surface
    if (
        surface == "content_detail"
        and resolution.confidence < 0.5
        and path.count("/") == 0
    ):
        return "sitemap"
    if surface.endswith("_detail"):
        return "detail"
    if surface == ECOMMERCE_LISTING_SURFACE or surface.endswith("_listing"):
        return "listing"
    return "listing"


def _detail_surface_for_url(url: str) -> str:
    surface = resolve_auto_surface(url=url).surface
    return surface if surface.endswith("_detail") else ECOMMERCE_DETAIL_SURFACE


async def create_session(
    session: AsyncSession,
    *,
    user: User,
    url: str | None = None,
    urls: list[str] | None = None,
    category_limit: int = PLAYGROUND_CATEGORY_DEFAULT_LIMIT,
) -> PlaygroundSession:
    input_values: list[str] = [item for item in [url, *(urls or [])] if item is not None]
    input_urls = _normalize_input_urls(input_values)
    if not input_urls:
        raise ValueError("URL is required")
    if len(input_urls) > MAX_PRODUCTS:
        raise ValueError(f"Maximum {MAX_PRODUCTS} input URLs per session")

    safe_category_limit = _safe_category_limit(category_limit)
    step_data: dict[str, object] = {"category_limit": safe_category_limit}
    if len(input_urls) > 1:
        step_data["input_urls"] = input_urls

    playground = PlaygroundSession(
        user_id=user.id,
        input_url=input_urls[0],
        state="created",
        step_data=step_data,
    )
    session.add(playground)
    await session.flush()
    await session.refresh(playground)
    return playground


async def get_session(
    session: AsyncSession,
    *,
    session_id: int,
    user: User,
) -> PlaygroundSession:
    playground = await session.get(PlaygroundSession, session_id)
    if playground is None or playground.user_id != user.id:
        raise LookupError("Session not found")
    _ = playground.step_data
    state_before = playground.state
    step_data_before = playground.step_data
    await _auto_advance(session, playground)
    if playground.state != state_before or playground.step_data != step_data_before:
        await session.flush()
        await session.refresh(playground)
    return playground


async def list_sessions(
    session: AsyncSession,
    *,
    user: User,
    limit: int = 20,
) -> list[PlaygroundSession]:
    rows = await session.scalars(
        select(PlaygroundSession)
        .where(PlaygroundSession.user_id == user.id)
        .order_by(PlaygroundSession.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def start_discover(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    user: User,
) -> dict[str, Any]:
    _require_state(playground, "created")

    classification = _classify_input_url(playground.input_url)
    step_data = dict(playground.step_data or {})
    input_urls = _session_input_urls(playground)
    category_limit = _session_category_limit(playground)

    if len(input_urls) > 1:
        detail_urls, discover_urls = _partition_playground_urls(input_urls)
        if detail_urls and not discover_urls:
            run_ids = await _launch_extract_runs(
                session,
                playground=playground,
                user=user,
                urls=detail_urls,
                skipped_discover=True,
            )
            return {"stage": "detail", "run_id": run_ids[0]}
        if detail_urls:
            step_data["seed_detail_urls"] = detail_urls

        sitemap = await _resolve_category_list_for_inputs(
            discover_urls,
            limit=category_limit,
        )
        step_data["sitemap"] = sitemap
        playground.state = "sitemap_listed"
        playground.step_data = step_data
        await session.flush()
        return {"stage": "sitemap", "url_count": int(sitemap["total_found"])}

    if classification == "sitemap":
        sitemap = await _resolve_category_list_for_inputs(
            [playground.input_url],
            limit=category_limit,
        )
        first_tree = sitemap.get("trees", {}).get(playground.input_url)
        if first_tree:
            sitemap["nav_tree"] = first_tree
        first_error = sitemap.get("errors", {}).get(playground.input_url)
        if first_error:
            sitemap["error"] = first_error
        step_data["sitemap"] = sitemap
        playground.state = "sitemap_listed"
        playground.step_data = step_data
        await session.flush()
        return {"stage": "sitemap", "url_count": int(sitemap["total_found"])}

    if classification == "detail":
        run = await create_crawl_run_from_payload(
            session,
            user.id,
            {
                "run_type": "crawl",
                "url": playground.input_url,
                "surface": _detail_surface_for_url(playground.input_url),
                "settings": {"playground_session_id": playground.id},
            },
        )
        step_data["selected_urls"] = [playground.input_url]
        step_data["extract"] = {
            "run_id": run.id,
            "run_ids": [run.id],
            "status": "running",
            "url_count": 1,
            "skipped_discover": True,
        }
        playground.state = "extracting"
        playground.step_data = step_data
        await session.flush()
        return {"stage": "detail", "run_id": run.id}

    run = await create_crawl_run_from_payload(
        session,
        user.id,
        {
            "run_type": "crawl",
            "url": playground.input_url,
            "surface": ECOMMERCE_LISTING_SURFACE,
            "settings": {"playground_session_id": playground.id},
        },
    )
    step_data["discover"] = {"run_id": run.id, "status": "running"}
    playground.state = "discovering"
    playground.step_data = step_data
    await session.flush()
    return {"stage": "listing", "run_id": run.id}


# skipcq: PY-R1000
async def _resolve_category_list_for_inputs(
    urls: list[str],
    *,
    limit: int,
) -> dict[str, Any]:
    discover_urls: list[str] = []
    input_listing_urls: list[str] = []
    groups: dict[str, list[str]] = {}
    sources: dict[str, str] = {}
    for url in urls:
        classification = _classify_input_url(url)
        if classification == "listing":
            input_listing_urls.append(url)
            groups[url] = [url]
            sources[url] = "input"
        elif classification != "detail":
            discover_urls.append(url)

    discovered: dict[str, Any] = (
        await discover_category_urls(discover_urls, limit=limit)
        if discover_urls
        else {
            "status": "completed",
            "source": "input",
            "sources": {},
            "urls": [],
            "groups": {},
            "trees": {},
            "errors": {},
            "diagnostics": {},
            "total_found": 0,
            "limit": limit,
        }
    )
    merged_groups = {**groups, **dict(discovered.get("groups") or {})}
    merged_sources = {**sources, **dict(discovered.get("sources") or {})}
    flat_urls: list[str] = []
    for url in [*input_listing_urls, *list(discovered.get("urls") or [])]:
        if isinstance(url, str) and url not in flat_urls:
            flat_urls.append(url)
    source = str(discovered.get("source") or "multi")
    if input_listing_urls and not discover_urls:
        source = "input"
    elif input_listing_urls:
        source = "multi"
    discovered_total = int(discovered.get("total_found") or 0)
    total_found = max(len(flat_urls), discovered_total + len(input_listing_urls))
    return {
        "status": "completed",
        "source": source,
        "sources": merged_sources,
        "urls": flat_urls[:limit],
        "groups": merged_groups,
        "trees": dict(discovered.get("trees") or {}),
        "errors": dict(discovered.get("errors") or {}),
        "diagnostics": dict(discovered.get("diagnostics") or {}),
        "total_found": total_found,
        "limit": limit,
    }


async def select_category(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    user: User,
    urls: list[str],
) -> int:
    _require_state(playground, "sitemap_listed")
    normalized_urls = [url.strip() for url in urls if url and url.strip()]
    if not normalized_urls:
        raise ValueError("category URL is required")
    unique_urls = list(dict.fromkeys(_validate_http_urls(normalized_urls)))
    if len(unique_urls) > MAX_PRODUCTS:
        raise ValueError(f"Maximum {MAX_PRODUCTS} category URLs per session")
    detail_urls, discover_urls = _partition_playground_urls(unique_urls)
    if detail_urls and not discover_urls:
        run_ids = await _launch_extract_runs(
            session,
            playground=playground,
            user=user,
            urls=detail_urls,
            skipped_discover=True,
        )
        return run_ids[0]

    run_type = "batch" if len(discover_urls) > 1 else "crawl"

    run = await create_crawl_run_from_payload(
        session,
        user.id,
        {
            "run_type": run_type,
            "url": discover_urls[0],
            "urls": discover_urls if len(discover_urls) > 1 else None,
            "surface": ECOMMERCE_LISTING_SURFACE,
            "settings": {"playground_session_id": playground.id},
        },
    )
    step_data = dict(playground.step_data or {})
    step_data["selected_category_url"] = discover_urls[0]
    step_data["selected_category_urls"] = discover_urls
    if detail_urls:
        step_data["seed_detail_urls"] = detail_urls
    step_data["discover"] = {"run_id": run.id, "status": "running"}
    playground.state = "discovering"
    playground.step_data = step_data
    await session.flush()
    return run.id


async def complete_discover(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    products: list[dict[str, Any]],
) -> None:
    _require_state(playground, "discovering")

    playground.state = "discovered"
    step_data = dict(playground.step_data or {})
    step_data["discover"] = {
        **step_data.get("discover", {}),
        "status": "completed",
        "products": products[:MAX_PRODUCTS],
        "total_found": len(products),
    }
    playground.step_data = step_data
    await session.flush()


async def select_products(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    urls: list[str],
) -> list[str]:
    _require_state(playground, "discovered")

    if len(urls) > MAX_PRODUCTS:
        raise ValueError(f"Maximum {MAX_PRODUCTS} products per session")
    if not urls:
        raise ValueError("Select at least one product")

    step_data = dict(playground.step_data or {})
    step_data["selected_urls"] = urls
    playground.step_data = step_data
    await session.flush()
    return urls


async def start_extract(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    user: User,
) -> list[int]:
    _require_state(playground, "discovered")

    urls = (playground.step_data or {}).get("selected_urls", [])
    if not urls:
        raise ValueError("No products selected — call select first")
    return await _launch_extract_runs(
        session,
        playground=playground,
        user=user,
        urls=urls,
    )


async def start_pipeline(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    user: User,
    enrich: bool = False,
    compare: bool = False,
    monitor: bool = False,
    audit: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, int]]]:
    needs_extracted = bool(enrich or compare or monitor)
    if needs_extracted:
        _require_state(playground, "extracted")
    elif playground.state == "created":
        raise ValueError("Session not started — call discover first")

    launched: dict[str, Any] = {}
    dispatch_specs: list[tuple[Any, int]] = []
    step_data = dict(playground.step_data or {})
    extract_run_ids = _extract_run_ids(step_data)
    source_record_ids = await _extract_record_ids(session, extract_run_ids)

    if enrich:
        if not source_record_ids:
            launched["enrich"] = {
                "job_id": None,
                "status": "failed",
                "error": "No extracted records available",
            }
        else:
            from app.services.data_enrichment.service import (
                create_data_enrichment_job,
                run_data_enrichment_job,
            )
            try:
                enrich_job = await create_data_enrichment_job(
                    session,
                    user=user,
                    payload={"source_record_ids": source_record_ids},
                )
                launched["enrich"] = {"job_id": enrich_job.id, "status": "running"}
                dispatch_specs.append((run_data_enrichment_job, enrich_job.id))
            except Exception as exc:
                logger.error("Pipeline enrich failed: %s", exc, exc_info=True)
                launched["enrich"] = {
                    "job_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
        step_data["enrich"] = launched["enrich"]

    if compare:
        if not source_record_ids:
            launched["compare"] = {
                "job_id": None,
                "status": "failed",
                "error": "No extracted records available",
            }
        else:
            from app.services.product_intelligence.service import (
                create_product_intelligence_job,
                run_product_intelligence_job,
            )
            try:
                compare_job = await create_product_intelligence_job(
                    session,
                    user=user,
                    payload={"source_record_ids": source_record_ids},
                )
                launched["compare"] = {"job_id": compare_job.id, "status": "running"}
                dispatch_specs.append((run_product_intelligence_job, compare_job.id))
            except Exception as exc:
                logger.error("Pipeline compare failed: %s", exc, exc_info=True)
                launched["compare"] = {
                    "job_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
        step_data["compare"] = launched["compare"]

    if monitor:
        selected_urls = step_data.get("selected_urls", [])
        from app.services.monitor_service import create_monitor

        if not selected_urls:
            launched["monitor"] = {
                "monitor_id": None,
                "status": "failed",
                "error": "No extracted URLs available",
            }
        else:
            try:
                monitor_obj = await create_monitor(
                    session,
                    user=user,
                    payload={
                        "name": f"Playground monitor for {urlparse(selected_urls[0]).netloc or 'selected products'}",
                        "urls": selected_urls,
                        "surface": ECOMMERCE_DETAIL_SURFACE,
                        "tracked_fields": ["price", "availability"],
                        "requested_fields": ["price", "availability"],
                        "schedule_interval_hours": 24,
                        "priority": MONITOR_PRIORITY_BACKGROUND,
                    },
                )
                launched["monitor"] = {
                    "monitor_id": monitor_obj.id,
                    "status": "created",
                    "url_count": len(selected_urls),
                }
            except Exception as exc:
                logger.error("Pipeline monitor failed: %s", exc, exc_info=True)
                launched["monitor"] = {
                    "monitor_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
        step_data["monitor"] = launched["monitor"]

    if audit:
        from app.services.ucp_audit.service import (
            create_ucp_audit_job,
            run_ucp_audit_job,
        )
        try:
            audit_job = await create_ucp_audit_job(
                session,
                user=user,
                payload={"domain": playground.input_url},
            )
            launched["audit"] = {"job_id": audit_job.id, "status": "running"}
            dispatch_specs.append((run_ucp_audit_job, audit_job.id))
        except Exception as exc:
            logger.error("Pipeline audit failed: %s", exc, exc_info=True)
            launched["audit"] = {
                "job_id": None,
                "status": "failed",
                "error": str(exc),
            }
        step_data["audit"] = launched["audit"]

    if needs_extracted:
        playground.state = "running_pipeline"
    playground.step_data = step_data
    await session.flush()
    return launched, dispatch_specs


async def get_results(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
) -> dict[str, Any]:
    step_data = dict(playground.step_data or {})
    results: dict[str, Any] = {
        "state": playground.state,
        "input_url": playground.input_url,
        "steps": {},
    }

    discover = step_data.get("discover", {})
    if discover:
        results["steps"]["discover"] = {
            "status": discover.get("status"),
            "total_found": discover.get("total_found", 0),
            "products": discover.get("products", []),
        }

    results["steps"]["selected_urls"] = step_data.get("selected_urls", [])

    extract = step_data.get("extract", {})
    if extract:
        records = await _extract_records(session, _extract_run_ids(step_data))
        results["steps"]["extract"] = {
            "status": extract.get("status"),
            "run_id": extract.get("run_id"),
            "run_ids": _extract_run_ids(step_data),
            "url_count": extract.get("url_count", 0),
            "record_count": len(records),
            "records": records,
        }

    for key in ("enrich", "compare", "monitor", "audit"):
        if key in step_data:
            results["steps"][key] = step_data[key]

    return results


async def _auto_advance(
    session: AsyncSession,
    playground: PlaygroundSession,
) -> None:
    step_data = dict(playground.step_data or {})

    if playground.state == "discovering":
        run_id = step_data.get("discover", {}).get("run_id")
        if run_id:
            run = await session.get(CrawlRun, run_id)
            if run and run.status in {s.value for s in TERMINAL_STATUSES}:
                products = await _extract_discovered_products(session, run_id)
                products = _merge_seed_detail_products(step_data, products)
                step_data["discover"] = {
                    **step_data.get("discover", {}),
                    "status": "completed",
                    "products": products[:MAX_PRODUCTS],
                    "total_found": len(products),
                }
                playground.state = "discovered"
                playground.step_data = step_data

    elif playground.state == "extracting":
        extract_info = step_data.get("extract", {}) or {}
        extract_runs = await _resolve_extract_runs(
            session,
            playground=playground,
            step_data=step_data,
        )
        resolved_run_ids = [int(run.id) for run in extract_runs]
        if resolved_run_ids:
            step_data["extract"] = {
                **extract_info,
                "run_id": resolved_run_ids[0],
                "run_ids": resolved_run_ids,
            }
            extract_info = step_data["extract"]
        expected_run_count = _expected_extract_run_count(step_data)
        if resolved_run_ids and len(resolved_run_ids) >= expected_run_count:
            terminal = {s.value for s in TERMINAL_STATUSES}
            statuses = [str(run.status) for run in extract_runs]
            if all(status in terminal for status in statuses):
                step_data["extract"] = {
                    **extract_info,
                    "status": "completed",
                }
                playground.state = "extracted"
                playground.step_data = step_data

    elif playground.state == "running_pipeline":
        mutated = False
        for key, refresher in (
            ("enrich", _refresh_enrich_status),
            ("compare", _refresh_compare_status),
            ("audit", _refresh_audit_status),
        ):
            info = step_data.get(key)
            if not info or not isinstance(info, dict):
                continue
            updated = await refresher(session, info)
            if updated is not None and updated != info:
                step_data[key] = updated
                mutated = True

        all_done = True
        for key in ("enrich", "compare", "audit"):
            info = step_data.get(key, {})
            if isinstance(info, dict) and info.get("status") == "running":
                all_done = False
                break
        if all_done:
            playground.state = "complete"
            mutated = True
        if mutated:
            playground.step_data = step_data

    if playground.state != "running_pipeline":
        audit_info = step_data.get("audit")
        if isinstance(audit_info, dict) and audit_info.get("status") == "running":
            updated = await _refresh_audit_status(session, audit_info)
            if updated is not None and updated != audit_info:
                step_data["audit"] = updated
                playground.step_data = step_data


async def _refresh_enrich_status(
    session: AsyncSession,
    info: dict[str, Any],
) -> dict[str, Any] | None:
    job_id = info.get("job_id")
    if not isinstance(job_id, int):
        return None
    from app.models.data_enrichment import DataEnrichmentJob

    job = await session.get(DataEnrichmentJob, job_id)
    if job is None:
        return None
    status = str(job.status or "").strip().lower()
    if status in _ENRICH_TERMINAL_STATUSES:
        return {**info, "status": status}
    return None


async def _refresh_compare_status(
    session: AsyncSession,
    info: dict[str, Any],
) -> dict[str, Any] | None:
    job_id = info.get("job_id")
    if not isinstance(job_id, int):
        return None
    from app.models.product_intelligence import ProductIntelligenceJob

    job = await session.get(ProductIntelligenceJob, job_id)
    if job is None:
        return None
    status = str(job.status or "").strip().lower()
    if status in _PI_TERMINAL_STATUSES:
        return {**info, "status": status}
    return None


async def _refresh_audit_status(
    session: AsyncSession,
    info: dict[str, Any],
) -> dict[str, Any] | None:
    job_id = info.get("job_id")
    if not isinstance(job_id, int):
        return None
    from app.models.ucp_audit import UCPAuditJob

    job = await session.get(UCPAuditJob, job_id)
    if job is None:
        return None
    status = str(job.status or "").strip().lower()
    if status in _AUDIT_TERMINAL_STATUSES:
        return {**info, "status": status}
    return None


async def _extract_discovered_products(
    session: AsyncSession,
    run_id: int,
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run_id)
        .limit(MAX_PRODUCTS)
    )
    products = []
    for record in rows.all():
        data = record.data or {}
        product_url = (
            data.get("url")
            or data.get("product_url")
            or data.get("detail_url")
            or data.get("canonical_url")
            or record.source_url
        )
        if product_url:
            products.append({
                "url": str(product_url),
                "title": str(data.get("title") or ""),
                "brand": str(data.get("brand") or ""),
                "price": str(data.get("price") or ""),
                "image": str(data.get("image") or data.get("image_url") or ""),
            })
    return products


async def _launch_extract_runs(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    user: User,
    urls: list[str],
    skipped_discover: bool = False,
) -> list[int]:
    run_ids: list[int] = []
    for product_url in urls:
        run = await create_crawl_run_from_payload(
            session,
            user.id,
            {
                "run_type": "crawl",
                "url": product_url,
                "surface": _detail_surface_for_url(product_url),
                "settings": {"playground_session_id": playground.id},
            },
        )
        run_ids.append(run.id)

    playground.state = "extracting"
    step_data = dict(playground.step_data or {})
    step_data["selected_urls"] = list(urls)
    step_data["extract"] = {
        "run_id": run_ids[0],
        "run_ids": run_ids,
        "status": "running",
        "url_count": len(urls),
        "skipped_discover": skipped_discover,
    }
    playground.step_data = step_data
    await session.flush()
    return run_ids


def _partition_playground_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    detail_urls: list[str] = []
    discover_urls: list[str] = []
    for url in urls:
        if _classify_input_url(url) == "detail":
            detail_urls.append(url)
        else:
            discover_urls.append(url)
    return detail_urls, discover_urls


def _validate_http_urls(urls: list[str]) -> list[str]:
    valid: list[str] = []
    invalid: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            invalid.append(url)
            continue
        valid.append(url)
    if invalid:
        raise ValueError(f"Invalid URL(s): {', '.join(invalid)}")
    return valid


def _normalize_input_urls(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_value in values:
        for item in str(raw_value or "").splitlines():
            candidate = item.strip()
            if not candidate:
                continue
            if not candidate.startswith(("http://", "https://")):
                candidate = f"https://{candidate}"
            normalized.append(candidate)
    return list(dict.fromkeys(_validate_http_urls(normalized)))


def _session_input_urls(playground: PlaygroundSession) -> list[str]:
    step_data = dict(playground.step_data or {})
    input_urls = step_data.get("input_urls")
    if isinstance(input_urls, list):
        normalized = [
            item.strip()
            for item in input_urls
            if isinstance(item, str) and item.strip()
        ]
        if normalized:
            return normalized
    return [playground.input_url]


def _safe_category_limit(value: object) -> int:
    try:
        candidate = int(value) if isinstance(value, (int, float, str)) else PLAYGROUND_CATEGORY_DEFAULT_LIMIT
    except (TypeError, ValueError):
        candidate = PLAYGROUND_CATEGORY_DEFAULT_LIMIT
    return max(1, min(candidate, PLAYGROUND_CATEGORY_MAX_LIMIT))


def _session_category_limit(playground: PlaygroundSession) -> int:
    return _safe_category_limit(
        dict(playground.step_data or {}).get(
            "category_limit",
            PLAYGROUND_CATEGORY_DEFAULT_LIMIT,
        )
    )


def _merge_seed_detail_products(
    step_data: dict[str, Any],
    discovered_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed_url in step_data.get("seed_detail_urls", []) or []:
        normalized = str(seed_url or "").strip()
        if not normalized or normalized in seen:
            continue
        merged.append({"url": normalized, "title": "", "brand": "", "price": "", "image": ""})
        seen.add(normalized)
    for product in discovered_products:
        normalized = str(product.get("url") or "").strip()
        if not normalized or normalized in seen:
            continue
        merged.append(product)
        seen.add(normalized)
    return merged


def _extract_run_ids(step_data: dict[str, Any]) -> list[int]:
    extract = step_data.get("extract", {}) or {}
    raw_run_ids = extract.get("run_ids")
    if isinstance(raw_run_ids, list):
        run_ids = [
            run_id
            for run_id in raw_run_ids
            if isinstance(run_id, int) and run_id > 0
        ]
        if run_ids:
            return run_ids
    run_id = extract.get("run_id")
    if isinstance(run_id, int) and run_id > 0:
        return [run_id]
    return []


async def _extract_record_ids(
    session: AsyncSession,
    run_ids: list[int],
) -> list[int]:
    if not run_ids:
        return []
    rows = await session.scalars(
        select(CrawlRecord.id)
        .where(CrawlRecord.run_id.in_(run_ids))
        .order_by(CrawlRecord.run_id.asc(), CrawlRecord.id.asc())
    )
    return [int(record_id) for record_id in rows.all() if record_id is not None]


async def _extract_records(
    session: AsyncSession,
    run_ids: list[int],
) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    rows = await session.scalars(
        select(CrawlRecord)
        .where(CrawlRecord.run_id.in_(run_ids))
        .order_by(CrawlRecord.run_id.asc(), CrawlRecord.id.asc())
    )
    records: list[dict[str, Any]] = []
    for record in rows.all():
        records.append(
            {
                "id": int(record.id),
                "run_id": int(record.run_id),
                "source_url": str(record.source_url),
                "data": dict(record.data or {}),
            }
        )
    return records


def _extract_selected_urls(step_data: dict[str, Any]) -> list[str]:
    selected_urls = step_data.get("selected_urls")
    if not isinstance(selected_urls, list):
        return []
    return [
        url.strip()
        for url in selected_urls
        if isinstance(url, str) and url.strip()
    ]


def _expected_extract_run_count(step_data: dict[str, Any]) -> int:
    extract = step_data.get("extract", {}) or {}
    url_count = extract.get("url_count")
    expected = max(
        len(_extract_selected_urls(step_data)),
        url_count if isinstance(url_count, int) and url_count > 0 else 0,
    )
    if expected > 0:
        return expected
    run_ids = _extract_run_ids(step_data)
    return len(run_ids)


async def _resolve_extract_runs(
    session: AsyncSession,
    *,
    playground: PlaygroundSession,
    step_data: dict[str, Any],
) -> list[CrawlRun]:
    resolved: dict[int, CrawlRun] = {}
    run_ids = _extract_run_ids(step_data)
    if run_ids:
        rows = await session.scalars(select(CrawlRun).where(CrawlRun.id.in_(run_ids)))
        run_by_id = {int(run.id): run for run in rows.all()}
        for run_id in run_ids:
            run = run_by_id.get(run_id)
            if run is None:
                continue
            resolved[int(run.id)] = run

    selected_urls = _extract_selected_urls(step_data)
    if selected_urls:
        rows = await session.scalars(
            select(CrawlRun)
            .where(
                CrawlRun.user_id == playground.user_id,
                CrawlRun.run_type == "crawl",
                CrawlRun.url.in_(selected_urls),
                CrawlRun.created_at >= playground.created_at,
            )
            .order_by(CrawlRun.id.asc())
        )
        for run in rows.all():
            settings = run.settings if isinstance(run.settings, dict) else {}
            if settings.get("playground_session_id") != playground.id:
                continue
            resolved.setdefault(int(run.id), run)

    return [resolved[run_id] for run_id in sorted(resolved)]


def _require_state(playground: PlaygroundSession, expected: str) -> None:
    if playground.state != expected:
        raise ValueError(
            f"Session is in state '{playground.state}', expected '{expected}'"
        )
