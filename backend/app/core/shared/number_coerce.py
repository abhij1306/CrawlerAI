from __future__ import annotations


def as_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
