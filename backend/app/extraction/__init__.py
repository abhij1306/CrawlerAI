"""Canonical extraction package."""

from typing import TYPE_CHECKING, Any

from app.extraction.contracts import CapabilityRequest
from app.extraction.surfaces import Surface, parse_surface, surface_spec

if TYPE_CHECKING:
    from app.extraction.engine import extract


def __getattr__(name: str) -> Any:
    """Lazily expose heavy extraction entry points without import cycles."""
    if name == "extract":
        from app.extraction.engine import extract

        return extract
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CapabilityRequest",
    "Surface",
    "extract",
    "parse_surface",
    "surface_spec",
]
