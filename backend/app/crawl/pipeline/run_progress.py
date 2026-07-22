from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.db_utils import mapping_or_empty
from app.models.crawl_run import CrawlRun, CrawlUrlResult
from app.persistence.publish import VERDICT_ERROR
from app.core.shared.run_summary import as_int
from app.core.shared.coerce_primitives import string_list


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
        # Per-URL patches must stay small and fixed-size: this patch is merged
        # into the run's result_summary JSONB on every URL commit, so growing
        # payloads (url_verdicts, resolved_url_list) would rewrite an N-sized
        # blob N times. url_verdicts is written once by build_final_patch and
        # can be reconstructed from crawl_url_results for in-flight reads.
        patch = {
            "url_count": self.total_urls,
            "record_count": self.persisted_record_count,
            "domain": self.url_domain,
            "progress": self._progress_percent(),
            "processed_urls": self.completed_count,
            "completed_urls": self.completed_count,
            "remaining_urls": max(self.total_urls - self.completed_count, 0),
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


_ACQUISITION_BOOL_TOTALS = {
    "browser_attempted_urls": "browser_attempted",
    "browser_used_urls": "browser_used",
    "memory_browser_first_urls": "memory_browser_first",
    "proxy_used_urls": "proxy_used",
    "traversal_attempted": "traversal_attempted",
    "traversal_succeeded": "traversal_succeeded",
    "traversal_fell_back": "traversal_fell_back",
}
_ACQUISITION_INT_TOTALS = {
    "network_payloads_total": "network_payloads",
    "promoted_sources_total": "promoted_sources",
    "frame_sources_total": "frame_sources",
    "records_total": "record_count",
    "acquisition_ms_total": "acquisition_ms",
    "extraction_ms_total": "extraction_ms",
    "curl_fetch_ms_total": "curl_fetch_ms",
    "browser_decision_ms_total": "browser_decision_ms",
    "browser_launch_ms_total": "browser_launch_ms",
    "browser_origin_warm_ms_total": "browser_origin_warm_ms",
    "browser_navigation_ms_total": "browser_navigation_ms",
    "browser_challenge_wait_ms_total": "browser_challenge_wait_ms",
    "browser_total_ms_total": "browser_total_ms",
    "request_wait_ms_total": "request_wait_ms",
    "host_fetch_ms_total": "host_fetch_ms",
    "host_browser_first_ms_total": "host_browser_first_ms",
    "host_total_ms_total": "host_total_ms",
    "pages_collected_total": "pages_collected",
    "scroll_iterations_total": "scroll_iterations",
    "pages_scrolled_total": "pages_scrolled",
}


def _count_map(value: object) -> dict[str, int]:
    return {
        str(key): as_int(item_value)
        for key, item_value in mapping_or_empty(value).items()
    }


def _bump_counter(current: object, bucket: str, key: object) -> dict[str, int]:
    counters = _count_map(mapping_or_empty(current).get(bucket))
    name = str(key or "").strip()
    if name:
        counters[name] = as_int(counters.get(name, 0)) + 1
    return counters


def _merge_bool_totals(
    current: dict[str, object],
    url_metrics: dict[str, object],
) -> dict[str, int]:
    return {
        total_key: as_int(current.get(total_key, 0))
        + int(bool(url_metrics.get(metric_key)))
        for total_key, metric_key in _ACQUISITION_BOOL_TOTALS.items()
    }


def _merge_int_totals(
    current: dict[str, object],
    url_metrics: dict[str, object],
) -> dict[str, int]:
    return {
        total_key: as_int(current.get(total_key, 0))
        + as_int(url_metrics.get(metric_key, 0))
        for total_key, metric_key in _ACQUISITION_INT_TOTALS.items()
    }


def _merge_run_acquisition_metrics(
    existing: object,
    url_metrics: dict[str, object],
) -> dict[str, object]:
    current = mapping_or_empty(existing)
    summary = {
        "methods": _bump_counter(current, "methods", url_metrics.get("method")),
        "platform_families": _bump_counter(
            current,
            "platform_families",
            url_metrics.get("platform_family"),
        ),
        "failure_reasons": _bump_counter(
            current,
            "failure_reasons",
            url_metrics.get("failure_reason"),
        ),
        **_merge_bool_totals(current, url_metrics),
        **_merge_int_totals(current, url_metrics),
        "host_wait_seconds_total": round(
            _as_float(current.get("host_wait_seconds_total", 0.0))
            + _as_float(url_metrics.get("host_wait_seconds", 0.0)),
            3,
        ),
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


class ProgressCommitGate:
    """Throttle per-URL progress commits to at most one per configured interval."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = max(0.0, float(interval_seconds))
        self._last_commit_monotonic: float | None = None

    def due(self) -> bool:
        if self._last_commit_monotonic is None:
            return True
        elapsed = time.monotonic() - self._last_commit_monotonic
        return elapsed >= self._interval_seconds

    def mark_committed(self) -> None:
        self._last_commit_monotonic = time.monotonic()


async def load_completed_url_entries(
    session: AsyncSession, run_id: int
) -> list[tuple[str, str, str, int]]:
    """Persisted per-URL outcomes (requested_url, normalized_url, verdict, records)."""
    result = await session.execute(
        select(
            CrawlUrlResult.requested_url,
            CrawlUrlResult.normalized_url,
            CrawlUrlResult.verdict,
            CrawlUrlResult.record_count,
        )
        .where(CrawlUrlResult.run_id == run_id)
        .order_by(CrawlUrlResult.id)
    )
    return [
        (
            str(requested_url or ""),
            str(normalized_url or ""),
            str(verdict or ""),
            as_int(record_count),
        )
        for requested_url, normalized_url, verdict, record_count in result.all()
    ]


def seed_progress_from_completed_entries(
    progress_state: BatchRunProgressState,
    url_list: list[str],
    completed_entries: list[tuple[str, str, str, int]],
) -> list[tuple[int, str]]:
    """Rebuild progress from crawl_url_results; return the pending (idx, url) work.

    On re-entry (redelivery, crash recovery, resume) URLs that already have a
    persisted crawl_url_results row are folded back into the progress state at
    their original positions and skipped, so the run resumes instead of
    restarting from URL 1. A fresh run has no rows and processes everything.
    """
    if not completed_entries:
        return [(idx, url) for idx, url in enumerate(url_list, start=1)]
    completed_by_url: dict[str, tuple[str, int]] = {}
    for requested_url, normalized_url, verdict, records_count in completed_entries:
        entry = (verdict or VERDICT_ERROR, records_count)
        if requested_url:
            completed_by_url[requested_url] = entry
        if normalized_url and normalized_url not in completed_by_url:
            completed_by_url[normalized_url] = entry
    pending_items: list[tuple[int, str]] = []
    for zero_based_idx, url in enumerate(url_list):
        hit = completed_by_url.get(url)
        if hit is None:
            pending_items.append((zero_based_idx + 1, url))
            continue
        verdict, records_count = hit
        progress_state.record_url_result(
            idx=zero_based_idx,
            records_count=records_count,
            verdict=verdict,
            url_metrics={},
        )
    return pending_items


async def assemble_run_summary_payload(
    session: AsyncSession, run: CrawlRun
) -> dict[str, object]:
    """result_summary with the legacy per-URL payloads assembled at read time.

    The run row no longer stores the growing ``url_verdicts`` /
    ``resolved_url_list`` blobs while a run executes (they made every per-URL
    commit rewrite an N-sized JSONB). Read paths that must serve the legacy
    response shape should call this helper and serve the returned dict instead
    of reading ``run.result_summary`` directly. Verdicts/URLs already persisted
    in the summary (e.g. by the final patch of a completed run) win over the
    reconstructed values, which are derived from crawl_url_results in
    persistence order.
    """
    payload = run.summary_dict()
    needs_verdicts = "url_verdicts" not in payload
    needs_url_list = "resolved_url_list" not in payload
    if not (needs_verdicts or needs_url_list):
        return payload
    entries = await load_completed_url_entries(session, int(run.id))
    if not entries:
        return payload
    if needs_verdicts:
        payload["url_verdicts"] = [verdict for _, _, verdict, _ in entries]
    if needs_url_list:
        payload["resolved_url_list"] = [
            requested_url for requested_url, _, _, _ in entries if requested_url
        ]
    return payload
