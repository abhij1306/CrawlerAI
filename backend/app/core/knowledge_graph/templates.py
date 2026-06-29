"""Template fingerprinting for Knowledge Graph matching (Slice 7).

Pure, deterministic functions for normalizing routes and generating stable
template fingerprints. Shared by the persistence projector (Slice 6) and the
extraction engine (Slice 7) to guarantee identical fingerprints at projection
time and at runtime contract matching.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.extraction.contracts import CollectorOutcome, Evidence, ExtractionResult


def normalize_route(url: str, surface: str) -> str:
    """Normalize URL path to route pattern for template fingerprinting.

    Strips product slugs/IDs so equivalent PDPs share templates (spec §5.1).
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    # Detail surfaces: replace final segment with placeholder
    if surface in ("ecommerce_detail", "job_detail") and path_parts:
        path_parts[-1] = "{id}"

    return "/" + "/".join(path_parts) if path_parts else "/"


def extract_tech_signals(result: ExtractionResult) -> list[str]:
    """Extract technology signals from collector outcomes."""
    tech_signals: list[str] = []
    collector_ids = {co.collector_id for co in result.collector_outcomes}
    if "jsonld" in collector_ids:
        tech_signals.append("jsonld")
    if "opengraph" in collector_ids:
        tech_signals.append("opengraph")
    if "microdata" in collector_ids:
        tech_signals.append("microdata")
    return tech_signals


def fingerprint_from_parts(
    url: str,
    surface: str,
    evidence: tuple[Evidence, ...],
    collector_outcomes: tuple[CollectorOutcome, ...],
) -> str:
    """Generate stable template fingerprint from raw extraction parts.

    Accepts evidence and collector_outcomes directly so the engine can fingerprint
    before an ExtractionResult is constructed. Used by contract_runtime at engine
    time; the projector calls fingerprint_template (which delegates here).
    """
    parsed = urlparse(url)
    route_pattern = normalize_route(url, surface)

    collector_ids = {co.collector_id for co in collector_outcomes}
    tech_signals: list[str] = []
    if "jsonld" in collector_ids:
        tech_signals.append("jsonld")
    if "opengraph" in collector_ids:
        tech_signals.append("opengraph")
    if "microdata" in collector_ids:
        tech_signals.append("microdata")

    fingerprint_data = {
        "route": {
            "domain": parsed.netloc,
            "route": route_pattern,
            "surface": surface,
        },
        "tech_signals": tech_signals,
        "collectors": sorted(set(e.collector_id for e in evidence)),
        "outcomes": {co.collector_id: co.outcome for co in collector_outcomes},
    }
    canonical = json.dumps(fingerprint_data, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def fingerprint_template(
    url: str,
    surface: str,
    result: ExtractionResult,
) -> str:
    """Generate stable template fingerprint from route + surface + sources.

    Excludes volatile data per feature spec §5: no product values, timestamps,
    IDs, or counts. Returns a deterministic hash suitable as canonical_key.
    """
    return fingerprint_from_parts(
        url, surface, result.evidence, result.collector_outcomes
    )
