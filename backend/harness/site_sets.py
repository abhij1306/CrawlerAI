from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, cast

from app.extraction.surfaces import parse_surface


def _safe_int(value: object) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _nonempty_strings(value: object) -> list[str]:
    return [
        str(item or "").strip()
        for item in _object_list(value)
        if str(item or "").strip()
    ]


__all__ = [
    "build_explicit_sites",
    "load_site_set",
    "parse_test_sites_markdown",
    "require_explicit_surface",
]


def require_explicit_surface(explicit_surface: object | None = None) -> str:
    explicit = str(explicit_surface or "").strip().lower()
    if explicit:
        return parse_surface(explicit).value
    raise ValueError("surface is required")


def build_explicit_sites(
    urls: list[str],
    *,
    explicit_surfaces: list[str] | None = None,
) -> list[dict[str, str]]:
    normalized_urls = [
        str(value or "").strip() for value in (urls or []) if str(value or "").strip()
    ]
    normalized_surfaces = [
        str(value or "").strip()
        for value in (explicit_surfaces or [])
        if str(value or "").strip()
    ]
    if normalized_surfaces and len(normalized_surfaces) != len(normalized_urls):
        raise ValueError("Explicit URL and surface counts must match")
    rows: list[dict[str, str]] = []
    for index, url in enumerate(normalized_urls):
        explicit_surface = (
            normalized_surfaces[index] if index < len(normalized_surfaces) else ""
        )
        rows.append(
            {
                "name": url,
                "url": url,
                "surface": require_explicit_surface(explicit_surface),
            }
        )
    return rows


def load_site_set(path: Path, *, site_set_name: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in site set file {path}: {exc.msg}") from exc
    defaults, sites = _site_set_payload(payload, path=path, site_set_name=site_set_name)
    rows: list[dict[str, object]] = []
    for item in sites:
        row = _site_set_row(item, defaults=defaults)
        if row is not None:
            rows.append(row)
    return rows


def _site_set_payload(
    payload: object, *, path: Path, site_set_name: str
) -> tuple[dict[str, object], list[object]]:
    if isinstance(payload, dict) and isinstance(payload.get("site_sets"), dict):
        site_set = payload["site_sets"].get(site_set_name)
        if not isinstance(site_set, dict):
            raise ValueError(f"Unknown site set: {site_set_name}")
        defaults = _object_dict(site_set.get("defaults"))
        sites = site_set.get("sites")
        if not isinstance(sites, list):
            raise ValueError(f"Site set {site_set_name} has no sites list")
    elif isinstance(payload, dict) and isinstance(payload.get("sites"), list):
        manifest_name = str(payload.get("name") or path.stem).strip()
        if site_set_name not in {"", manifest_name, path.stem}:
            raise ValueError(f"Unknown site set: {site_set_name}")
        defaults = _object_dict(payload.get("defaults"))
        sites = payload["sites"]
    else:
        raise ValueError(f"Invalid site-set payload in {path}")
    return defaults, sites


def _site_set_row(
    item: object, *, defaults: dict[str, object]
) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    site = {**defaults, **item}
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    row: dict[str, object] = {
        "name": str(site.get("name") or url).strip(),
        "url": url,
        "surface": require_explicit_surface(site.get("surface")),
        "bucket": str(site.get("bucket") or "").strip().lower() or None,
        "expected_failure_modes": _nonempty_strings(site.get("expected_failure_modes")),
        "artifact_run_id": _safe_int(site.get("artifact_run_id")) or None,
        "seed_failure_mode": str(site.get("seed_failure_mode") or "").strip().lower()
        or None,
        "quality_expectations": {
            **_object_dict(defaults.get("quality_expectations")),
            **_object_dict(item.get("quality_expectations")),
        },
    }
    row.update(_optional_site_values(site))
    return row


def _optional_site_values(site: dict[str, object]) -> dict[str, object]:
    optional = {
        "gate": str(site.get("gate") or "").strip().lower() or None,
        "expected": _object_dict(site.get("expected")) or None,
        "known_failure_mode": str(site.get("known_failure_mode") or "").strip() or None,
    }
    return {key: value for key, value in optional.items() if value is not None}


def parse_test_sites_markdown(path: Path, *, start_line: int) -> list[dict[str, str]]:
    if not isinstance(start_line, int) or start_line < 1:
        raise ValueError("parse_test_sites_markdown start_line must be an integer >= 1")
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[start_line - 1 :]:
        row = _markdown_site_row(line)
        if row is not None:
            rows.append(row)
    return rows


def _markdown_site_row(line: object) -> dict[str, str] | None:
    value = html.unescape(str(line or "").strip())
    if not value or value.startswith(("http://", "https://")):
        return None
    if not value.startswith("|") or "http" not in value:
        return None
    cells = [cell.strip() for cell in value.strip("|").split("|")]
    url = next(
        (
            match.group(0).strip().rstrip("`.,;:)")
            for cell in cells
            if (match := re.search(r"https?://[^`\s|>]+", cell))
        ),
        "",
    )
    surface_aliases = {
        "listing": "ecommerce_listing",
        "ajax_listing": "ecommerce_listing",
        "infinite_scroll": "ecommerce_listing",
        "spa_listing": "ecommerce_listing",
        "detail": "ecommerce_detail",
        "spa_detail": "ecommerce_detail",
    }
    normalized_cells = (
        re.sub(r"[^a-z0-9]+", "_", cell.lower()).strip("_") for cell in cells[1:]
    )
    surface = next(
        (surface_aliases[cell] for cell in normalized_cells if cell in surface_aliases),
        "",
    )
    if not url:
        return None
    return {"name": url, "url": url, "surface": require_explicit_surface(surface)}
