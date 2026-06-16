from __future__ import annotations

from typing import Any

from app.services.acquisition.browser_page_helpers import object_int as _int_or_zero


def browser_runtime_snapshot_from_runtimes(
    runtimes: list[Any],
    *,
    default_capacity: int,
) -> dict[str, int | bool]:
    if not runtimes:
        return {
            "ready": False,
            "size": 0,
            "max_size": default_capacity,
            "active": 0,
            "queued": 0,
            "capacity": default_capacity,
        }
    snapshots = [runtime.snapshot() for runtime in runtimes]
    return {
        "ready": any(bool(snapshot.get("ready")) for snapshot in snapshots),
        "size": sum(_int_or_zero(snapshot.get("size")) for snapshot in snapshots),
        "max_size": sum(_snapshot_count(snapshot, "max_size", "capacity") for snapshot in snapshots),
        "active": sum(_int_or_zero(snapshot.get("active")) for snapshot in snapshots),
        "queued": sum(_int_or_zero(snapshot.get("queued")) for snapshot in snapshots),
        "capacity": sum(_snapshot_count(snapshot, "capacity", "max_size") for snapshot in snapshots),
        "total_contexts_created": sum(
            _int_or_zero(snapshot.get("total_contexts_created"))
            for snapshot in snapshots
        ),
        "browser_lifetime_seconds": max(
            _int_or_zero(snapshot.get("browser_lifetime_seconds"))
            for snapshot in snapshots
        ),
    }


def _snapshot_count(snapshot: dict[str, object], primary_key: str, fallback_key: str) -> int:
    primary = _int_or_zero(snapshot.get(primary_key))
    if primary:
        return primary
    return _int_or_zero(snapshot.get(fallback_key))
