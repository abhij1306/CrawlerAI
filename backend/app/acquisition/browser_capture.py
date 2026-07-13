from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from patchright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from app.acquisition.browser_background_tasks import (
    register_eviction_cleanup_task,
)
from app.acquisition.runtime import NetworkPayloadReadResult
from app.core.config.network_capture import (
    ENDPOINT_TYPE_PATH_TOKENS,
    GRAPHQL_PATH_TOKENS,
    HIGH_VALUE_NETWORK_ENDPOINT_TYPES,
    HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER,
    NETWORK_PAYLOAD_NOISE_URL_RE,
    NETWORK_EVIDENCE_SAFE_REQUEST_HEADERS,
    NETWORK_EVIDENCE_SAFE_RESPONSE_HEADERS,
    NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS,
    NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES,
    NETWORK_PAYLOAD_URL_HINTS,
    NETWORK_REPLAY_REQUEST_ALLOWED_KEYS,
    NETWORK_REPLAY_REQUEST_MAX_BYTES,
    NETWORK_REPLAY_REQUEST_SENSITIVE_KEY_TOKENS,
)
from app.core.config.runtime_settings import (
    browser_capture_max_network_payload_bytes,
    browser_capture_max_network_payloads,
    browser_capture_queue_size,
    browser_capture_total_network_payload_bytes,
    browser_capture_workers,
    crawler_runtime_settings,
)
from app.acquisition.platform_policy import classify_network_endpoint_family

logger = logging.getLogger(__name__)

PLAYWRIGHT_RECOVERABLE_ERRORS: tuple[type[Exception], ...] = (
    PlaywrightError,
    PlaywrightTimeoutError,
)
_RECOVERABLE_RUNTIME_ERROR_PATTERNS = (
    "event loop is closed",
    "browser has been closed",
    "target closed",
    "connection closed",
    "session closed",
)


def is_recoverable_playwright_error(exc: Exception) -> bool:
    if isinstance(exc, (*PLAYWRIGHT_RECOVERABLE_ERRORS, ConnectionResetError, OSError)):
        return True
    return isinstance(exc, RuntimeError) and any(
        pattern in str(exc).lower() for pattern in _RECOVERABLE_RUNTIME_ERROR_PATTERNS
    )


@dataclass(slots=True)
class BrowserNetworkCaptureSummary:
    payloads: list[dict[str, object]]
    network_payload_count: int
    captured_network_payload_bytes: int
    malformed_network_payloads: int
    network_payload_read_failures: int
    network_payload_read_timeouts: int
    closed_network_payloads: int
    skipped_oversized_network_payloads: int
    dropped_payload_events: int


