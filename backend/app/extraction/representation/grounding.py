from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.core.config.evaluation import EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS
from app.extraction.representation.flat_map import FlatMap


@dataclass(frozen=True, slots=True)
class GroundingResult:
    grounded: bool
    match_type: Literal["exact", "normalized", "none"]
    source_path: str | None = None


def ground(
    value: object,
    flat_map: FlatMap,
    sources: tuple[str, ...] | list[str] | None = None,
) -> GroundingResult:
    text = str(value or "").strip()
    if not text:
        return GroundingResult(False, "none", None)
    paths = tuple(sources or flat_map.keys())
    exact = _find_exact(text, flat_map, paths)
    if exact is not None:
        return GroundingResult(True, "exact", exact)
    normalized = _normalize(text)
    for path in paths:
        source_text = flat_map.get(path)
        if source_text is None:
            continue
        if normalized and normalized in _normalize(source_text):
            return GroundingResult(True, "normalized", path)
    return GroundingResult(False, "none", None)


def _find_exact(text: str, flat_map: FlatMap, paths: tuple[str, ...]) -> str | None:
    needle = text.casefold()
    for path in paths:
        source_text = flat_map.get(path)
        if source_text is not None and needle in source_text.casefold():
            return path
    return None


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    for symbol, replacement in EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS.items():
        text = text.replace(symbol, f" {replacement} ")
    text = re.sub(r"(?<=\d)[,\s](?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=\d)\.(?=\d{2}\b)", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text
