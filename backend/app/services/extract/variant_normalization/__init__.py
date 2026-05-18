from __future__ import annotations

from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.variant_normalization import (
    backfill,
    contract,
    deduplication,
    hydration,
    sanitization,
)

__all__ = ("normalize_variant_record",)

# Underscore-prefixed stage functions are intentionally imported from sibling
# modules here. They are stable only for this internal normalization pipeline.


def normalize_variant_record(record: dict[str, Any], *, finalize_contract: bool = True) -> None:
    hydration._hydrate_variant_axes(record)
    sanitization._sanitize_variant_axes(record)
    deduplication._dedupe_and_prune_variant_rows(record)
    backfill._backfill_variant_context(record)
    backfill._backfill_parent_scalar_axes_from_variants(record)
    sanitization._drop_polluted_parent_scalar_axes(record)
    if finalize_contract:
        try:
            raw_limit = crawler_runtime_settings.detail_max_variant_rows
            max_rows = int(raw_limit) if raw_limit is not None else 0
        except (TypeError, ValueError):
            max_rows = 0
        contract.finalize(record, max_rows=max_rows)
