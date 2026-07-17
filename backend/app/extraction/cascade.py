"""The single tier-ordering seam for the selector-free extraction cascade.

This module owns the one place that fixes the deterministic floor order —
**structured -> network -> DOM** — for every ``many``-record listing surface,
and the analogous **structured source -> DOM** floor order for ``one``-record
detail surfaces (``run_detail_cascade``). Per the repo invariant (extraction
order: structured source -> DOM, with the network-JSON floor slotted between
them for listings), the order is declared once here and executed here (first
non-empty floor wins for listings); no floor module or adapter re-decides it.

Design contract: the cascade body is **surface-agnostic**. It is driven purely
by the ``ListingSchema`` / ``SurfaceSpec`` lens; there is deliberately no
``if surface is Surface.X`` branch here (an architecture invariant).
Surface-specific DOM reuse (e.g. the commerce card collector) lives inside the
DOM-floor module ``app.extraction.listing_tier0``, not in this seam.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    CollectorOutcome,
    Evidence,
    ExtractionRequest,
    FACT_TYPES,
    HarvestResult,
)
from app.extraction.listing_tier0 import (
    collect_dom_listing,
    collect_structured_listing,
)
from app.extraction.network_listing import collect_network_listing
from app.extraction.pipeline import (
    detail_dom_collectors,
    detail_recipe_requested_evidence,
    detail_structured_collectors,
    run_detail_collectors,
)
from app.extraction.jobs import (
    job_detail_dom_collectors,
    job_detail_structured_collectors,
)
from app.extraction.surfaces import ListingSchema, Surface, SurfaceSpec

# Signature every listing floor implements: given a capture + reader + surface,
# return that floor's evidence (empty when the floor does not hold).
_Floor = Callable[..., list[Evidence]]

# Signature every detail floor implements: a collector-group factory whose
# members the cascade runs through the shared assembly primitive. The cascade
# owns the ORDER these groups run in; the group membership lives in pipeline.
_DetailFloor = Callable[[], tuple[Any, ...]]

# The single declaration of floor order. The cascade executes these in sequence
# and the first floor that yields evidence wins, so the ordering has exactly one
# owner: reorder this tuple and the runtime order changes with it.
_FLOOR_REGISTRY: Final[tuple[tuple[str, _Floor], ...]] = (
    ("structured", collect_structured_listing),
    ("network", collect_network_listing),
    ("dom", collect_dom_listing),
)

LISTING_FLOOR_ORDER: Final[tuple[str, ...]] = tuple(name for name, _ in _FLOOR_REGISTRY)


@dataclass(frozen=True)
class ListingCascadeResult:
    """Outcome of one listing-cascade run.

    ``evidence`` is the winning floor's evidence (empty when no floor held).
    ``collector_outcomes`` carries one diagnostic per floor, always emitted in
    ``floor_order``: the winning floor is ``produced_evidence``, floors that ran
    and did not hold are ``no_match``, and floors after the winner are
    ``skipped`` (never executed). ``floor_order`` is the fixed structured ->
    network -> DOM sequence declared by this seam.
    """

    evidence: tuple[Evidence, ...]
    collector_outcomes: tuple[CollectorOutcome, ...]
    floor_order: tuple[str, ...] = LISTING_FLOOR_ORDER


def run_listing_cascade(
    request: ExtractionRequest,
    reader: ArtifactReader,
    schema: ListingSchema,
) -> ListingCascadeResult:
    """Execute the deterministic listing floors in the declared order.

    Runs ``_FLOOR_REGISTRY`` in sequence; the first floor to produce evidence
    wins and later floors are skipped. Emits one ``CollectorOutcome`` per floor
    in ``LISTING_FLOOR_ORDER`` so callers see which floors ran, which held, and
    which were skipped. No model is ever invoked; this is the deterministic
    backbone only.
    """
    bundle, surface = request.capture, schema.surface
    evidence: tuple[Evidence, ...] = ()
    outcomes: list[CollectorOutcome] = []
    for name, floor in _FLOOR_REGISTRY:
        if evidence:
            outcomes.append(_outcome(name, "skipped", 0))
            continue
        rows = tuple(floor(bundle, reader, surface=surface))
        evidence = rows or evidence
        outcomes.append(
            _outcome(name, "produced_evidence" if rows else "no_match", len(rows))
        )
    return ListingCascadeResult(evidence=evidence, collector_outcomes=tuple(outcomes))


def _outcome(floor: str, status: str, count: int) -> CollectorOutcome:
    return CollectorOutcome(
        collector_id=f"listing_{floor}_floor",
        outcome=status,  # type: ignore[arg-type]
        evidence_count=count,
    )


# The single declaration of one-record detail floor order: structured source
# floor, then DOM floor. The cascade owns this ordering; group membership lives
# in pipeline. Reorder this tuple and the runtime detail floor order changes.
_DETAIL_FLOOR_REGISTRY: Final[tuple[tuple[str, _DetailFloor], ...]] = (
    ("structured", detail_structured_collectors),
    ("dom", detail_dom_collectors),
)

DETAIL_FLOOR_ORDER: Final[tuple[str, ...]] = tuple(
    name for name, _ in _DETAIL_FLOOR_REGISTRY
)

# The job-detail floor order: structured JSON-LD JobPosting floor, then the DOM
# floor fused onto the single structured subject. Same structured -> DOM order
# as commerce; the collector groups differ (job.* facts, no commerce recipe
# tail).
_JOB_DETAIL_FLOOR_REGISTRY: Final[tuple[tuple[str, _DetailFloor], ...]] = (
    ("structured", job_detail_structured_collectors),
    ("dom", job_detail_dom_collectors),
)

# Per-surface detail collector profiles, keyed by ``spec.surface``. A one-record
# surface is only supported when it has an entry here; this is the declarative,
# spec-driven support table that replaces any ``surface ==`` branch. Commerce
# detail runs the commerce collector floors; job_detail runs the job floors.
_DETAIL_SURFACE_PROFILES: Final[dict[Surface, tuple[tuple[str, _DetailFloor], ...]]] = {
    Surface.ECOMMERCE_DETAIL: _DETAIL_FLOOR_REGISTRY,
    Surface.JOB_DETAIL: _JOB_DETAIL_FLOOR_REGISTRY,
}

# Surfaces whose detail cascade runs the trailing commerce css-recipe /
# requested-field tail after the deterministic floors. The tail collects
# commerce recipe evidence, so it is commerce-only; job_detail is absent here
# and its cascade skips the tail rather than pulling commerce facts. Spec-driven
# membership test, not a ``surface ==`` branch.
_DETAIL_RECIPE_TAIL_SURFACES: Final[frozenset[Surface]] = frozenset(
    {Surface.ECOMMERCE_DETAIL}
)

DETAIL_SUPPORTED_SURFACES: Final[frozenset[Surface]] = frozenset(
    _DETAIL_SURFACE_PROFILES
)


def run_detail_cascade(
    request: ExtractionRequest,
    reader: ArtifactReader,
    spec: SurfaceSpec,
) -> HarvestResult:
    """Orchestrate the deterministic detail floors for a one-record surface.

    Owns the floor ORDER (``_DETAIL_FLOOR_REGISTRY``: structured source -> DOM)
    and runs each floor's collector group through the shared assembly primitive
    ``run_detail_collectors``, then the trailing recipe/requested-field tail. All
    detail floors run and are concatenated in order (unlike listings, where the
    first non-empty floor wins), so a one-record surface fuses structured and DOM
    evidence exactly as the legacy inline harvest did — hence byte-identical
    output.

    Routing is declarative, driven by the typed ``SurfaceSpec`` lens: the
    ``spec.cardinality`` guard rejects listings, and ``_DETAIL_SURFACE_PROFILES``
    (keyed by ``spec.surface``) selects that surface's collector profile. There
    is deliberately no ``surface ==``/``is`` branch. A one-record surface with no
    profile (e.g. job_detail until Slice 4) fails honestly rather than emitting
    another surface's facts. ``resolve``/``publish``/variant logic is untouched.
    """
    if spec.cardinality != "one":
        raise ValueError(
            f"run_detail_cascade requires a one-record surface, got {spec.surface}"
        )
    profile = _DETAIL_SURFACE_PROFILES.get(spec.surface)
    if profile is None:
        raise ValueError(
            f"no detail collector profile registered for {spec.surface}; "
            "supported one-record surfaces: "
            f"{sorted(s.value for s in DETAIL_SUPPORTED_SURFACES)}"
        )
    bundle: CaptureBundle = request.capture
    requested_fields = request.requested_fields
    # Union the surface's admitted fact set with the shared commerce FACT_TYPES
    # so commerce stays byte-identical (FACT_TYPES carries variant.option facts
    # absent from COMMERCE_FACTS) while job_detail also admits its job.* facts.
    allowed_facts = FACT_TYPES | spec.allowed_facts
    rows: list[Evidence] = []
    outcomes: list[CollectorOutcome] = []
    admitted = 0
    for _name, floor in profile:
        floor_rows, floor_outcomes, floor_admitted = run_detail_collectors(
            floor(),
            bundle,
            reader,
            requested_fields=requested_fields,
            allowed_facts=allowed_facts,
        )
        rows.extend(floor_rows)
        outcomes.extend(floor_outcomes)
        admitted += floor_admitted
    tail_rows: tuple[Evidence, ...] = ()
    tail_outcomes: tuple[CollectorOutcome, ...] = ()
    tail_admitted = 0
    if spec.surface in _DETAIL_RECIPE_TAIL_SURFACES:
        tail_rows, tail_outcomes, tail_admitted = detail_recipe_requested_evidence(
            bundle, reader, requested_fields
        )
    return HarvestResult(
        surface=spec.surface,
        evidence=(*rows, *tail_rows),
        collector_outcomes=(*outcomes, *tail_outcomes),
        admitted_source_objects=admitted + tail_admitted,
    )


__all__ = [
    "DETAIL_FLOOR_ORDER",
    "DETAIL_SUPPORTED_SURFACES",
    "LISTING_FLOOR_ORDER",
    "ListingCascadeResult",
    "run_detail_cascade",
    "run_listing_cascade",
]
