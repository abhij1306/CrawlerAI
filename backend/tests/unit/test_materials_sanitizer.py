"""Unit tests for materials field cleanup in detail extraction."""
from __future__ import annotations

import pytest

from app.services.extract.detail.text.sanitizer import _clean_materials_pollution


@pytest.mark.unit
def test_clean_materials_passes_real_composition() -> None:
    assert _clean_materials_pollution("100% Wool") == "100% Wool"
    assert (
        _clean_materials_pollution("97% Cotton, 3% Elastane")
        == "97% Cotton, 3% Elastane"
    )


@pytest.mark.unit
def test_clean_materials_salvages_trailing_composition_from_editorial_block() -> None:
    """Some sites pull a long editorial/glossary block into the materials
    accordion (e.g. Todd Snyder seersucker page). The real fabric composition
    is appended at the end. Keep only the trailing composition slice.
    """
    editorial = (
        "The word seersucker originates from the Persian words shir and "
        "shakar, literally meaning milk and sugar, which presumably refers "
        "to the gritty texture (sugar) on the otherwise smooth (milk) cloth. "
        "Its texture is created by weaving on twin-beam looms at different "
        "speeds with a slack tension process that causes some threads to "
        "bunch up, giving the fabric an intentionally rumpled look. "
        "Traditional seersucker is often seen in blue-and-white stripes, "
        "but may be tonal. " * 3
    ) + "97% Cotton, 3% Elastane"

    cleaned = _clean_materials_pollution(editorial)

    assert "seersucker" not in cleaned.lower()
    assert "97% Cotton" in cleaned
    assert "3% Elastane" in cleaned


@pytest.mark.unit
def test_clean_materials_drops_long_editorial_with_no_composition() -> None:
    long_editorial = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30
    )
    assert _clean_materials_pollution(long_editorial) == ""


@pytest.mark.unit
def test_clean_materials_keeps_long_text_when_head_has_composition() -> None:
    head_with_compo = (
        "100% Cotton. " + "Some additional care notes that follow. " * 30
    )
    cleaned = _clean_materials_pollution(head_with_compo)
    # The salvage logic should NOT trigger when composition is in the head.
    assert "100% Cotton" in cleaned
