"""Listing Integrity Gate — product-grid vs promo-only-cluster decision.

Single owner for the accept/reject decision on a ranked listing candidate set.
Pure function: no I/O, no mutation of the input records list or its elements.

Placement rationale: lives in ``backend/app/services/extract/`` because it is
part of the listing-extraction bucket per ``docs/CODEBASE_MAP.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from app.services.config.extraction_rules import (
    LISTING_CATEGORY_PATH_PREFIXES,
    LISTING_INTEGRITY_SUPPORT_FIELDS,
    LISTING_PRODUCT_DETAIL_ID_RE,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.detail_identity import (
    listing_detail_like_path,
    listing_url_is_structural,
)


@dataclass(frozen=True)
class IntegrityDecision:
    """Immutable decision record produced by :func:`evaluate_listing_integrity`."""

    outcome: Literal["product_grid", "promo_only_cluster"]
    reason: str  # short identifier for the triggering condition
    metrics: dict[str, int | float]


def evaluate_listing_integrity(
    records: list[dict[str, Any]],
    *,
    page_url: str,
    surface: str,
) -> IntegrityDecision:
    """Decide whether *records* represent a product grid or a promo-only cluster.

    Priority-ordered rules (first match wins; remaining still fill metrics):

    1. ``len(records) < listing_integrity_min_records`` → promo_only_cluster / below_min_records
    2. cohort-homogeneity ratio < threshold → promo_only_cluster / cohort_heterogeneous
    3. every record URL is a Sibling_Category_URL → promo_only_cluster / all_sibling_category_urls
    4. zero Detail_Identity_Marker AND zero support signals → promo_only_cluster / no_support_signals
    5. otherwise → product_grid / supported_set

    Pure function: no I/O, no list/element mutation.
    """
    record_count = len(records)

    # --- Compute metrics (always populated regardless of early decision) ---
    cohort_homogeneity_ratio, dominant_signature_count = _compute_cohort_homogeneity(
        records
    )
    sibling_category_count = _count_sibling_category_urls(records, page_url=page_url)
    detail_marker_count = _count_detail_markers(records, surface=surface)
    support_signal_count = _count_support_signals(records, surface=surface)

    metrics: dict[str, int | float] = {
        "record_count": record_count,
        "cohort_homogeneity_ratio": cohort_homogeneity_ratio,
        "dominant_signature_count": dominant_signature_count,
        "sibling_category_count": sibling_category_count,
        "support_signal_count": support_signal_count,
        "detail_marker_count": detail_marker_count,
    }

    # --- Priority-ordered decision rules ---
    min_records = crawler_runtime_settings.listing_integrity_min_records
    if record_count > 0 and record_count < min_records:
        # Below-threshold sets are only rejected when they also fail the
        # sibling-category or no-support-signals checks (rules 3/4 below).
        # A legitimate low-volume grid (even title-only) should not be tripped
        # by the min-records threshold alone — the Arcteryx promo cluster is
        # caught by rules 3 and 4 regardless.
        # Check: all records are sibling-category URLs AND lack support evidence.
        if (
            sibling_category_count == record_count
            and detail_marker_count == 0
            and support_signal_count == 0
        ):
            return IntegrityDecision(
                outcome="promo_only_cluster",
                reason="below_min_records",
                metrics=metrics,
            )

    min_ratio = crawler_runtime_settings.listing_cohort_homogeneity_min_ratio
    if cohort_homogeneity_ratio < min_ratio:
        # Override: non-article listings still need at least 5 records and
        # support on at least half the set. Small sets are normally not
        # overridden, but article listings may override at any size when every
        # record carries a support signal.
        support_override = (
            surface == "article_listing"
            and record_count > 0
            and support_signal_count == record_count
        ) or (record_count >= 5 and support_signal_count >= max(1, record_count // 2))
        if not support_override:
            return IntegrityDecision(
                outcome="promo_only_cluster",
                reason="cohort_heterogeneous",
                metrics=metrics,
            )

    if record_count > 0 and sibling_category_count == record_count:
        return IntegrityDecision(
            outcome="promo_only_cluster",
            reason="all_sibling_category_urls",
            metrics=metrics,
        )

    if detail_marker_count == 0 and support_signal_count == 0:
        # Only reject when records also show sibling-category signals.
        # A non-structural URL is itself evidence of a product link; the ranker
        # already validated these candidates. The Arcteryx promo tiles are all
        # sibling-category URLs and are caught by rule 3 above.
        if sibling_category_count > 0:
            return IntegrityDecision(
                outcome="promo_only_cluster",
                reason="no_support_signals",
                metrics=metrics,
            )

    return IntegrityDecision(
        outcome="product_grid",
        reason="supported_set",
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Internal metric helpers — pure, no I/O, no mutation
# ---------------------------------------------------------------------------


def _compute_cohort_homogeneity(
    records: list[dict[str, Any]],
) -> tuple[float, int]:
    """Return (homogeneity_ratio, dominant_signature_count).

    Uses the ``_structural_signature`` field on each record when available.
    Empty set returns (1.0, 0).
    """
    if not records:
        return 1.0, 0

    signatures: list[str] = []
    for record in records:
        sig = record.get("_structural_signature")
        if sig is not None:
            signatures.append(str(sig))
        else:
            # Fallback: use URL shape as a coarse signature proxy.
            url = str(record.get("url") or "").strip()
            signatures.append(_url_shape_signature(url))

    if not signatures:
        return 1.0, 0

    counter = Counter(signatures)
    dominant_count = counter.most_common(1)[0][1]
    ratio = dominant_count / len(signatures)
    return ratio, dominant_count


def _url_shape_signature(url: str) -> str:
    """Coarse URL-shape fingerprint used when no structural signature is available."""
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(url)
        path = parsed.path.lower().rstrip("/")
        segments = [seg for seg in path.split("/") if seg]
        depth = str(min(len(segments), 5))
        # Use the path prefix bucket as a distinguishing feature.
        prefix_bucket = ""
        for prefix in LISTING_CATEGORY_PATH_PREFIXES:
            if path.startswith(prefix) or (
                f"/{'/'.join(segments[:2])}".startswith(prefix)
                if len(segments) >= 2
                else False
            ):
                prefix_bucket = prefix
                break
        has_detail = "1" if LISTING_PRODUCT_DETAIL_ID_RE.search(url) else "0"
        return f"url|{depth}|{prefix_bucket}|{has_detail}"
    except (ValueError, AttributeError):
        return "url|0||0"


def _count_sibling_category_urls(
    records: list[dict[str, Any]],
    *,
    page_url: str,
) -> int:
    """Count records whose URL is a Sibling_Category_URL of *page_url*."""
    count = 0
    for record in records:
        url = str(record.get("url") or "").strip()
        if not url:
            continue
        if listing_url_is_structural(url, page_url):
            count += 1
    return count


def _count_detail_markers(
    records: list[dict[str, Any]],
    *,
    surface: str,
) -> int:
    """Count records whose URL carries a Detail_Identity_Marker."""
    count = 0
    is_job = surface.startswith("job_")
    for record in records:
        url = str(record.get("url") or "").strip()
        if not url:
            continue
        if _has_detail_identity_marker(url, is_job=is_job):
            count += 1
    return count


def _has_detail_identity_marker(url: str, *, is_job: bool) -> bool:
    """Check whether *url* carries a Detail_Identity_Marker.

    Delegates to listing_detail_like_path which handles both ecommerce
    and job surfaces via its ``is_job`` parameter.
    """
    return listing_detail_like_path(url, is_job=is_job)


def _count_support_signals(
    records: list[dict[str, Any]],
    *,
    surface: str,
) -> int:
    """Count records that have at least one support signal for the active surface."""
    support_fields = _get_support_fields(surface)
    count = 0
    for record in records:
        if _record_has_support_signal(record, support_fields=support_fields):
            count += 1
    return count


def _ensure_frozenset(value: object) -> frozenset[str]:
    """Return value as a frozenset, converting if necessary."""
    if isinstance(value, frozenset):
        return value
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, Mapping):
        exported_items = value.get("items")
        if isinstance(exported_items, Iterable) and not isinstance(
            exported_items, (str, bytes)
        ):
            return frozenset(str(item) for item in exported_items)
        return frozenset(str(item) for item in value.values())
    if isinstance(value, Iterable):
        return frozenset(str(item) for item in value)
    return frozenset()


def _get_support_fields(surface: str) -> frozenset[str]:
    """Retrieve support-signal field names for the given surface.

    Sources from ``LISTING_INTEGRITY_SUPPORT_FIELDS`` keyed by surface.
    Falls back to ecommerce_listing fields when the surface is not found.
    """
    if isinstance(LISTING_INTEGRITY_SUPPORT_FIELDS, dict):
        # Try exact match first, then prefix match.
        fields = LISTING_INTEGRITY_SUPPORT_FIELDS.get(surface)
        if fields is not None:
            return _ensure_frozenset(fields)
        # Prefix match: "ecommerce_listing" matches "ecommerce_listing_*"
        for key, value in LISTING_INTEGRITY_SUPPORT_FIELDS.items():
            if surface.startswith(key):
                return _ensure_frozenset(value)
        # Default fallback to ecommerce_listing.
        fallback = LISTING_INTEGRITY_SUPPORT_FIELDS.get("ecommerce_listing")
        if fallback is not None:
            return _ensure_frozenset(fallback)
    return frozenset({"image_url", "price", "rating", "review_count", "brand"})


def _record_has_support_signal(
    record: dict[str, Any],
    *,
    support_fields: frozenset[str],
) -> bool:
    """Return True if *record* has at least one non-empty support signal field."""
    return any(record.get(field) not in (None, "", [], {}) for field in support_fields)
