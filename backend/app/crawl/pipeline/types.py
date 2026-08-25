from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict

from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.config.runtime_settings import crawler_runtime_settings


class PublicRecord(TypedDict, total=False):
    """One public record crossing the extraction -> persistence seam.

    Keys derive from the four ``extraction.contracts`` record models
    (``CommerceDetailRecord`` / ``CommerceListingRecord`` / ``JobDetailRecord``
    / ``JobListingRecord``, dumped ``exclude_none=True`` at the seam) plus the
    bounded underscore-prefixed provenance keys the publication serializers
    attach and the persistence write path consumes. Structural typing only —
    annotations at the seam, no runtime validation in the hot path.
    """

    # Identity + commerce detail/listing scalars.
    url: str
    title: str
    brand: str
    description: str
    category: str
    sku: str
    mpn: str
    gtin: str
    price: object  # JsonValue at the contracts boundary
    price_min: object
    price_max: object
    currency: str
    original_price: object
    availability: str
    image_url: str
    additional_images: list[str]
    variant_count: int
    variants: list[dict[str, object]]
    # Job detail/listing scalars.
    company: str
    location: str
    apply_url: str
    job_id: str
    job_type: str
    posted_date: str
    # Provenance consumed by the persistence write path (stripped from the
    # stored public data; underscore-prefixed keys never go public).
    source_url: str
    _lineage: dict[str, object]
    _field_sources: dict[str, list[str]]
    _subject_id: str
    _manifest_trace: dict[str, object]
    _semantic: dict[str, object]
    _review_bucket: list[object]
    _selector_traces: dict[str, object]


class URLMetrics(TypedDict, total=False):
    """Per-URL acquisition/traversal metrics carried on ``URLProcessingResult``.

    Keys derive from ``persistence/publish/metrics.py``
    (``build_url_metrics`` + ``_acquisition_attempt_metrics`` +
    ``finalize_url_metrics``) and the failure/robots short-circuit paths in
    the extraction loop. All keys optional: short-circuit results carry only
    a subset.
    """

    # Core acquisition outcome.
    method: str
    status_code: int | None
    blocked: bool
    final_url: str
    requested_fields: list[str]
    record_count: int
    adapter_name: str | None
    platform_family: object
    failure_reason: object
    error: str
    # Browser diagnostics passthrough.
    browser_used: bool
    browser_attempted: bool
    browser_fetch_method: str | None
    memory_browser_first: bool
    browser_engine: str | None
    browser_profile: object
    browser_launch_mode: object
    browser_headless: object
    browser_native_context: object
    browser_stealth_enabled: object
    browser_reason: object
    browser_outcome: object
    browser_phase_timings_ms: dict[str, object]
    browser_navigation_strategy: object
    browser_diagnostics: dict[str, object]
    html_bytes: int
    network_payloads: int
    network_payload_count: int
    malformed_network_payloads: int
    # Traversal metrics.
    requested_traversal_mode: str | None
    traversal_mode_used: str | None
    traversal_stop_reason: object
    traversal_attempted: bool
    traversal_succeeded: bool
    traversal_fell_back: bool
    traversal_fallback_used: bool
    traversal_fallback_recovered: bool
    traversal_fallback_record_count: int
    pages_collected: int
    pages_scrolled: int
    scroll_iterations: int
    load_more_clicks: int
    traversal_iterations: int
    # Acquisition attempt summaries.
    acquisition_plan_id: object
    acquisition_attempt_count: int
    acquisition_attempts: list[dict[str, object]]
    acquisition_selected_attempt_id: object
    acquisition_outcome: object
    acquisition_termination_reason: object
    # Short-circuit payloads (robots gate / URL failure recovery).
    robots: dict[str, object]
    failure_log_persistence_error: str
    failure_log_persisted: bool


@dataclass(slots=True)
class URLProcessingResult:
    records: list[PublicRecord] = field(default_factory=list)
    verdict: str = ""
    url_metrics: URLMetrics = field(default_factory=URLMetrics)


class RecordWriter(Protocol):
    def write_record(self, record: PublicRecord) -> Any:
        raise NotImplementedError


@dataclass(slots=True)
class URLProcessingConfig:
    acquisition_plan: AcquisitionIntent | None = None
    proxy_list: list[str] = field(default_factory=list)
    traversal_mode: str | None = None
    max_pages: int = crawler_runtime_settings.default_max_pages
    max_scrolls: int = crawler_runtime_settings.default_max_scrolls
    max_records: int = crawler_runtime_settings.default_max_records
    sleep_ms: int = crawler_runtime_settings.default_sleep_ms
    update_run_state: bool = True
    persist_logs: bool = True
    prefetch_only: bool = False
    record_writer: RecordWriter | None = None
    url_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.acquisition_plan is None:
            self.acquisition_plan = AcquisitionIntent(
                surface="",
                proxy_list=tuple(self.proxy_list),
                traversal_mode=self.traversal_mode,
                max_pages=self.max_pages,
                max_scrolls=self.max_scrolls,
                max_records=self.max_records,
                sleep_ms=self.sleep_ms,
            )
        self._sync_from_plan(self.acquisition_plan)

    @classmethod
    def from_acquisition_plan(
        cls,
        plan: AcquisitionIntent,
        *,
        update_run_state: bool = True,
        persist_logs: bool = True,
        prefetch_only: bool = False,
        record_writer: RecordWriter | None = None,
        url_timeout_seconds: float | None = None,
    ) -> "URLProcessingConfig":
        return cls(
            acquisition_plan=plan,
            update_run_state=update_run_state,
            persist_logs=persist_logs,
            prefetch_only=prefetch_only,
            record_writer=record_writer,
            url_timeout_seconds=url_timeout_seconds,
        )

    def resolved_acquisition_plan(self, *, surface: str) -> AcquisitionIntent:
        if self.acquisition_plan is None:
            # Defensive for unusual construction paths; __post_init__ normally sets this.
            self.acquisition_plan = AcquisitionIntent(
                surface=str(surface or "").strip()
            )
        if self.acquisition_plan.surface == str(surface or "").strip():
            return self.acquisition_plan
        return self.acquisition_plan.with_updates(surface=str(surface or "").strip())

    def _sync_from_plan(self, plan: AcquisitionIntent) -> None:
        self.proxy_list = list(plan.proxy_list)
        self.traversal_mode = plan.traversal_mode
        self.max_pages = plan.max_pages
        self.max_scrolls = plan.max_scrolls
        self.max_records = plan.max_records
        self.sleep_ms = plan.sleep_ms
