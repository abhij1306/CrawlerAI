# FastAPI application factory and route registration.
from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections import OrderedDict, deque
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.auth import router as auth_router
from app.api.api_keys import router as api_keys_router
from app.api.public.capabilities import router as public_capabilities_router
from app.api.public.domains import router as public_domains_router
from app.api.public.extract import router as public_extract_router
from app.api.crawl_domain import router as crawl_domain_router
from app.api.crawls import router as crawls_router
from app.api.data_enrichment import router as data_enrichment_router
from app.api.dashboard import router as dashboard_router
from app.api.jobs import router as jobs_router
from app.api.llm import router as llm_router
from app.api.monitors import router as monitors_router
from app.api.notifications import router as notifications_router
from app.api.observability import router as observability_router
from app.api.product_intelligence import router as product_intelligence_router
from app.api.playground import router as playground_router
from app.api.public_alerts import router as public_alerts_router
from app.api.records import router as records_router
from app.api.review import router as review_router
from app.api.selectors import router as selectors_router
from app.api.users import router as users_router
from app.api.ucp_audit import router as ucp_audit_router
from app.api.alerts import router as alerts_router
from app.core.config import get_frontend_origins, runtime_app_env, settings
from app.core.dependencies import get_db, shutdown_run_dispatchers
from app.core.metrics import (
    check_browser_pool,
    check_database,
    check_redis,
    render_prometheus_metrics,
)
from app.core.rate_limit import client_identifier_from_request, consume_sliding_window_limit
from app.core.redis import close_redis
from app.core.database import SessionLocal, dispose_engine
from app.core.public_auth import authenticate_public_api_key
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
from app.services.config.auth_security import (
    API_ALLOWED_CORS_METHODS,
    SECURITY_HEADER_CONTENT_TYPE_OPTIONS,
    SECURITY_HEADER_FRAME_OPTIONS,
    SECURITY_HEADER_HSTS,
    SECURITY_HEADER_PERMISSIONS_POLICY,
    SECURITY_HEADER_REFERRER_POLICY,
    cors_allowed_headers,
    path_requires_no_store,
    secure_transport_required,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.crawl.service import recover_stale_local_runs
from app.services.llm.provider_client import close_llm_provider_clients
from app.services.config.monitor_settings import (
    SCHEDULER_DRIVER_DEV,
    SCHEDULER_POLL_INTERVAL_SECONDS,
)
from app.api.public.common import PublicApiError, public_error_response
from app.api.public.rate_limit import consume_public_rate_limit, public_rate_scope
from app.services.config.public_api import (
    PUBLIC_API_ERROR_INVALID_API_KEY,
    PUBLIC_API_ERROR_RATE_LIMITED,
)
from app.services.monitor_async_loop import AsyncSchedulerLoop
from app.services.monitor_change_detection import ensure_monitor_change_detection_registered
from app.services.observability.run_audit import ensure_run_audit_registered
from app.services.monitor_scheduler_service import MonitorSchedulerService

logger = logging.getLogger("app")
_PUBLIC_API_PREFIX = "/api/v1"


@dataclass
class CrawlerAppState:
    rate_limit_buckets: OrderedDict[str, deque[float]] = field(
        default_factory=OrderedDict
    )
    rate_limit_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    auth_rate_limit_buckets: OrderedDict[str, deque[float]] = field(
        default_factory=OrderedDict
    )
    auth_rate_limit_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
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
    ensure_run_audit_registered()
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
    allow_methods=list(API_ALLOWED_CORS_METHODS),
    allow_headers=cors_allowed_headers(settings.request_id_header),
)


@app.middleware("http")
async def public_api_middleware(request: Request, call_next) -> Response:
    if not request.url.path.startswith(_PUBLIC_API_PREFIX):
        return await call_next(request)
    request.state.public_api_started_at = perf_counter()
    request.state.public_rate_limit_headers = {
        "X-RateLimit-Limit": "0",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": "0",
    }
    try:
        async with _public_auth_session(request) as session:
            principal = await authenticate_public_api_key(
                session,
                request.headers.get("authorization"),
                touch=True,
            )
    except HTTPException as exc:
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        return public_error_response(
            request,
            code=str(detail.get("code") or PUBLIC_API_ERROR_INVALID_API_KEY),
            message=str(detail.get("message") or exc.detail or "Invalid API key"),
            status_code=exc.status_code,
        )
    request.state.public_api_key_id = principal.api_key_id
    request.state.public_api_user_id = principal.user_id

    decision = await consume_public_rate_limit(
        _crawler_app_state(request.app).rate_limit_buckets,
        _crawler_app_state(request.app).rate_limit_lock,
        api_key_id=principal.api_key_id,
        scope=public_rate_scope(request.url.path),
    )
    request.state.public_rate_limit_headers = decision.headers()
    if not decision.allowed:
        return public_error_response(
            request,
            code=PUBLIC_API_ERROR_RATE_LIMITED,
            message="Rate limit exceeded.",
            status_code=429,
        )
    response = await call_next(request)
    for name, value in decision.headers().items():
        response.headers[name] = value
    return response


