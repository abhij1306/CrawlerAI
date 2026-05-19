# FastAPI application factory and route registration.
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from types import MappingProxyType

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.auth import router as auth_router
from app.api.crawl_domain import router as crawl_domain_router
from app.api.crawls import router as crawls_router
from app.api.data_enrichment import router as data_enrichment_router
from app.api.dashboard import router as dashboard_router
from app.api.jobs import router as jobs_router
from app.api.llm import router as llm_router
from app.api.monitors import router as monitors_router
from app.api.notifications import router as notifications_router
from app.api.orchestration import router as orchestration_router
from app.api.product_intelligence import router as product_intelligence_router
from app.api.records import router as records_router
from app.api.review import router as review_router
from app.api.selectors import router as selectors_router
from app.api.users import router as users_router
from app.api.ucp_audit import router as ucp_audit_router
from app.core.config import get_frontend_origins, settings
from app.core.dependencies import shutdown_run_dispatchers
from app.core.metrics import (
    check_browser_pool,
    check_database,
    check_redis,
    render_prometheus_metrics,
)
from app.core.redis import close_redis
from app.core.database import SessionLocal, dispose_engine
from app.core.telemetry import (
    configure_logging,
    generate_correlation_id,
    install_asyncio_exception_filter,
    reset_correlation_id,
    set_correlation_id,
)
from app.services.acquisition import (
    close_shared_http_client,
    shutdown_browser_runtime,
    validate_cookie_policy_config,
)
from app.services.auth_service import bootstrap_admin_user
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl.service import recover_stale_local_runs
from app.services.llm.provider_client import close_llm_provider_clients
from app.services.config.monitor_settings import (
    SCHEDULER_DRIVER_DEV,
    SCHEDULER_POLL_INTERVAL_SECONDS,
)
from app.services.monitor_async_loop import AsyncSchedulerLoop
from app.services.monitor_change_detection import ensure_monitor_change_detection_registered
from app.services.monitor_scheduler_service import MonitorSchedulerService

logger = logging.getLogger("app")


@dataclass
class CrawlerAppState:
    rate_limit_buckets: OrderedDict[str, deque[float]] = field(
        default_factory=OrderedDict
    )
    rate_limit_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    monitor_scheduler_loop: AsyncSchedulerLoop | None = None
    trusted_proxy_cache_key: tuple[str, ...] = ()
    trusted_proxy_cache_set: frozenset[str] = frozenset()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    configure_logging()
    try:
        install_asyncio_exception_filter()
    except RuntimeError:
        logger.debug("Asyncio exception filter not installed; no running loop")
    validate_cookie_policy_config()
    async with SessionLocal() as session:
        await bootstrap_admin_user(session)
        recovered = await recover_stale_local_runs(session)
        if recovered:
            logger.warning(
                "Recovered %s stale local crawl run(s) after backend restart",
                recovered,
            )
    ensure_monitor_change_detection_registered()
    crawler_state = _crawler_app_state(fastapi_app)
    if settings.scheduler_driver == SCHEDULER_DRIVER_DEV:
        scheduler_loop = AsyncSchedulerLoop(
            MonitorSchedulerService(),
            SCHEDULER_POLL_INTERVAL_SECONDS,
        )
        try:
            scheduler_loop.start_nowait()
        except Exception:
            await scheduler_loop.stop()
            raise
        crawler_state.monitor_scheduler_loop = scheduler_loop
    try:
        yield
    finally:
        if crawler_state.monitor_scheduler_loop is not None:
            await crawler_state.monitor_scheduler_loop.stop()
            crawler_state.monitor_scheduler_loop = None
        await shutdown_run_dispatchers()
        await shutdown_browser_runtime()
        await close_shared_http_client()
        await close_llm_provider_clients()
        await close_redis()
        await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.state.crawler = CrawlerAppState()
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _crawler_app_state(fastapi_app: FastAPI | None = None) -> CrawlerAppState:
    target = fastapi_app or app
    state = getattr(target.state, "crawler", None)
    if not isinstance(state, CrawlerAppState):
        state = CrawlerAppState()
        target.state.crawler = state
    return state


def _sanitize_header_value(value: str) -> str:
    return value.replace("\r", "").replace("\n", "")


