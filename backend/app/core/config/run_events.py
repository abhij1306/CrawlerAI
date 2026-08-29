from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum


class AcquisitionEventKind(str, Enum):
    STARTED = "started"
    STRATEGY_SELECTED = "strategy_selected"
    HTTP_ATTEMPTED = "http_attempted"
    HTTP_FAILED = "http_failed"
    BROWSER_LAUNCHED = "browser_launched"
    BROWSER_PAGE_LOADED = "browser_page_loaded"
    BROWSER_FIRST_FALLBACK = "browser_first_fallback"
    BROWSER_ESCALATED = "browser_escalated"
    PROTECTION_DETECTED = "protection_detected"
    POPUP_CLOSED = "popup_closed"
    BROWSER_INTERSTITIAL_DISMISSED = "browser_interstitial_dismissed"
    TRAVERSAL_DETECTED = "traversal_detected"
    TRAVERSAL_PROGRESSED = "traversal_progressed"
    TRAVERSAL_SETTLED = "traversal_settled"
    TRAVERSAL_RECOVERY_STARTED = "traversal_recovery_started"
    TRAVERSAL_COMPLETED = "traversal_completed"


ACQUISITION_EVENT_REQUIRED_FACTS: dict[AcquisitionEventKind, frozenset[str]] = {
    AcquisitionEventKind.STARTED: frozenset({"url"}),
    AcquisitionEventKind.STRATEGY_SELECTED: frozenset(
        {
            "fetch_mode",
            "browser_first",
            "prefer_browser",
            "host_preference_enabled",
            "http_timeout_seconds",
            "primary_http_fetcher",
        }
    ),
    AcquisitionEventKind.HTTP_ATTEMPTED: frozenset(
        {"fetcher", "timeout_seconds", "proxy_mode"}
    ),
    AcquisitionEventKind.HTTP_FAILED: frozenset({"fetcher", "exception_type"}),
    AcquisitionEventKind.BROWSER_LAUNCHED: frozenset(
        {"launch_mode", "engine", "profile", "proxy_mode", "binary"}
    ),
    AcquisitionEventKind.BROWSER_PAGE_LOADED: frozenset({"elapsed_ms", "page_title"}),
    AcquisitionEventKind.BROWSER_FIRST_FALLBACK: frozenset({"exception_type"}),
    AcquisitionEventKind.BROWSER_ESCALATED: frozenset({"status_code", "method"}),
    AcquisitionEventKind.PROTECTION_DETECTED: frozenset({"status_code"}),
    AcquisitionEventKind.POPUP_CLOSED: frozenset({"popup_url"}),
    AcquisitionEventKind.BROWSER_INTERSTITIAL_DISMISSED: frozenset({"selector"}),
    AcquisitionEventKind.TRAVERSAL_DETECTED: frozenset(
        {"mode", "safety_cap", "target_records"}
    ),
    AcquisitionEventKind.TRAVERSAL_PROGRESSED: frozenset(
        {
            "action",
            "step",
            "previous_card_count",
            "current_card_count",
            "target_records",
        }
    ),
    AcquisitionEventKind.TRAVERSAL_SETTLED: frozenset(
        {"previous_card_count", "current_card_count"}
    ),
    AcquisitionEventKind.TRAVERSAL_RECOVERY_STARTED: frozenset({"action"}),
    AcquisitionEventKind.TRAVERSAL_COMPLETED: frozenset(
        {"mode", "card_count", "fragment_count", "progress_event_count", "stop_reason"}
    ),
}


