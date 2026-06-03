from __future__ import annotations

import re


def query_dimension_is_tiny(query: str) -> bool:
    for key in ("hei", "height", "h", "wid", "width", "w"):
        match = re.search(rf"(?:^|&){key}=(\d+)(?:&|$)", query, re.I)
        if match is not None and int(match.group(1)) <= 120:
            return True
    return False
