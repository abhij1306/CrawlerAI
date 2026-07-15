"""The single tier-ordering seam for the selector-free listing cascade.

This module owns the one place that fixes the deterministic floor order —
**structured -> network -> DOM** — for every ``many``-record listing surface.
Per the repo invariant (extraction order: structured source -> DOM, with the
network-JSON floor slotted between them), the order is declared once here as a
registry and executed here (first non-empty floor wins); no floor module or
adapter re-decides it.

Design contract: the cascade body is **surface-agnostic**. It is driven purely
by the ``ListingSchema`` / ``SurfaceSpec`` lens; there is deliberately no
``if surface is Surface.X`` branch here (an architecture invariant).
Surface-specific DOM reuse (e.g. the commerce card collector) lives inside the
DOM-floor module ``app.extraction.listing_tier0``, not in this seam.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.extraction.contracts import (
    ArtifactReader,
    CollectorOutcome,
    Evidence,
    ExtractionRequest,
)
from app.extraction.listing_tier0 import (
    collect_dom_listing,
    collect_structured_listing,
)
from app.extraction.network_listing import collect_network_listing
from app.extraction.surfaces import ListingSchema

# Signature every listing floor implements: given a capture + reader + surface,
# return that floor's evidence (empty when the floor does not hold).
_Floor = Callable[..., list[Evidence]]

# The single declaration of floor order. The cascade executes these in sequence
# and the first floor that yields evidence wins, so the ordering has exactly one
# owner: reorder this tuple and the runtime order changes with it.
_FLOOR_REGISTRY: Final[tuple[tuple[str, _Floor], ...]] = (
    ("structured", collect_structured_listing),
    ("network", collect_network_listing),
    ("dom", collect_dom_listing),
)

LISTING_FLOOR_ORDER: Final[tuple[str, ...]] = tuple(
    name for name, _ in _FLOOR_REGISTRY
)


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


__all__ = ["LISTING_FLOOR_ORDER", "ListingCascadeResult", "run_listing_cascade"]
