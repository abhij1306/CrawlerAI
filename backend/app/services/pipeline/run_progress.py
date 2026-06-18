from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.db_utils import mapping_or_empty
from app.services.run_summary import as_int
from app.services.shared.coerce_primitives import string_list

if TYPE_CHECKING:
    from app.models.crawl_run import CrawlRun


@dataclass(slots=True)
class BatchRunProgressState:
    total_urls: int
    url_domain: str = ""
    url_verdicts: list[str] = field(default_factory=list)
    verdict_counts: dict[str, int] = field(default_factory=dict)
    acquisition_summary: dict[str, object] = field(default_factory=dict)
    quality_summary: dict[str, object] = field(default_factory=dict)
    persisted_record_count: int = 0
    completed_count: int = 0

    @classmethod
    def from_run(
        cls,
        run: "CrawlRun",
        *,
        total_urls: int,
        url_domain: str,
        persisted_record_count: int,
    ) -> "BatchRunProgressState":
        return cls.from_summary(
            run.summary_dict(),
            total_urls=total_urls,
            url_domain=url_domain,
            persisted_record_count=persisted_record_count,
        )

    @classmethod
    def from_summary(
        cls,
        current_summary: object,
        *,
        total_urls: int,
        url_domain: str,
        persisted_record_count: int,
    ) -> "BatchRunProgressState":
        summary = mapping_or_empty(current_summary)
        raw_verdicts = string_list(
            summary.get("url_verdicts"), strip=True, none_as_empty=True
        )[:total_urls]
        completed_count = min(as_int(summary.get("completed_urls", 0)), total_urls)
        if raw_verdicts:
            completed_count = 0
            for verdict in raw_verdicts:
                if not verdict:
                    break
                completed_count += 1
        return cls(
            total_urls=total_urls,
            url_domain=str(url_domain or ""),
            url_verdicts=raw_verdicts,
            verdict_counts={
                str(key): as_int(value)
                for key, value in mapping_or_empty(
                    summary.get("verdict_counts")
                ).items()
            },
            acquisition_summary=mapping_or_empty(summary.get("acquisition_summary")),
            quality_summary=mapping_or_empty(summary.get("quality_summary")),
            persisted_record_count=max(0, as_int(persisted_record_count)),
            completed_count=completed_count,
        )

    def record_url_result(
        self,
        *,
        idx: int,
        records_count: int,
        verdict: str,
        url_metrics: dict[str, object],
    ) -> None:
        self.persisted_record_count += max(0, as_int(records_count))
        self.completed_count += 1
        if idx >= len(self.url_verdicts):
            self.url_verdicts.extend([""] * (idx + 1 - len(self.url_verdicts)))
        self.url_verdicts[idx] = verdict
        self.verdict_counts[verdict] = int(self.verdict_counts.get(verdict, 0)) + 1
        self.acquisition_summary = _merge_run_acquisition_metrics(
            self.acquisition_summary,
            url_metrics,
        )
        self.quality_summary = _merge_run_quality_summary(
            self.quality_summary,
            url_metrics,
        )

    def build_progress_patch(
        self,
        *,
        current_url: str,
        current_url_index: int,
        error_message: str | None = None,
    ) -> dict[str, object]:
        patch = {
            "url_count": self.total_urls,
            "record_count": self.persisted_record_count,
            "domain": self.url_domain,
            "progress": self._progress_percent(),
            "processed_urls": self.completed_count,
            "completed_urls": self.completed_count,
            "remaining_urls": max(self.total_urls - self.completed_count, 0),
            "url_verdicts": self.url_verdicts,
            "verdict_counts": self.verdict_counts,
            "acquisition_summary": self.acquisition_summary,
            "quality_summary": self.quality_summary,
            "current_url": current_url,
            "current_url_index": current_url_index,
        }
        if error_message:
            patch["error"] = error_message
        return patch

    def build_final_patch(self, aggregate_verdict: str) -> dict[str, object]:
        return {
            "url_count": self.total_urls,
            "record_count": self.persisted_record_count,
            "domain": self.url_domain,
            "progress": self._progress_percent(final=True),
            "extraction_verdict": aggregate_verdict,
            "url_verdicts": self.url_verdicts,
            "processed_urls": self.completed_count,
            "completed_urls": self.completed_count,
            "remaining_urls": max(self.total_urls - self.completed_count, 0),
            "verdict_counts": self.verdict_counts,
            "acquisition_summary": self.acquisition_summary,
            "quality_summary": self.quality_summary,
        }

    def _progress_percent(self, *, final: bool = False) -> int:
        if self.total_urls <= 0:
            return 100 if final else 0
        return int((self.completed_count / self.total_urls) * 100)


