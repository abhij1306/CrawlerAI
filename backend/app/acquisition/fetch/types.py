from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.acquisition.contracts import AttemptResult, AttemptSpec
from app.acquisition.events import AcquisitionEventHandler
from app.acquisition.host_protection_memory import HostProtectionPolicy
from app.acquisition.runtime import PageFetchResult

FetchEventHandler = AcquisitionEventHandler


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


@dataclass(slots=True)
class AttemptPlanState:
    """Mutable per-run attempt plan owned by ``BrowserAttemptRunner``.

    Lives in the shared types module so the attempt collaborator modules
    (``attempt_plan``/``attempt_execution``/``attempt_host_policy``) can type
    their ``runner`` parameter without importing the runner module back —
    that back-edge created an import cycle.
    """

    plan_id: str = ""
    plan_started_at: datetime | None = None
    plan_deadline: datetime | None = None
    attempt_specs: list[AttemptSpec] = field(default_factory=list)
    attempt_results: list[AttemptResult] = field(default_factory=list)
    retry_budget_exhausted: bool = False


@dataclass(slots=True)
class AttemptOutcomeState:
    """Latest per-run attempt outcomes owned by ``BrowserAttemptRunner``."""

    latest_page_result: PageFetchResult | None = None
    last_blocked_result: PageFetchResult | None = None
    last_browser_error: Exception | None = None


class AttemptRunner(Protocol):
    """Structural view of ``BrowserAttemptRunner`` used by its collaborators.

    Keeps ``attempt_plan``/``attempt_execution``/``attempt_host_policy``
    annotated without importing ``browser_attempt_runner`` (which imports
    them) — inverting the edge into this shared types module. ``deps`` stays
    ``Any``: ``BrowserAttemptDependencies`` is owned by the runner module and
    typing it here would re-introduce the cycle.
    """

    context: FetchRuntimeContext
    reason: str
    requested_fields: list[str] | None
    listing_recovery_mode: str | None
    capture_screenshot: bool
    host_policy: HostProtectionPolicy | None
    active_host_policy: HostProtectionPolicy | None
    plan: AttemptPlanState
    outcome: AttemptOutcomeState
    deps: Any
