from __future__ import annotations

from app.core.config.extraction_rules import AVAILABILITY_CANONICAL_ENUM
from app.extraction.contracts import (
    CommerceDetailRecord,
    CommerceVariantRecord,
)


def typed_detail_record(record: dict[str, object]) -> CommerceDetailRecord:
    cleaned = {
        key: value for key, value in record.items() if value not in (None, "", [], {})
    }
    variants = cleaned.get("variants")
    if isinstance(variants, list):
        cleaned["variants"] = tuple(
            CommerceVariantRecord.model_validate(row).model_dump(exclude_none=True)
            for row in variants
            if isinstance(row, dict)
        )
    return CommerceDetailRecord.model_validate(cleaned)


def public_availability(value: object) -> str:
    text = str(value or "").strip()
    if text in _PUBLIC_AVAILABILITY_ENUM:
        return text
    return ""


_PUBLIC_AVAILABILITY_ENUM = frozenset(AVAILABILITY_CANONICAL_ENUM)
