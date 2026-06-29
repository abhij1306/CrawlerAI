from __future__ import annotations

import pytest

from app.acquisition.browser_detail import _candidate_is_admitted


def _admit(
    snapshot: dict[str, object], *, selector: str = "button[aria-controls]"
) -> bool:
    admitted, _key, _label = _candidate_is_admitted(
        snapshot,
        selector=selector,
        keywords=("spec", "detail"),
        requested_keywords=(),
        requested_fields=None,
    )
    return admitted


@pytest.mark.component
def test_aria_controls_only_button_is_admitted() -> None:
    # A genuine in-page accordion toggle (button + aria-controls, no navigation)
    # must still be clicked to reveal collapsed spec content.
    snapshot = {
        "label": "specifications",
        "tag_name": "button",
        "aria_controls": "panel-specs",
        "visible": True,
        "actionable": True,
    }

    assert _admit(snapshot) is True


@pytest.mark.component
def test_anchor_with_target_blank_and_aria_controls_is_not_admitted() -> None:
    # An anchor that opens a new browsing context must never be clicked during
    # detail expansion, even when it carries aria-controls — clicking it spawns
    # the "flash open then close" tab the popup guard would otherwise reap.
    snapshot = {
        "label": "specifications",
        "tag_name": "a",
        "href": "#",
        "target": "_blank",
        "aria_controls": "panel-specs",
        "visible": True,
        "actionable": True,
    }

    assert _admit(snapshot) is False


@pytest.mark.component
def test_anchor_with_real_link_and_aria_controls_is_not_admitted() -> None:
    # A true http(s) destination is navigational even with aria-controls; the
    # old escape hatch (`and not aria_controls`) used to admit these and let
    # them navigate/open a tab.
    snapshot = {
        "label": "view details",
        "tag_name": "a",
        "href": "https://example.com/products/widget",
        "aria_controls": "panel-specs",
        "visible": True,
        "actionable": True,
    }

    assert _admit(snapshot) is False


@pytest.mark.component
def test_in_page_hash_anchor_with_aria_controls_stays_admitted() -> None:
    # `<a href="#" aria-controls=...>` toggles are in-page, not navigational, so
    # they remain admitted for expansion.
    snapshot = {
        "label": "more specifications",
        "tag_name": "a",
        "href": "#specs",
        "aria_controls": "panel-specs",
        "visible": True,
        "actionable": True,
    }

    assert _admit(snapshot) is True
