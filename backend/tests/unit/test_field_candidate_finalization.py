from __future__ import annotations

import pytest

from app.services.extract.field_candidates.finalization import finalize_candidate_value


@pytest.mark.unit
def test_long_text_finalization_keeps_shared_boilerplate_with_distinct_body() -> None:
    boilerplate = "This product is built for everyday use with reliable details. " * 4
    first = boilerplate + "First value has a distinct technical body. " * 12
    second = boilerplate + "Second value has a different technical body. " * 12

    finalized = finalize_candidate_value("description", [first, second])

    assert finalized == f"{first.strip()}\n\n{second.strip()}"


@pytest.mark.unit
def test_long_text_finalization_dedupes_short_trailing_variant_suffix() -> None:
    shared = "This product is built for everyday use with reliable details. " * 5
    first = shared + "Color: Blue"
    second = shared + "Color: Red"

    finalized = finalize_candidate_value("description", [first, second])

    assert finalized == first.strip()
