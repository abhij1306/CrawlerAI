"""Phase 1.1 — resolution ranking spine (precision / the phantom-DOM bug).

``_rank`` orders candidates on a single shared spine
``(value_quality, reliability, directness, …)`` so that *source reliability beats
directness*: an embedded JSON-LD offer outranks a phantom ``[data-price]`` DOM
scrape, and a shape-valid value outranks a shape-invalid one even when the
invalid value carried no rejection flag. Field-specific quality terms
(title pollution, brand derivation) ride on top of that spine and are preserved.
"""

from __future__ import annotations

import pytest

from app.core.config import field_mappings
from app.extraction.contracts import Evidence, SourceLocator
from app.extraction.resolution import _rank, _resolve_scalar

pytestmark = pytest.mark.unit


def _evidence(
    evidence_id: str,
    *,
    fact_type: str,
    value: object,
    collector_id: str,
    directness: str = "direct",
    confidence: float = 0.9,
    flags: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle-1",
        artifact_id="artifact-1",
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=f"/{evidence_id}"),
        directness=directness,  # type: ignore[arg-type]
        confidence=confidence,
        flags=flags,
        metadata=metadata or {},
        subject_id="subject-1",
    )


def _winner(*evidence: Evidence) -> str:
    by_id = {ev.evidence_id: ev for ev in evidence}
    decision = _resolve_scalar(
        "entity-1",
        evidence[0].fact_type,
        tuple(by_id),
        by_id,
        (),
    )
    assert decision.status == "resolved"
    return decision.accepted_evidence_ids[0]


def test_jsonld_offer_outranks_phantom_dom_price() -> None:
    # The bug: a `direct` DOM [data-price] used to beat an `embedded` JSON-LD
    # offer because directness preceded reliability. Reliability now wins.
    jsonld = _evidence(
        "ev-jsonld",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="19.99",
        collector_id="jsonld",
        directness="embedded",
    )
    phantom_dom = _evidence(
        "ev-dom",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="9.99",
        collector_id="dom",
        directness="direct",
    )
    assert _rank(jsonld) < _rank(phantom_dom)
    assert _winner(jsonld, phantom_dom) == "ev-jsonld"


def test_enum_invalid_availability_loses_to_enum_valid() -> None:
    # Both pass flag-based admissibility (neither is flagged invalid_availability);
    # the shape-only value_quality term breaks the tie toward the canonical enum.
    valid = _evidence(
        "ev-valid",
        fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        value="in_stock",
        collector_id="dom",
    )
    off_enum = _evidence(
        "ev-off-enum",
        fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        value="on_sale",
        collector_id="jsonld",
        directness="embedded",
    )
    # Even though off_enum comes from a more reliable collector, its non-enum
    # shape ranks it below the canonical value.
    assert _rank(valid) < _rank(off_enum)
    assert _winner(valid, off_enum) == "ev-valid"


def test_malformed_price_loses_to_well_formed_price() -> None:
    well_formed = _evidence(
        "ev-good",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="19.99",
        collector_id="dom",
    )
    malformed = _evidence(
        "ev-bad",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="call for price",
        collector_id="jsonld",
        directness="embedded",
    )
    assert _rank(well_formed) < _rank(malformed)


def test_title_pollution_ranking_preserved() -> None:
    clean = _evidence(
        "ev-clean",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe",
        collector_id="dom",
    )
    polluted = _evidence(
        "ev-polluted",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe | Buy Now | BrandStore",
        collector_id="jsonld",
        directness="embedded",
        flags=("seo_title_pollution",),
    )
    assert _rank(clean) < _rank(polluted)


def test_brand_derivation_ranking_preserved() -> None:
    direct = _evidence(
        "ev-direct",
        fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
        value="Acme",
        collector_id="jsonld",
        directness="embedded",
    )
    derived = _evidence(
        "ev-derived",
        fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
        value="Acme",
        collector_id="dom",
        metadata={"derived_by": "brand_from_title_host"},
    )
    assert _rank(direct) < _rank(derived)