class RunEventKind(StrEnum):
    RUN_PUBLIC_HTTP_STARTED = "run.public_http_started"
    RUN_STARTED = "run.started"
    RUN_SEED_URLS_RESOLVED = "run.seed_urls_resolved"
    RUN_CONCURRENCY_SELECTED = "run.concurrency_selected"
    RUN_CONTROL_REQUESTED = "run.control_requested"
    RUN_CONTROL_APPLIED = "run.control_applied"
    RUN_LIMIT_REACHED = "run.limit_reached"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_STALE_RECOVERED = "run.stale_recovered"
    RUN_CALLBACK_FAILED = "run.callback_failed"
    REVIEW_FIELDS_COMMITTED = "review.fields_committed"
    URL_STARTED = "url.started"
    URL_COMPLETED = "url.completed"
    URL_FAILED = "url.failed"
    ROBOTS_CHECKED = "robots.checked"
    ACQUISITION_STARTED = "acquisition.started"
    ACQUISITION_STRATEGY_SELECTED = "acquisition.strategy_selected"
    ACQUISITION_HTTP_ATTEMPTED = "acquisition.http_attempted"
    ACQUISITION_HTTP_FAILED = "acquisition.http_failed"
    ACQUISITION_BROWSER_LAUNCHED = "acquisition.browser_launched"
    ACQUISITION_BROWSER_PAGE_LOADED = "acquisition.browser_page_loaded"
    ACQUISITION_INTERSTITIAL_DISMISSED = "acquisition.interstitial_dismissed"
    ACQUISITION_BROWSER_FIRST_FALLBACK = "acquisition.browser_first_fallback"
    ACQUISITION_BROWSER_ESCALATED = "acquisition.browser_escalated"
    ACQUISITION_COMPLETED = "acquisition.completed"
    ACQUISITION_PROTECTION_DETECTED = "acquisition.protection_detected"
    ACQUISITION_POPUP_CLOSED = "acquisition.popup_closed"
    BROWSER_RETRY_RESULT = "browser_retry.result"
    BROWSER_RETRY_PRECOMMIT_UNAVAILABLE = "browser_retry.precommit_unavailable"
    TRAVERSAL_DETECTED = "traversal.detected"
    TRAVERSAL_PROGRESS = "traversal.progress"
    TRAVERSAL_SETTLED = "traversal.settled"
    TRAVERSAL_RECOVERY_STARTED = "traversal.recovery_started"
    TRAVERSAL_COMPLETED = "traversal.completed"
    EXTRACTION_VARIANT_EXPANSION_FAILED = "extraction.variant_expansion_failed"
    EXTRACTION_LISTING_FALLBACK = "extraction.listing_fallback"
    EXTRACTION_MEMORY_OBSERVATION_FAILED = "extraction_memory.observation_failed"
    PERSISTENCE_RECORDS_PERSISTED = "persistence.records_persisted"


class RunEventStage(StrEnum):
    ACQUISITION = "acquisition"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    PERSISTENCE = "persistence"


class RunEventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RunEventOutcome(StrEnum):
    PROGRESS = "progress"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    REQUESTED = "requested"
    LIMITED = "limited"


class RunEventUrlPolicy(StrEnum):
    FORBIDDEN = "forbidden"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class RunEventDefinition:
    stage: RunEventStage | None
    severity: RunEventSeverity
    outcome: RunEventOutcome
    url_policy: RunEventUrlPolicy
    required_facts: frozenset[str] = frozenset()
    optional_facts: frozenset[str] = frozenset()
    reason_codes: frozenset[str] = frozenset()
    allows_open_reason_code: bool = False


def _run(
    *,
    stage: RunEventStage | None = None,
    severity: RunEventSeverity = RunEventSeverity.INFO,
    outcome: RunEventOutcome = RunEventOutcome.PROGRESS,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
) -> RunEventDefinition:
    return RunEventDefinition(
        stage=stage,
        severity=severity,
        outcome=outcome,
        url_policy=RunEventUrlPolicy.FORBIDDEN,
        required_facts=frozenset(required),
        optional_facts=frozenset(optional),
        reason_codes=frozenset(reasons),
    )


def _url(
    stage: RunEventStage,
    *,
    severity: RunEventSeverity = RunEventSeverity.INFO,
    outcome: RunEventOutcome = RunEventOutcome.PROGRESS,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    allows_open_reason_code: bool = False,
) -> RunEventDefinition:
    return RunEventDefinition(
        stage=stage,
        severity=severity,
        outcome=outcome,
        url_policy=RunEventUrlPolicy.REQUIRED,
        required_facts=frozenset(required),
        optional_facts=frozenset(optional),
        reason_codes=frozenset(reasons),
        allows_open_reason_code=allows_open_reason_code,
    )


