from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "product_intelligence"
_BELK_BRANDS_FILE = _DATA_DIR / "belk_brands.txt"
_BELK_EXCLUSIVE_BRANDS_FILE = _DATA_DIR / "belk_exclusive_brands.txt"
_MIN_BRAND_KEY_LENGTH = 3


@lru_cache(maxsize=1)
def belk_brand_entries() -> tuple[tuple[str, str], ...]:
    return _dedupe_entries(
        (*_load_brand_entries(_BELK_BRANDS_FILE), *_load_brand_entries(_BELK_EXCLUSIVE_BRANDS_FILE))
    )


@lru_cache(maxsize=1)
def belk_exclusive_brand_keys() -> frozenset[str]:
    return frozenset(key for key, _ in _load_brand_entries(_BELK_EXCLUSIVE_BRANDS_FILE))


# Minimum length for compact (spaceless) brand matching to avoid false positives.
_MIN_COMPACT_MATCH_LENGTH = 5


def infer_belk_brand(*values: object) -> str:
    haystack = _registry_key(" ".join(str(value or "") for value in values))
    if not haystack:
        return ""
    padded = f" {haystack} "
    compact = haystack.replace(" ", "")
    for key, display in belk_brand_entries():
        no_and_key = key.replace(" and ", " ")
        if f" {key} " in padded or f" {no_and_key} " in padded:
            return display
        compact_key = key.replace(" ", "")
        compact_no_and_key = no_and_key.replace(" ", "")
        if len(compact_key) >= _MIN_COMPACT_MATCH_LENGTH and compact_key in compact:
            return display
        if len(compact_no_and_key) >= _MIN_COMPACT_MATCH_LENGTH and compact_no_and_key in compact:
            return display
    return ""


def infer_belk_brand_prefix(value: object) -> str:
    haystack = _registry_key(value)
    if not haystack:
        return ""
    for key, display in belk_brand_entries():
        no_and_key = key.replace(" and ", " ")
        if haystack == key or haystack.startswith(f"{key} "):
            return display
        if haystack == no_and_key or haystack.startswith(f"{no_and_key} "):
            return display
    return ""


def is_belk_exclusive_brand(value: object) -> bool:
    return _registry_key(value) in belk_exclusive_brand_keys()


def registry_key(value: object) -> str:
    return _registry_key(value)


def _load_brand_entries(path: Path) -> tuple[tuple[str, str], ...]:
    if not path.exists():
        return ()
    seen: set[str] = set()
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        display = line.strip()
        key = _registry_key(display)
        if len(key) < _MIN_BRAND_KEY_LENGTH or key in seen:
            continue
        seen.add(key)
        entries.append((key, display))
    return tuple(sorted(entries, key=lambda item: (len(item[0]), item[0]), reverse=True))


def _dedupe_entries(entries: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    by_key: dict[str, str] = {}
    for key, display in entries:
        by_key.setdefault(key, display)
    return tuple(
        sorted(by_key.items(), key=lambda item: (len(item[0]), item[0]), reverse=True)
    )


def _registry_key(value: object) -> str:
    text = str(value or "").casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())
