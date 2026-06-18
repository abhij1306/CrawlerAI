from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.services.acquisition.host_protection_memory import HostProtectionPolicy

FetchEventHandler = Callable[[str, str], Awaitable[None] | None]


@dataclass(slots=True)
class FetchRuntimeContext:
    url: str
    resolved_timeout: float
    deadline_monotonic: float
    run_id: int | None
    surface: str | None
    traversal_mode: str | None
    max_pages: int
    max_scrolls: int
    max_records: int | None
    on_event: FetchEventHandler | None
    browser_reason: str | None
    requested_fields: list[str]
    listing_recovery_mode: str | None
    proxies: list[str | None]
    proxy_profile: dict[str, object]
    traversal_required: bool
    fetch_mode: str
    runtime_policy: dict[str, object]
    capture_screenshot: bool = False
    forced_browser_engine: str | None = None
    host_memory_ttl_seconds: int = 0
    prefer_browser: bool = False
    prefer_curl_handoff: bool = False
    handoff_cookie_engine: str | None = None
    locality_profile: dict[str, object] = field(default_factory=dict)
    host_policy: HostProtectionPolicy | None = None
    last_browser_attempt_diagnostics: dict[str, object] = field(default_factory=dict)
    browser_first_failed: bool = False
    last_error: Exception | None = None


@dataclass(slots=True)
class FetchPageCall:
    url: str
    run_id: int | None = None
    timeout_seconds: float | None = None
    proxy_list: list[str] | None = None
    proxy_profile: dict[str, object] | None = None
    locality_profile: dict[str, object] | None = None
    fetch_mode: str = "auto"
    prefer_browser: bool = False
    browser_reason: str | None = None
    surface: str | None = None
    traversal_mode: str | None = None
    requested_fields: list[str] | None = None
    listing_recovery_mode: str | None = None
    capture_screenshot: bool = False
    host_memory_ttl_seconds: int | None = None
    prefer_curl_handoff: bool = False
    handoff_cookie_engine: str | None = None
    forced_browser_engine: str | None = None
    max_pages: int = 1
    max_scrolls: int = 1
    max_records: int | None = None
    on_event: FetchEventHandler | None = None