def _as_float(value: object) -> float:
    try:
        return float(str(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _merge_run_acquisition_metrics(
    existing: object,
    url_metrics: dict[str, object],
) -> dict[str, object]:
    current = mapping_or_empty(existing)
    methods = {
        str(key): as_int(value)
        for key, value in mapping_or_empty(current.get("methods")).items()
    }
    method = str(url_metrics.get("method") or "").strip()
    if method:
        methods[method] = as_int(methods.get(method, 0)) + 1
    platform_families = {
        str(key): as_int(value)
        for key, value in mapping_or_empty(current.get("platform_families")).items()
    }
    platform_family = str(url_metrics.get("platform_family") or "").strip()
    if platform_family:
        platform_families[platform_family] = (
            as_int(platform_families.get(platform_family, 0)) + 1
        )
    failure_reasons = {
        str(key): as_int(value)
        for key, value in mapping_or_empty(current.get("failure_reasons")).items()
    }
    failure_reason = str(url_metrics.get("failure_reason") or "").strip()
    if failure_reason:
        failure_reasons[failure_reason] = (
            as_int(failure_reasons.get(failure_reason, 0)) + 1
        )

    summary = {
        "methods": methods,
        "platform_families": platform_families,
        "failure_reasons": failure_reasons,
        "browser_attempted_urls": as_int(current.get("browser_attempted_urls", 0))
        + int(bool(url_metrics.get("browser_attempted"))),
        "browser_used_urls": as_int(current.get("browser_used_urls", 0))
        + int(bool(url_metrics.get("browser_used"))),
        "memory_browser_first_urls": as_int(current.get("memory_browser_first_urls", 0))
        + int(bool(url_metrics.get("memory_browser_first"))),
        "proxy_used_urls": as_int(current.get("proxy_used_urls", 0))
        + int(bool(url_metrics.get("proxy_used"))),
        "network_payloads_total": as_int(current.get("network_payloads_total", 0))
        + as_int(url_metrics.get("network_payloads", 0)),
        "promoted_sources_total": as_int(current.get("promoted_sources_total", 0))
        + as_int(url_metrics.get("promoted_sources", 0)),
        "frame_sources_total": as_int(current.get("frame_sources_total", 0))
        + as_int(url_metrics.get("frame_sources", 0)),
        "host_wait_seconds_total": round(
            _as_float(current.get("host_wait_seconds_total", 0.0))
            + _as_float(url_metrics.get("host_wait_seconds", 0.0)),
            3,
        ),
        "records_total": as_int(current.get("records_total", 0))
        + as_int(url_metrics.get("record_count", 0)),
        "acquisition_ms_total": as_int(current.get("acquisition_ms_total", 0))
        + as_int(url_metrics.get("acquisition_ms", 0)),
        "extraction_ms_total": as_int(current.get("extraction_ms_total", 0))
        + as_int(url_metrics.get("extraction_ms", 0)),
        "curl_fetch_ms_total": as_int(current.get("curl_fetch_ms_total", 0))
        + as_int(url_metrics.get("curl_fetch_ms", 0)),
        "browser_decision_ms_total": as_int(current.get("browser_decision_ms_total", 0))
        + as_int(url_metrics.get("browser_decision_ms", 0)),
        "browser_launch_ms_total": as_int(current.get("browser_launch_ms_total", 0))
        + as_int(url_metrics.get("browser_launch_ms", 0)),
        "browser_origin_warm_ms_total": as_int(
            current.get("browser_origin_warm_ms_total", 0)
        )
        + as_int(url_metrics.get("browser_origin_warm_ms", 0)),
        "browser_navigation_ms_total": as_int(
            current.get("browser_navigation_ms_total", 0)
        )
        + as_int(url_metrics.get("browser_navigation_ms", 0)),
        "browser_challenge_wait_ms_total": as_int(
            current.get("browser_challenge_wait_ms_total", 0)
        )
        + as_int(url_metrics.get("browser_challenge_wait_ms", 0)),
        "browser_total_ms_total": as_int(current.get("browser_total_ms_total", 0))
        + as_int(url_metrics.get("browser_total_ms", 0)),
        "request_wait_ms_total": as_int(current.get("request_wait_ms_total", 0))
        + as_int(url_metrics.get("request_wait_ms", 0)),
        "host_fetch_ms_total": as_int(current.get("host_fetch_ms_total", 0))
        + as_int(url_metrics.get("host_fetch_ms", 0)),
        "host_browser_first_ms_total": as_int(
            current.get("host_browser_first_ms_total", 0)
        )
        + as_int(url_metrics.get("host_browser_first_ms", 0)),
        "host_total_ms_total": as_int(current.get("host_total_ms_total", 0))
        + as_int(url_metrics.get("host_total_ms", 0)),
        "pages_collected_total": as_int(current.get("pages_collected_total", 0))
        + as_int(url_metrics.get("pages_collected", 0)),
        "scroll_iterations_total": as_int(current.get("scroll_iterations_total", 0))
        + as_int(url_metrics.get("scroll_iterations", 0)),
        "pages_scrolled_total": as_int(current.get("pages_scrolled_total", 0))
        + as_int(url_metrics.get("pages_scrolled", 0)),
        "traversal_attempted": as_int(current.get("traversal_attempted", 0))
        + int(bool(url_metrics.get("traversal_attempted"))),
        "traversal_succeeded": as_int(current.get("traversal_succeeded", 0))
        + int(bool(url_metrics.get("traversal_succeeded"))),
        "traversal_fell_back": as_int(current.get("traversal_fell_back", 0))
        + int(bool(url_metrics.get("traversal_fell_back"))),
    }
    traversal_mode = str(url_metrics.get("traversal_mode_used") or "").strip()
    if traversal_mode:
        traversal_modes_used = {
            str(key): as_int(value)
            for key, value in mapping_or_empty(
                current.get("traversal_modes_used")
            ).items()
        }
        summary["traversal_modes_used"] = {
            **traversal_modes_used,
            traversal_mode: as_int(traversal_modes_used.get(traversal_mode, 0)) + 1,
        }
    elif current.get("traversal_modes_used"):
        summary["traversal_modes_used"] = mapping_or_empty(
            current.get("traversal_modes_used")
        )

    return summary


def _quality_level_from_score(score: float) -> str:
    if score >= crawler_runtime_settings.run_quality_threshold_high:
        return "high"
    if score >= crawler_runtime_settings.run_quality_threshold_medium:
        return "medium"
    return "low"


def _merge_run_quality_summary(
    existing: object,
    url_metrics: dict[str, object],
) -> dict[str, object]:
    current = mapping_or_empty(existing)
    url_quality: dict[str, object] = (
        mapping_or_empty(url_metrics.get("quality_summary"))
        if isinstance(url_metrics.get("quality_summary"), dict)
        else {}
    )
    if not url_quality:
        return current

    level_counts = {
        str(key): as_int(value)
        for key, value in mapping_or_empty(current.get("level_counts")).items()
    }
    url_level = str(url_quality.get("level") or "").strip().lower()
    if url_level in {"high", "medium", "low", "unknown"}:
        level_counts[url_level] = int(level_counts.get(url_level, 0) or 0) + 1

    current_scored_urls = as_int(current.get("scored_urls", 0))
    current_score_total = _as_float(current.get("score", 0.0)) * current_scored_urls
    next_scored_urls = current_scored_urls + 1
    next_score_total = current_score_total + _as_float(url_quality.get("score", 0.0))
    average_score = round(next_score_total / next_scored_urls, 4)

    listing_incomplete = as_int(current.get("listing_incomplete_urls", 0))
    listing_completeness_value = url_quality.get("listing_completeness")
    listing_completeness: dict[str, object] = (
        listing_completeness_value
        if isinstance(listing_completeness_value, dict)
        else {}
    )
    if listing_completeness.get("applicable") and not listing_completeness.get(
        "complete", True
    ):
        listing_incomplete += 1

    variant_incomplete = as_int(current.get("variant_incomplete_urls", 0))
    variant_completeness_value = url_quality.get("variant_completeness")
    variant_completeness: dict[str, object] = (
        variant_completeness_value
        if isinstance(variant_completeness_value, dict)
        else {}
    )
    if variant_completeness.get("applicable") and not variant_completeness.get(
        "complete", True
    ):
        variant_incomplete += 1

    requested_total = max(
        as_int(current.get("requested_fields_total", 0)),
        as_int(url_quality.get("requested_fields_total", 0)),
    )
    requested_found_best = max(
        as_int(current.get("requested_fields_found_best", 0)),
        as_int(url_quality.get("requested_fields_found_best", 0)),
    )

    summary = {
        "level": _quality_level_from_score(average_score),
        "score": average_score,
        "scored_urls": next_scored_urls,
        "level_counts": level_counts,
        "listing_incomplete_urls": listing_incomplete,
        "variant_incomplete_urls": variant_incomplete,
    }
    if requested_total > 0:
        summary["requested_fields_total"] = requested_total
    if requested_found_best > 0:
        summary["requested_fields_found_best"] = requested_found_best
    return summary
