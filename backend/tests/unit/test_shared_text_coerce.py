from __future__ import annotations

import pytest

from app.services.shared.text_coerce import (
    clean_text,
    coerce_long_text,
    coerce_text,
    is_null_text,
    is_title_noise,
    slug_tokens,
    strip_html_tags,
    text_or_none,
)


@pytest.mark.unit
def test_clean_text_normalizes_entities_whitespace_and_css_noise() -> None:
    assert clean_text("  A&nbsp;\n B  ") == "A B"
    assert clean_text(None) == ""
    assert clean_text(False) == ""
    assert clean_text("A\t\tB\r\nC") == "A B C"
    assert clean_text(".x{display:none} Product") == "Product"
    assert clean_text('Sleep Number Ultimate 12\\" Mattress') == 'Sleep Number Ultimate 12" Mattress'
    assert clean_text(r'meaning \\"Dragon Well\\" tea') == 'meaning "Dragon Well" tea'
    assert clean_text("SleepIQ\\u00ae score") == "SleepIQ® score"
    assert clean_text(r"Line 1\nLine 2") == "Line 1 Line 2"
    assert clean_text(r"Path\\to\\file") == r"Path\to\file"
    assert clean_text(r"Line 1\\nLine 2") == r"Line 1\nLine 2"


@pytest.mark.unit
def test_strip_and_coerce_html_text() -> None:
    assert strip_html_tags("<p>Hello <b>world</b></p>") == "Hello world"
    assert strip_html_tags("plain text") == "plain text"
    assert coerce_text("<p>Hello&nbsp;world</p>") == "Hello world"
    assert coerce_text("A&nbsp;B") == "A B"
    assert coerce_text({"x": 1}) == "{'x': 1}"
    assert coerce_long_text("<p>One</p><p>Two</p>") == "One Two"


@pytest.mark.unit
def test_literal_text_lists_and_empty_values() -> None:
    assert coerce_text("['Small', 'Large']") == "Small; Large"
    assert coerce_text("[True, {'bad': 1}, 'Good']") == "Good"
    assert coerce_text("[") == "["
    assert text_or_none(" \n ") is None


@pytest.mark.unit
def test_title_noise_and_slug_tokens() -> None:
    assert is_title_noise("undefined")
    assert is_title_noise("null")
    assert is_title_noise("12345")
    assert not is_title_noise("Cotton Shirt")
    assert slug_tokens("Café au lait") == ["caf", "au", "lait"]
    assert slug_tokens("Cotton-Shirt / Blue") == ["cotton", "shirt", "blue"]


@pytest.mark.unit
def test_is_null_text_normalizes_common_string_sentinels() -> None:
    assert is_null_text(" NULL ")
    assert is_null_text("undefined")
    assert is_null_text("N/A")
    assert is_null_text("- / null")
    assert not is_null_text("null leather finish")


@pytest.mark.unit
def test_coerce_brand_text_strips_marketing_tagline() -> None:
    """JSON-LD ``Brand.name`` sometimes includes a site tagline (Gymshark
    serves ``"Gymshark | We Do Gym"``). The trailing tagline must be dropped
    while real multi-word brands and single-word brands stay intact.
    """
    from app.services.shared.field_coerce_text import coerce_brand_text

    # Tagline after pipe is stripped.
    assert coerce_brand_text("Gymshark | We Do Gym") == "Gymshark"
    assert coerce_brand_text("Gymshark | We Do Gym.") == "Gymshark"
    # En-dash and em-dash separators also strip a multi-word tagline.
    assert (
        coerce_brand_text("Patagonia \u2013 Sustainable Outdoor") == "Patagonia"
    )
    # Region/storefront tokens were already handled by the existing suffix
    # regex; they keep working.
    assert coerce_brand_text("Brand | USA") == "Brand"
    # Real brands without a tagline pass through unchanged.
    assert coerce_brand_text("Tommy Hilfiger") == "Tommy Hilfiger"
    assert coerce_brand_text("Nike Inc.") == "Nike Inc."
    assert coerce_brand_text("Levi's") == "Levi's"
    # A single-word suffix is not assumed to be a tagline (could be a
    # legitimate brand-line marker); leave the value alone.
    assert coerce_brand_text("Gymshark | Single") == "Gymshark | Single"
