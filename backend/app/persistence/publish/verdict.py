from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

VERDICT_SUCCESS: str = "success"
VERDICT_PARTIAL: str = "partial"
VERDICT_BLOCKED: str = "blocked"
VERDICT_LISTING_FAILED: str = "listing_detection_failed"
VERDICT_EMPTY: str = "empty"
VERDICT_ERROR: str = "error"


def compute_verdict(
    *,
    is_listing: bool,
    blocked: bool,
    record_count: int,
    records: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    if int(record_count) > 0:
        if _has_high_detail_findings(records):
            return VERDICT_PARTIAL
        return VERDICT_PARTIAL if bool(blocked) else VERDICT_SUCCESS
    if bool(blocked):
        return VERDICT_BLOCKED
    return VERDICT_LISTING_FAILED if bool(is_listing) else VERDICT_EMPTY


def _has_high_detail_findings(records: Sequence[Mapping[str, Any]] | None) -> bool:
    for record in records or ():
        findings = record.get("_validation_findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            if str(finding.get("severity") or "").strip().lower() in {
                "high",
                "critical",
            }:
                return True
    return False


def aggregate_verdict(verdicts: list[str]) -> str:
    cleaned: list[str] = [
        str(value or "").strip() for value in verdicts if str(value or "").strip()
    ]
    if len(cleaned) == 0:
        return VERDICT_EMPTY
    verdict_set: set[str] = set(cleaned)
    if verdict_set.intersection({VERDICT_SUCCESS, VERDICT_PARTIAL}):
        return VERDICT_SUCCESS if verdict_set <= {VERDICT_SUCCESS} else VERDICT_PARTIAL
    for preferred in tuple([VERDICT_ERROR, VERDICT_BLOCKED, VERDICT_LISTING_FAILED]):
        if verdict_set.intersection({preferred}):
            return preferred
    return str(cleaned[-1])


def run_health_verdict(summary: dict[str, object] | object) -> dict[str, object]:
    from app.core.config.runtime_settings import crawler_runtime_settings

    payload = dict(summary) if isinstance(summary, Mapping) else {}
    raw_verdicts = payload.get("url_verdicts")
    verdicts = [
        str(value or "").strip()
        for value in list(raw_verdicts or [])
        if str(value or "").strip()
    ]
    url_count = _safe_count(payload.get("url_count"))
    count_processed, count_failures = _verdict_count_summary(
        raw_verdicts, payload.get("verdict_counts")
    )
    total, failures = _health_totals(
        raw_verdicts=raw_verdicts,
        verdicts=verdicts,
        url_count=url_count,
        count_processed=count_processed,
        count_failures=count_failures,
    )
    failure_rate = failures / total if total else 0.0
    status = _health_status(
        total=total,
        failure_rate=failure_rate,
        has_verdict_list=isinstance(raw_verdicts, list),
        degraded_rate=crawler_runtime_settings.run_health_degraded_error_rate,
        failed_rate=crawler_runtime_settings.run_health_failed_error_rate,
    )
    return {
        "status": status,
        "url_count": total,
        "failure_count": failures,
        "failure_rate": round(failure_rate, 4),
        "degraded_error_rate": crawler_runtime_settings.run_health_degraded_error_rate,
        "failed_error_rate": crawler_runtime_settings.run_health_failed_error_rate,
    }


def _safe_count(value: object) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0


def _verdict_count_summary(raw_verdicts: object, raw_counts: object) -> tuple[int, int]:
    if isinstance(raw_verdicts, list) or not isinstance(raw_counts, Mapping):
        return 0, 0
    processed = failures = 0
    for key, value in raw_counts.items():
        verdict = str(key or "").strip()
        count = _safe_count(value)
        if not verdict or count <= 0:
            continue
        processed += count
        if verdict not in {VERDICT_SUCCESS, VERDICT_PARTIAL}:
            failures += count
    return processed, failures


def _health_totals(
    *,
    raw_verdicts: object,
    verdicts: list[str],
    url_count: int,
    count_processed: int,
    count_failures: int,
) -> tuple[int, int]:
    if isinstance(raw_verdicts, list):
        total = max(url_count, len(verdicts)) if verdicts else 0
        failures = sum(
            verdict not in {VERDICT_SUCCESS, VERDICT_PARTIAL} for verdict in verdicts
        )
        return total, failures
    if count_processed:
        return max(url_count, count_processed), count_failures
    return url_count, 0


def _health_status(
    *,
    total: int,
    failure_rate: float,
    has_verdict_list: bool,
    degraded_rate: float,
    failed_rate: float,
) -> str:
    if not total:
        return "healthy" if has_verdict_list else "unknown"
    if failure_rate >= failed_rate:
        return "failed"
    if failure_rate >= degraded_rate:
        return "degraded"
    return "healthy"
