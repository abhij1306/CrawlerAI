from __future__ import annotations

from typing import Any


def record_score(record: dict[str, Any]) -> int:
    return sum(
        1
        for key, value in record.items()
        if key not in {"source_url", "url", "_source"}
        and value not in (None, "", [], {})
    )
