from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def content_sha256(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else str(value or "").encode("utf-8")
    return hashlib.sha256(data).hexdigest()
