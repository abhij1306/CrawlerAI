from __future__ import annotations

import pytest

from app.services.extract.record_overlay import overlay_record


@pytest.mark.unit
def test_overlay_record_deep_merges_structured_fields() -> None:
    result = overlay_record(
        {"nested": {"child": {"primary": "kept"}}},
        {"nested": {"child": {"secondary": "added"}}},
        deep_structured=True,
    )

    assert result == {
        "nested": {
            "child": {
                "primary": "kept",
                "secondary": "added",
            }
        }
    }


@pytest.mark.unit
def test_overlay_record_stops_deep_merge_at_max_depth() -> None:
    result = overlay_record(
        {"nested": {"child": {"primary": "kept"}}},
        {"nested": {"child": {"secondary": "not_added"}}},
        deep_structured=True,
        max_depth=0,
    )

    assert result == {"nested": {"child": {"primary": "kept"}}}
