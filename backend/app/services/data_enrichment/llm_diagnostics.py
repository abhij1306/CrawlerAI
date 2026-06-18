from __future__ import annotations

from app.models.data_enrichment import EnrichedProduct
from app.services.data_enrichment.deterministic import string_list
from app.services.shared.field_coerce import text_or_none


def build_llm_diagnostics(
    product: EnrichedProduct, payload: dict[str, object], applied_fields: list[str]
) -> dict[str, object]:
    return {
        "rejected_payload": rejected_llm_payload(payload, applied_fields),
    }


def rejected_llm_payload(
    payload: dict[str, object], applied_fields: list[str]
) -> dict[str, object]:
    applied = set(applied_fields)
    rejected: dict[str, object] = {}
    for key, value in payload.items():
        if key in applied or value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            if values := string_list(value, max_items=10, max_chars=60):
                rejected[str(key)] = values
            continue
        if text := text_or_none(value):
            rejected[str(key)] = text[:120]
    return rejected