RUN_EVENT_DEFINITIONS: dict[RunEventKind, RunEventDefinition] = {
    RunEventKind.RUN_PUBLIC_HTTP_STARTED: _run(optional=("surface",)),
    RunEventKind.RUN_STARTED: _run(required=("seed_url_count",)),
    RunEventKind.RUN_SEED_URLS_RESOLVED: _run(
        required=("seed_url_count",), optional=("domain_policy",)
    ),
    RunEventKind.RUN_CONCURRENCY_SELECTED: _run(required=("url_count", "concurrency")),
    RunEventKind.RUN_CONTROL_REQUESTED: _run(
        outcome=RunEventOutcome.REQUESTED,
        reasons=("pause", "resume", "kill"),
    ),
    RunEventKind.RUN_CONTROL_APPLIED: _run(
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.CANCELLED,
        reasons=("paused", "resumed", "killed"),
    ),
    RunEventKind.RUN_LIMIT_REACHED: _run(
        outcome=RunEventOutcome.LIMITED,
        required=("limit_name", "limit_value"),
    ),
    RunEventKind.RUN_COMPLETED: _run(
        outcome=RunEventOutcome.SUCCEEDED,
        required=("record_count", "verdict"),
    ),
    RunEventKind.RUN_FAILED: _run(
        severity=RunEventSeverity.ERROR,
        outcome=RunEventOutcome.FAILED,
        required=("exception_type",),
    ),
    RunEventKind.RUN_STALE_RECOVERED: _run(
        severity=RunEventSeverity.ERROR,
        outcome=RunEventOutcome.FAILED,
        required=("status",),
        reasons=("interrupted_before_start", "interrupted_during_run"),
    ),
    RunEventKind.RUN_CALLBACK_FAILED: _run(
        severity=RunEventSeverity.ERROR,
        outcome=RunEventOutcome.FAILED,
        required=("exception_type",),
    ),
    RunEventKind.REVIEW_FIELDS_COMMITTED: _run(
        stage=RunEventStage.PERSISTENCE,
        outcome=RunEventOutcome.SUCCEEDED,
        required=("field_count",),
    ),
    RunEventKind.URL_STARTED: _url(
        RunEventStage.ACQUISITION, required=("index", "total")
    ),
    RunEventKind.URL_COMPLETED: _url(
        RunEventStage.PERSISTENCE,
        outcome=RunEventOutcome.SUCCEEDED,
        required=("record_count", "verdict"),
        optional=("final_url",),
    ),
    RunEventKind.URL_FAILED: _url(
        RunEventStage.PERSISTENCE,
        severity=RunEventSeverity.ERROR,
        outcome=RunEventOutcome.FAILED,
        required=("exception_type",),
        optional=("timeout_seconds",),
        reasons=("timeout", "exception"),
    ),
    RunEventKind.ROBOTS_CHECKED: _url(
        RunEventStage.ACQUISITION,
        reasons=("allowed", "blocked", "missing", "fetch_failed"),
    ),
    RunEventKind.ACQUISITION_STARTED: _url(RunEventStage.ACQUISITION),
    RunEventKind.ACQUISITION_STRATEGY_SELECTED: _url(
        RunEventStage.ACQUISITION,
        allows_open_reason_code=True,
        required=("strategy",),
        optional=(
            "reason",
            "browser_first",
            "prefer_browser",
            "host_preference_enabled",
            "http_timeout_seconds",
            "primary_http_fetcher",
        ),
    ),
    RunEventKind.ACQUISITION_HTTP_ATTEMPTED: _url(
        RunEventStage.ACQUISITION,
        required=("fetcher",),
        optional=("timeout_seconds", "proxy_mode"),
    ),
    RunEventKind.ACQUISITION_HTTP_FAILED: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        required=("fetcher", "exception_type"),
    ),
    RunEventKind.ACQUISITION_BROWSER_LAUNCHED: _url(
        RunEventStage.ACQUISITION,
        required=("engine", "launch_mode"),
        optional=("profile", "proxy_mode", "binary"),
    ),
    RunEventKind.ACQUISITION_BROWSER_PAGE_LOADED: _url(
        RunEventStage.ACQUISITION,
        required=("elapsed_ms",),
        optional=("page_title",),
    ),
    RunEventKind.ACQUISITION_INTERSTITIAL_DISMISSED: _url(
        RunEventStage.ACQUISITION, required=("selector",)
    ),
    RunEventKind.ACQUISITION_BROWSER_FIRST_FALLBACK: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        required=("exception_type",),
    ),
    RunEventKind.ACQUISITION_BROWSER_ESCALATED: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        optional=("status_code", "prior_method", "reason"),
        allows_open_reason_code=True,
    ),
    RunEventKind.ACQUISITION_COMPLETED: _url(
        RunEventStage.ACQUISITION,
        outcome=RunEventOutcome.SUCCEEDED,
        required=("method",),
        optional=("status_code", "elapsed_ms"),
    ),
    RunEventKind.ACQUISITION_PROTECTION_DETECTED: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.BLOCKED,
        optional=("status_code",),
    ),
    RunEventKind.ACQUISITION_POPUP_CLOSED: _url(
        RunEventStage.ACQUISITION, required=("popup_url",)
    ),
    RunEventKind.BROWSER_RETRY_RESULT: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        optional=(
            "exception_type",
            "reason",
        ),
        reasons=("failed", "skipped"),
    ),
    RunEventKind.BROWSER_RETRY_PRECOMMIT_UNAVAILABLE: _url(
        RunEventStage.ACQUISITION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.SKIPPED,
    ),
    RunEventKind.TRAVERSAL_DETECTED: _url(
        RunEventStage.ACQUISITION,
        required=("mode",),
        optional=("target_records", "safety_cap"),
    ),
    RunEventKind.TRAVERSAL_PROGRESS: _url(
        RunEventStage.ACQUISITION,
        required=("action", "step"),
        optional=("previous_count", "current_count", "target_records"),
    ),
    RunEventKind.TRAVERSAL_SETTLED: _url(
        RunEventStage.ACQUISITION,
        optional=("previous_count", "record_count", "iterations"),
    ),
    RunEventKind.TRAVERSAL_RECOVERY_STARTED: _url(
        RunEventStage.ACQUISITION, required=("action",)
    ),
    RunEventKind.TRAVERSAL_COMPLETED: _url(
        RunEventStage.ACQUISITION,
        outcome=RunEventOutcome.SUCCEEDED,
        required=("mode",),
        optional=("record_count", "fragment_count", "progress_count", "stop_reason"),
    ),
    RunEventKind.EXTRACTION_VARIANT_EXPANSION_FAILED: _url(
        RunEventStage.EXTRACTION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        required=("exception_type",),
    ),
    RunEventKind.EXTRACTION_LISTING_FALLBACK: _url(
        RunEventStage.EXTRACTION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        optional=("record_count",),
        reasons=("recovered", "empty"),
    ),
    RunEventKind.EXTRACTION_MEMORY_OBSERVATION_FAILED: _url(
        RunEventStage.EXTRACTION,
        severity=RunEventSeverity.WARNING,
        outcome=RunEventOutcome.PARTIAL,
        required=("exception_type",),
    ),
    RunEventKind.PERSISTENCE_RECORDS_PERSISTED: _url(
        RunEventStage.PERSISTENCE,
        outcome=RunEventOutcome.SUCCEEDED,
        required=("record_count", "final_url"),
    ),
}