class BrowserNetworkCapture:
    def __init__(
        self,
        *,
        surface: str,
        should_capture_payload: Any | None = None,
        classify_endpoint: Any | None = None,
        read_payload_body: Any | None = None,
    ) -> None:
        self._surface = surface
        self._should_capture_payload = (
            should_capture_payload or should_capture_network_payload
        )
        self._classify_endpoint = classify_endpoint or classify_network_endpoint
        self._read_payload_body = read_payload_body or read_network_payload_body
        self._lock = asyncio.Lock()
        self._payloads: list[dict[str, object]] = []
        self._workers: set[asyncio.Task[None]] = set()
        self._closed = False
        self._closing = False
        self._listener_attached = False
        self._summary: BrowserNetworkCaptureSummary | None = None
        self._malformed_payloads = 0
        self._payload_read_failures = 0
        self._payload_closed_failures = 0
        self._oversized_payloads = 0
        self._payload_read_timeouts = 0
        self._captured_bytes = 0
        self._pending_payloads = 0
        self._reserved_bytes = 0
        self._dropped_payload_events = 0
        self._max_payloads = max(1, browser_capture_max_network_payloads())
        self._max_payload_bytes = max(1, browser_capture_max_network_payload_bytes())
        self._total_payload_bytes = max(
            1,
            browser_capture_total_network_payload_bytes(),
        )
        self._queue: asyncio.Queue[Any | None] = asyncio.Queue(
            maxsize=max(1, browser_capture_queue_size())
        )

    def attach(self, page: Any) -> None:
        if (
            self._listener_attached
            or self._closing
            or self._closed
            or self._summary is not None
            or self._workers
        ):
            return
        self._workers = {
            asyncio.create_task(self._capture_worker())
            for _ in range(
                max(
                    1,
                    min(
                        browser_capture_workers(),
                        self._max_payloads,
                        self._queue.maxsize,
                    ),
                )
            )
        }
        page.on("response", self._schedule_capture)
        self._listener_attached = True

    async def close(self, page: Any) -> BrowserNetworkCaptureSummary:
        if self._summary is not None:
            return self._summary
        remove_listener = getattr(page, "remove_listener", None)
        if callable(remove_listener):
            try:
                remove_listener("response", self._schedule_capture)
            except Exception as exc:
                if is_response_closed_error(exc):
                    logger.debug(
                        "Browser response listener detach skipped (page already closed)"
                    )
                else:
                    logger.warning(
                        "Failed to detach browser response listener: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
        self._listener_attached = False
        if self._workers:
            workers = set(self._workers)
            await asyncio.sleep(0)
            self._closing = True
            queue_empty = getattr(self._queue, "empty", None)
            active_payload_reads = self._pending_payloads > 0 or (
                callable(queue_empty) and not queue_empty()
            )
            join_timeout_seconds = _queue_join_timeout_seconds(
                active_payload_reads=active_payload_reads
            )
            try:
                for _worker in workers:
                    await asyncio.wait_for(
                        self._queue.put(None),
                        timeout=join_timeout_seconds,
                    )
                await asyncio.wait_for(
                    self._queue.join(),
                    timeout=join_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Browser capture queue join timed out after %ss; "
                    "cancelling workers and draining queue",
                    join_timeout_seconds,
                )
                for worker in workers:
                    worker.cancel()
                queue_empty = getattr(self._queue, "empty", None)
                queue_get_nowait = getattr(self._queue, "get_nowait", None)
                queue_task_done = getattr(self._queue, "task_done", None)
                while (
                    callable(queue_empty)
                    and callable(queue_get_nowait)
                    and not queue_empty()
                ):
                    try:
                        queue_get_nowait()
                        if callable(queue_task_done):
                            queue_task_done()
                    except asyncio.QueueEmpty:
                        break
            else:
                for worker in workers:
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            self._workers.clear()
        self._closed = True
        async with self._lock:
            self._summary = BrowserNetworkCaptureSummary(
                payloads=list(self._payloads[: self._max_payloads]),
                network_payload_count=len(self._payloads),
                captured_network_payload_bytes=self._captured_bytes,
                malformed_network_payloads=self._malformed_payloads,
                network_payload_read_failures=self._payload_read_failures,
                network_payload_read_timeouts=self._payload_read_timeouts,
                closed_network_payloads=self._payload_closed_failures,
                skipped_oversized_network_payloads=self._oversized_payloads,
                dropped_payload_events=self._dropped_payload_events,
            )
        return self._summary

    def _schedule_capture(self, response: Any) -> None:
        if self._closing:
            return
        try:
            self._queue.put_nowait(response)
        except asyncio.QueueFull:
            self._dropped_payload_events += 1

    async def _capture_worker(self) -> None:
        while True:
            response = await self._queue.get()
            try:
                if response is None:
                    return
                await self._capture_response(response)
            except Exception:
                logger.debug(
                    "Failed to capture browser network payload",
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    async def _capture_response(self, response: Any) -> None:
        content_type = str(response.headers.get("content-type", "") or "").lower()
        endpoint_info = self._classify_endpoint(
            response_url=response.url,
            surface=self._surface,
        )
        reserved_bytes = await self._reserve_capture_budget(
            response=response,
            content_type=content_type,
            endpoint_info=endpoint_info,
        )
        if reserved_bytes is None:
            return
        try:
            body_result = await self._read_payload_body(
                response,
                surface=self._surface,
                endpoint_info=endpoint_info,
            )
        except Exception:
            await self._release_capture_budget(reserved_bytes)
            raise
        if body_result.outcome == "response_closed":
            await self._release_capture_budget(reserved_bytes)
            async with self._lock:
                self._payload_closed_failures += 1
            return
        if body_result.outcome == "too_large":
            await self._release_capture_budget(reserved_bytes)
            async with self._lock:
                self._oversized_payloads += 1
            return
        if body_result.outcome == "timeout":
            await self._release_capture_budget(reserved_bytes)
            async with self._lock:
                self._payload_read_timeouts += 1
            return
        if body_result.outcome == "read_error":
            await self._release_capture_budget(reserved_bytes)
            async with self._lock:
                self._payload_read_failures += 1
            return
        body_bytes = body_result.body
        if body_bytes is None:
            await self._release_capture_budget(reserved_bytes)
            return
        payload = _decode_network_payload(
            body_bytes,
            content_type=content_type,
        )
        if payload is None:
            await self._release_capture_budget(reserved_bytes)
            async with self._lock:
                self._malformed_payloads += 1
            return
        async with self._lock:
            self._pending_payloads = max(0, self._pending_payloads - 1)
            self._reserved_bytes = max(0, self._reserved_bytes - reserved_bytes)
            if not self._should_capture_payload(
                url=response.url,
                content_type=content_type,
                headers=response.headers,
                captured_count=len(self._payloads),
                captured_bytes=self._captured_bytes,
                surface=self._surface,
                endpoint_info=endpoint_info,
            ):
                return
            if self._captured_bytes + len(body_bytes) > self._total_payload_bytes:
                self._oversized_payloads += 1
                return
            self._payloads.append(
                {
                    "url": response.url,
                    "method": getattr(response.request, "method", "GET"),
                    "status": int(getattr(response, "status", 0) or 0),
                    "content_type": content_type,
                    "endpoint_type": endpoint_info["type"],
                    "endpoint_family": endpoint_info["family"],
                    "request_headers": _safe_headers(
                        getattr(response.request, "headers", {}),
                        allowed=NETWORK_EVIDENCE_SAFE_REQUEST_HEADERS,
                    ),
                    "response_headers": _safe_headers(
                        response.headers,
                        allowed=NETWORK_EVIDENCE_SAFE_RESPONSE_HEADERS,
                    ),
                    "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "resource_type": str(
                        getattr(response.request, "resource_type", "") or ""
                    ),
                    "frame_url": _request_frame_url(response.request),
                    "request_json": _safe_replay_request_json(
                        response.request,
                        endpoint_type=endpoint_info["type"],
                    ),
                    "body": payload,
                }
            )
            self._captured_bytes += len(body_bytes)

    async def _reserve_capture_budget(
        self,
        *,
        response: Any,
        content_type: str,
        endpoint_info: dict[str, str],
    ) -> int | None:
        reserved_bytes = (
            0
            if has_chunked_transfer_encoding(response.headers)
            else max(0, int(coerce_content_length(response.headers) or 0))
        )
        async with self._lock:
            if not self._should_capture_payload(
                url=response.url,
                content_type=content_type,
                headers=response.headers,
                captured_count=len(self._payloads) + self._pending_payloads,
                captured_bytes=self._captured_bytes + self._reserved_bytes,
                surface=self._surface,
                endpoint_info=endpoint_info,
            ):
                return None
            self._pending_payloads += 1
            self._reserved_bytes += reserved_bytes
            return reserved_bytes

    async def _release_capture_budget(self, reserved_bytes: int) -> None:
        async with self._lock:
            self._pending_payloads = max(0, self._pending_payloads - 1)
            self._reserved_bytes = max(0, self._reserved_bytes - reserved_bytes)


def _safe_headers(
    headers: dict[str, object] | Any,
    *,
    allowed: tuple[str, ...],
) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        return {}
    allowed_names = set(allowed)
    return {
        str(name).strip().lower(): str(value)
        for name, value in headers.items()
        if str(name).strip().lower() in allowed_names
    }


def _request_frame_url(request: Any) -> str:
    try:
        return str(getattr(getattr(request, "frame", None), "url", "") or "")
    except Exception:
        return ""


def _safe_replay_request_json(
    request: Any, *, endpoint_type: str
) -> dict[str, object] | None:
    """Keep a bounded non-sensitive JSON POST template for recipe learning."""
    if str(getattr(request, "method", "")).upper() != "POST":
        return None
    headers = getattr(request, "headers", {})
    content_type = str(
        headers.get("content-type", "") if isinstance(headers, Mapping) else ""
    ).casefold()
    if "json" not in content_type and endpoint_type != "graphql":
        return None
    raw = getattr(request, "post_data", None)
    raw = raw() if callable(raw) else raw
    if (
        not isinstance(raw, str)
        or len(raw.encode("utf-8")) > NETWORK_REPLAY_REQUEST_MAX_BYTES
    ):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    query = str(payload.get("query") or "")
    if "mutation" in query.casefold():
        return None
    if endpoint_type == "graphql" and (
        set(payload) - NETWORK_REPLAY_REQUEST_ALLOWED_KEYS
        or not (query or payload.get("operationName") or payload.get("extensions"))
    ):
        return None
    if _has_sensitive_request_key(payload):
        return None
    return dict(payload)


def _has_sensitive_request_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if any(
                token in normalized
                for token in NETWORK_REPLAY_REQUEST_SENSITIVE_KEY_TOKENS
            ):
                return True
            if _has_sensitive_request_key(item):
                return True
    elif isinstance(value, list):
        return any(_has_sensitive_request_key(item) for item in value)
    return False


def should_capture_network_payload(
    *,
    url: str,
    content_type: str,
    headers: dict[str, object] | Any,
    captured_count: int,
    captured_bytes: int = 0,
    surface: str = "",
    endpoint_info: dict[str, str] | None = None,
) -> bool:
    lowered_url = str(url or "").lower()
    if not _is_supported_network_payload_content_type(
        content_type=content_type,
        lowered_url=lowered_url,
    ):
        return False
    max_payloads = max(1, browser_capture_max_network_payloads())
    total_payload_bytes = max(
        1,
        browser_capture_total_network_payload_bytes(),
    )
    if captured_count >= max_payloads:
        return False
    if NETWORK_PAYLOAD_NOISE_URL_RE.search(lowered_url):
        return False
    payload_budget = _network_payload_byte_budget(
        url=url,
        surface=surface,
        endpoint_info=endpoint_info,
    )
    content_length = (
        None
        if has_chunked_transfer_encoding(headers)
        else coerce_content_length(headers)
    )
    if content_length is not None and content_length > payload_budget:
        return False
    if (
        content_length is not None
        and captured_bytes + content_length > total_payload_bytes
    ):
        return False
    if captured_bytes >= total_payload_bytes:
        return False
    return True


def _is_supported_network_payload_content_type(
    *,
    content_type: str,
    lowered_url: str,
) -> bool:
    normalized_content_type = str(content_type or "").strip().lower()
    if "json" in normalized_content_type:
        return True
    if any(
        token in normalized_content_type
        for token in NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS
    ):
        return True
    if any(token in lowered_url for token in NETWORK_PAYLOAD_URL_HINTS):
        return True
    return any(
        token in normalized_content_type
        for token in NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES
    )


def _decode_network_payload(
    body_bytes: bytes,
    *,
    content_type: str,
) -> object | None:
    text = body_bytes.decode("utf-8", errors="replace")
    normalized_content_type = str(content_type or "").strip().lower()
    if any(
        token in normalized_content_type
        for token in NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES
    ):
        return _decode_rsc_payload(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _repair_truncated_json_prefix(text)


def _repair_truncated_json_prefix(text: str) -> object | None:
    candidate = str(text or "").strip()
    if not candidate.startswith(("{", "[")):
        return None
    in_string = False
    escaped = False
    string_start = -1
    for index, char in enumerate(candidate):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            string_start = index
    if in_string and string_start >= 0:
        candidate = candidate[:string_start]
    for _attempt in range(24):
        candidate = candidate.rstrip().rstrip(",:")
        if not candidate:
            return None
        stack: list[str] = []
        in_string = False
        escaped = False
        valid = True
        for char in candidate:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                expected = "[" if char == "]" else "{"
                if not stack or stack.pop() != expected:
                    valid = False
                    break
        if valid and not in_string:
            repaired = candidate + "".join(
                "]" if opener == "[" else "}" for opener in reversed(stack)
            )
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        comma_index = candidate.rfind(",")
        if comma_index < 0:
            return None
        candidate = candidate[:comma_index]
    return None


def _decode_rsc_payload(text: str) -> object | None:
    decoder = json.JSONDecoder()
    payloads: list[object] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _decode_rsc_line(line, decoder=decoder)
        if parsed is not None:
            payloads.append(parsed)
    if not payloads:
        return None
    if len(payloads) == 1:
        return payloads[0]
    return payloads


def _decode_rsc_line(
    line: str,
    *,
    decoder: json.JSONDecoder,
) -> object | None:
    candidates = [line]
    colon_index = line.find(":")
    if colon_index >= 0:
        suffix = line[colon_index + 1 :].strip()
        if suffix:
            candidates.append(suffix)
    for candidate in candidates:
        start_index = next(
            (index for index, char in enumerate(candidate) if char in '[{"'),
            -1,
        )
        if start_index < 0:
            continue
        fragment = candidate[start_index:]
        try:
            parsed, _ = decoder.raw_decode(fragment)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def classify_network_endpoint(*, response_url: str, surface: str) -> dict[str, str]:
    lowered_url = str(response_url or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    family = classify_network_endpoint_family(response_url)

    endpoint_type = "generic_json"
    if any(token in lowered_url for token in GRAPHQL_PATH_TOKENS):
        endpoint_type = "graphql"
    else:
        surface_tokens = ENDPOINT_TYPE_PATH_TOKENS.get(normalized_surface, {})
        for etype, tokens in surface_tokens.items():
            if any(token in lowered_url for token in tokens):
                endpoint_type = etype
                break
    return {"type": endpoint_type, "family": family}


async def read_network_payload_body(
    response: Any,
    *,
    surface: str = "",
    endpoint_info: dict[str, str] | None = None,
) -> NetworkPayloadReadResult:
    payload_budget = _network_payload_byte_budget(
        url=str(getattr(response, "url", "") or ""),
        surface=surface,
        endpoint_info=endpoint_info,
    )
    try:
        body_task = asyncio.create_task(response.body())
        done, _pending = await asyncio.wait(
            {body_task},
            timeout=_payload_read_timeout_seconds(),
        )
        if not done:
            register_eviction_cleanup_task(body_task)
            return NetworkPayloadReadResult(body=None, outcome="timeout")
        body_bytes = body_task.result()
    except Exception as exc:
        if is_response_closed_error(exc):
            return NetworkPayloadReadResult(
                body=None,
                outcome="response_closed",
                error=f"{type(exc).__name__}: {exc}",
            )
        return NetworkPayloadReadResult(
            body=None,
            outcome="read_error",
            error=f"{type(exc).__name__}: {exc}",
        )
    if len(body_bytes) > payload_budget:
        return NetworkPayloadReadResult(body=None, outcome="too_large")
    return NetworkPayloadReadResult(body=body_bytes, outcome="read")


def coerce_content_length(headers: dict[str, object] | Any) -> int | None:
    if not headers:
        return None
    raw_value = headers.get("content-length")
    try:
        parsed = int(str(raw_value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def has_chunked_transfer_encoding(headers: dict[str, object] | Any) -> bool:
    if not headers:
        return False
    raw_value = headers.get("transfer-encoding")
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return False
    return any(token.strip() == "chunked" for token in normalized.split(","))


def _queue_join_timeout_seconds(*, active_payload_reads: bool = False) -> float:
    configured = max(
        0.1,
        float(crawler_runtime_settings.browser_capture_queue_join_timeout_ms) / 1000,
    )
    if not active_payload_reads:
        return configured
    return max(configured, _payload_read_timeout_seconds() + 0.5)


def _payload_read_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_capture_read_timeout_seconds),
    )


def is_response_closed_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    return (
        "targetclosed" in class_name
        or "target closed" in message
        or "page closed" in message
        or "browser has been closed" in message
    )


def _network_payload_byte_budget(
    *,
    url: str,
    surface: str,
    endpoint_info: dict[str, str] | None = None,
) -> int:
    resolved_endpoint = endpoint_info or classify_network_endpoint(
        response_url=url,
        surface=surface,
    )
    budget = max(1, browser_capture_max_network_payload_bytes())
    if resolved_endpoint.get("type") in HIGH_VALUE_NETWORK_ENDPOINT_TYPES:
        budget *= HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER
    return min(budget, max(1, browser_capture_total_network_payload_bytes()))


__all__ = [
    "BrowserNetworkCapture",
    "BrowserNetworkCaptureSummary",
    "classify_network_endpoint",
    "coerce_content_length",
    "has_chunked_transfer_encoding",
    "read_network_payload_body",
    "should_capture_network_payload",
]