def _crawler_app_state(fastapi_app: FastAPI | None = None) -> CrawlerAppState:
    target = app if fastapi_app is None else fastapi_app
    state = getattr(target.state, "crawler", None)
    if not isinstance(state, CrawlerAppState):
        if fastapi_app is not None:
            raise RuntimeError(
                "FastAPI app state.crawler must be initialized with CrawlerAppState"
            )
        state = CrawlerAppState()
        target.state.crawler = state
    return state


@asynccontextmanager
async def _public_auth_session(request: Request):
    override = request.app.dependency_overrides.get(get_db)
    if override is None:
        async with SessionLocal() as session:
            yield session
        return
    value = override()
    if inspect.isawaitable(value):
        value = await value
    if inspect.isasyncgen(value):
        session = await anext(value)
        try:
            yield session
        finally:
            await value.aclose()
        return
    if inspect.isgenerator(value):
        session = next(value)
        try:
            yield session
        finally:
            value.close()
        return
    yield value


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
async def security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = SECURITY_HEADER_CONTENT_TYPE_OPTIONS
    response.headers["X-Frame-Options"] = SECURITY_HEADER_FRAME_OPTIONS
    response.headers["Referrer-Policy"] = SECURITY_HEADER_REFERRER_POLICY
    response.headers["Permissions-Policy"] = SECURITY_HEADER_PERMISSIONS_POLICY
    if path_requires_no_store(request.url.path):
        response.headers["Cache-Control"] = "no-store"
    if _should_emit_hsts(request):
        response.headers["Strict-Transport-Security"] = SECURITY_HEADER_HSTS
    return response


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
        or path.startswith(_PUBLIC_API_PREFIX)
    )


def _client_rate_limit_key(request: Request) -> str:
    return client_identifier_from_request(
        request,
        trusted_proxies=tuple(_trusted_proxy_set()),
    )


sanitize_header_value = _sanitize_header_value
sanitize_header_name = _sanitize_header_name
client_rate_limit_key = _client_rate_limit_key


class _RateLimitBucketsView(Mapping[str, deque[float]]):
    def __getitem__(self, key: str) -> deque[float]:
        return _crawler_app_state().rate_limit_buckets[key]

    def __iter__(self):
        return iter(_crawler_app_state().rate_limit_buckets)

    def __len__(self) -> int:
        return len(_crawler_app_state().rate_limit_buckets)


RATE_LIMIT_BUCKETS: Mapping[str, deque[float]] = _RateLimitBucketsView()


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
    return await consume_sliding_window_limit(
        crawler_state.rate_limit_buckets,
        crawler_state.rate_limit_lock,
        identifier=identifier,
        window_seconds=float(crawler_runtime_settings.api_rate_limit_window_seconds),
        max_requests=int(crawler_runtime_settings.api_rate_limit_max_requests),
        max_clients=int(crawler_runtime_settings.api_rate_limit_max_clients),
    )


def auth_rate_limit_buckets_snapshot() -> OrderedDict[str, deque[float]]:
    buckets = _crawler_app_state().auth_rate_limit_buckets
    return OrderedDict((key, deque(value)) for key, value in buckets.items())


def clear_auth_rate_limit_buckets_for_testing() -> None:
    _crawler_app_state().auth_rate_limit_buckets.clear()


def restore_auth_rate_limit_buckets_for_testing(
    buckets: OrderedDict[str, deque[float]],
) -> None:
    auth_rate_limit_buckets = _crawler_app_state().auth_rate_limit_buckets
    auth_rate_limit_buckets.clear()
    auth_rate_limit_buckets.update(
        OrderedDict((key, deque(value)) for key, value in buckets.items())
    )


def _request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    peer_host = request.client.host if request.client and request.client.host else ""
    if _is_trusted_proxy(peer_host):
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto.split(",", maxsplit=1)[0].strip().lower() == "https":
            return True
    return False


def _should_emit_hsts(request: Request) -> bool:
    return secure_transport_required(runtime_app_env()) and _request_is_https(request)


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


@app.exception_handler(PublicApiError)
async def public_api_error_handler(request: Request, exc: PublicApiError) -> JSONResponse:
    if request.url.path.startswith(_PUBLIC_API_PREFIX):
        return public_error_response(
            request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def public_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if not request.url.path.startswith(_PUBLIC_API_PREFIX):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
    if detail.get("status") == "error":
        return JSONResponse(detail, status_code=exc.status_code, headers=exc.headers)
    nested_raw = detail.get("error")
    nested: dict[str, Any] = nested_raw if isinstance(nested_raw, dict) else {}
    return public_error_response(
        request,
        code=str(detail.get("code") or nested.get("code") or PUBLIC_API_ERROR_INVALID_API_KEY),
        message=str(detail.get("message") or nested.get("message") or exc.detail or "Request failed"),
        status_code=exc.status_code,
        details=detail.get("details") if isinstance(detail.get("details"), dict) else {},
        headers=dict(exc.headers) if exc.headers else None,
    )


@app.exception_handler(RequestValidationError)
async def public_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if not request.url.path.startswith(_PUBLIC_API_PREFIX):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return public_error_response(
        request,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        status_code=422,
        details={"errors": exc.errors()},
    )


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
    api_keys_router,
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
    playground_router,
    monitors_router,
    alerts_router,
    public_extract_router,
    public_domains_router,
    public_capabilities_router,
    public_alerts_router,
    notifications_router,
    ucp_audit_router,
    observability_router,
]:
    app.include_router(router)