RUN_EVENT_REASON_OUTCOMES: dict[tuple[RunEventKind, str], RunEventOutcome] = {
    (RunEventKind.RUN_CONTROL_APPLIED, "paused"): RunEventOutcome.CANCELLED,
    (RunEventKind.RUN_CONTROL_APPLIED, "resumed"): RunEventOutcome.SUCCEEDED,
    (RunEventKind.RUN_CONTROL_APPLIED, "killed"): RunEventOutcome.CANCELLED,
    (
        RunEventKind.RUN_STALE_RECOVERED,
        "interrupted_before_start",
    ): RunEventOutcome.CANCELLED,
    (RunEventKind.ROBOTS_CHECKED, "allowed"): RunEventOutcome.SUCCEEDED,
    (RunEventKind.ROBOTS_CHECKED, "blocked"): RunEventOutcome.BLOCKED,
    (RunEventKind.ROBOTS_CHECKED, "missing"): RunEventOutcome.SUCCEEDED,
    (RunEventKind.ROBOTS_CHECKED, "fetch_failed"): RunEventOutcome.PARTIAL,
    (RunEventKind.BROWSER_RETRY_RESULT, "failed"): RunEventOutcome.FAILED,
    (RunEventKind.BROWSER_RETRY_RESULT, "skipped"): RunEventOutcome.SKIPPED,
    (RunEventKind.EXTRACTION_LISTING_FALLBACK, "recovered"): RunEventOutcome.PARTIAL,
    (RunEventKind.EXTRACTION_LISTING_FALLBACK, "empty"): RunEventOutcome.FAILED,
}

RUN_EVENT_REASON_SEVERITIES: dict[tuple[RunEventKind, str], RunEventSeverity] = {
    (RunEventKind.RUN_CONTROL_REQUESTED, "pause"): RunEventSeverity.WARNING,
    (RunEventKind.RUN_CONTROL_REQUESTED, "kill"): RunEventSeverity.WARNING,
    (RunEventKind.RUN_CONTROL_APPLIED, "resumed"): RunEventSeverity.INFO,
    (
        RunEventKind.RUN_STALE_RECOVERED,
        "interrupted_before_start",
    ): RunEventSeverity.WARNING,
    (RunEventKind.ROBOTS_CHECKED, "blocked"): RunEventSeverity.WARNING,
    (RunEventKind.ROBOTS_CHECKED, "fetch_failed"): RunEventSeverity.WARNING,
    (RunEventKind.BROWSER_RETRY_RESULT, "skipped"): RunEventSeverity.INFO,
}

RUN_EVENT_VERDICT_OUTCOMES: dict[str, RunEventOutcome] = {
    "success": RunEventOutcome.SUCCEEDED,
    "partial": RunEventOutcome.PARTIAL,
    "blocked": RunEventOutcome.BLOCKED,
    "listing_detection_failed": RunEventOutcome.FAILED,
    "empty": RunEventOutcome.FAILED,
    "error": RunEventOutcome.FAILED,
}


__all__ = [
    "ACQUISITION_EVENT_REQUIRED_FACTS",
    "RUN_EVENT_DEFINITIONS",
    "RUN_EVENT_REASON_OUTCOMES",
    "RUN_EVENT_REASON_SEVERITIES",
    "RUN_EVENT_VERDICT_OUTCOMES",
    "AcquisitionEventKind",
    "RunEventDefinition",
    "RunEventKind",
    "RunEventOutcome",
    "RunEventSeverity",
    "RunEventStage",
    "RunEventUrlPolicy",
]