_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _sanitize_header_name(value: str) -> str:
    text = str(value or "")
    sanitized = _sanitize_header_value(text).strip()
    if sanitized != text.strip():
        return "X-Request-ID"
    if sanitized and _HEADER_NAME_RE.fullmatch(sanitized):
        return sanitized
    return "X-Request-ID"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next) -> Response:
    if not crawler_runtime_settings.api_rate_limit_enabled:
        return await call_next(request)
    if _rate_limit_exempt_path(request.url.path):
        return await call_next(request)

    allowed, retry_after = await _consume_rate_limit(
        _client_rate_limit_key(request),
        state=_crawler_app_state(request.app),
    )
    if not allowed:
        return JSONResponse(
            {"detail": "Rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


def _rate_limit_exempt_path(path: str) -> bool:
    return (
        path == "/health"
        or path.startswith("/health/")
        or path.startswith("/api/metrics")
    )


def _client_rate_limit_key(request: Request) -> str:
    peer_host = request.client.host if request.client and request.client.host else ""
    forwarded_for = (
        request.headers.get("x-forwarded-for") if _is_trusted_proxy(peer_host) else None
    )
    if forwarded_for:
        first = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first:
            return first
    if peer_host:
        return peer_host
    return "unknown"


sanitize_header_value = _sanitize_header_value
sanitize_header_name = _sanitize_header_name
client_rate_limit_key = _client_rate_limit_key
RATE_LIMIT_BUCKETS = MappingProxyType(_crawler_app_state().rate_limit_buckets)
def rate_limit_buckets_snapshot() -> OrderedDict[str, deque[float]]:
    buckets = _crawler_app_state().rate_limit_buckets
    return OrderedDict((key, deque(value)) for key, value in buckets.items())


def clear_rate_limit_buckets_for_testing() -> None:
    _crawler_app_state().rate_limit_buckets.clear()


def restore_rate_limit_buckets_for_testing(
    buckets: OrderedDict[str, deque[float]],
) -> None:
    rate_limit_buckets = _crawler_app_state().rate_limit_buckets
    rate_limit_buckets.clear()
    rate_limit_buckets.update(
        OrderedDict((key, deque(value)) for key, value in buckets.items())
    )


def _trusted_proxy_set() -> frozenset[str]:
    crawler_state = _crawler_app_state()
    values = tuple(
        normalized
        for normalized in (
            str(value).strip()
            for value in crawler_runtime_settings.api_rate_limit_trusted_proxies
        )
        if normalized
    )
    if values != crawler_state.trusted_proxy_cache_key:
        crawler_state.trusted_proxy_cache_key = values
        crawler_state.trusted_proxy_cache_set = frozenset(values)
    return crawler_state.trusted_proxy_cache_set


def _is_trusted_proxy(proxy_ip: str) -> bool:
    return proxy_ip in _trusted_proxy_set()


async def _consume_rate_limit(
    identifier: str,
    *,
    state: CrawlerAppState | None = None,
) -> tuple[bool, int]:
    crawler_state = state or _crawler_app_state()
    now = monotonic()
    window_seconds = float(crawler_runtime_settings.api_rate_limit_window_seconds)
    max_requests = int(crawler_runtime_settings.api_rate_limit_max_requests)
    async with crawler_state.rate_limit_lock:
        bucket = crawler_state.rate_limit_buckets.get(identifier)
        if bucket is None:
            bucket = deque()
            crawler_state.rate_limit_buckets[identifier] = bucket
        else:
            crawler_state.rate_limit_buckets.move_to_end(identifier)

        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= max_requests:
            retry_after = max(1, int(bucket[0] + window_seconds - now))
            return False, retry_after

        bucket.append(now)
        while len(crawler_state.rate_limit_buckets) > int(
            crawler_runtime_settings.api_rate_limit_max_clients
        ):
            crawler_state.rate_limit_buckets.popitem(last=False)
        return True, 0


@app.middleware("http")
async def correlation_middleware(request: Request, call_next) -> Response:
    request_id_header = _sanitize_header_name(settings.request_id_header)
    raw_correlation_id = request.headers.get(request_id_header)
    correlation_id = (
        _sanitize_header_value(raw_correlation_id)
        if raw_correlation_id is not None
        else generate_correlation_id()
    )
    if not correlation_id:
        correlation_id = generate_correlation_id()
    token = set_correlation_id(correlation_id)
    try:
        response = await call_next(request)
    finally:
        reset_correlation_id(token)
    response.headers[request_id_header] = correlation_id
    return response


async def _health_checks() -> dict[str, bool]:
    return {
        "database": await check_database(),
        "redis": await check_redis(),
        "browser_pool": check_browser_pool(),
    }


def _health_payload(checks: dict[str, bool]) -> dict[str, object]:
    status = "healthy" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    checks = await _health_checks()
    payload = _health_payload(checks)
    status_code = 200 if all(checks.values()) else 503
    return JSONResponse(payload, status_code=status_code)


@app.get("/api/health")
async def health() -> dict[str, object]:
    return _health_payload(await _health_checks())


@app.get("/api/metrics")
async def metrics() -> Response:
    payload, content_type = await render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)


# crawl_domain_router and crawls_router share "/api/crawls". Dynamic run routes
# use the int path converter, so non-run domain-memory routes are not shadowed.
for router in [
    auth_router,
    users_router,
    dashboard_router,
    crawl_domain_router,
    crawls_router,
    data_enrichment_router,
    records_router,
    jobs_router,
    review_router,
    selectors_router,
    llm_router,
    product_intelligence_router,
    orchestration_router,
    monitors_router,
    notifications_router,
    ucp_audit_router,
]:
    app.include_router(router)
