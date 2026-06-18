from __future__ import annotations

import json

from app.services.shared.field_coerce import STRUCTURED_MULTI_FIELDS


def candidate_fingerprint(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def add_candidate(
    candidates: dict[str, list[object]],
    field_name: str,
    value: object,
) -> int:
    if value in (None, "", [], {}):
        return 0
    bucket = candidates.setdefault(field_name, [])
    values = (
        list(value)
        if field_name in STRUCTURED_MULTI_FIELDS and isinstance(value, list)
        else [value]
    )
    seen = {candidate_fingerprint(existing) for existing in bucket}
    added = 0
    for item in values:
        if item in (None, "", [], {}):
            continue
        fingerprint = candidate_fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bucket.append(item)
        added += 1
    return added
