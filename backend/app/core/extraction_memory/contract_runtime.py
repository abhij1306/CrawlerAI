"""Frozen executable-recipe selection for the recipe-only runtime."""

from __future__ import annotations

import re
from typing import Any

from app.core.config.extraction_memory import EXTRACTION_MEMORY_STATUS_SUSPENDED
from app.core.extraction_memory.templates import normalize_route


def select_active_recipe(
    snapshot: dict[str, Any],
    *,
    surface: str,
    url: str,
    template_signature: str = "",
) -> dict[str, Any] | None:
    """Select one executable-v2 release entry before discovery runs."""
    if (
        snapshot.get("schema_version") != "release.v2"
        or snapshot.get("surface") != surface
    ):
        return None
    route = _normalized_recipe_route(normalize_route(url, surface))
    templates = [
        row
        for row in snapshot.get("templates", ())
        if isinstance(row, dict)
        and isinstance(row.get("compiled_recipe"), dict)
        and str(row.get("status") or "active") != EXTRACTION_MEMORY_STATUS_SUSPENDED
    ]
    if template_signature:
        exact = next(
            (
                row
                for row in templates
                if str(row.get("template_signature") or "") == template_signature
            ),
            None,
        )
        if exact is not None:
            return exact
    return next(
        (
            row
            for row in templates
            if _normalized_recipe_route(str(row.get("route_pattern") or "/")) == route
        ),
        None,
    )


def _normalized_recipe_route(value: str) -> str:
    return re.sub(r"\{[^/{}]+\}", "{id}", str(value or "/"))
