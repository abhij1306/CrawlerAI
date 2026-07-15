"""Load fixture HTML + label JSON pairs for an evaluation surface.

A surface's corpus lives under two sibling directories inside this package::

    backend/eval/fixtures/<surface>/<stem>.html
    backend/eval/labels/<surface>/<stem>.json

Each ``<stem>.html`` fixture is paired with the ``<stem>.json`` label document
that carries its ground-truth expected facts. A label document is either a
JSON list of record objects, or a JSON object with a ``records`` key holding
that list. Every record maps a field name to its emitted string value(s).

The loader returns a typed, deterministic structure (fixtures sorted by stem)
so scoring is reproducible run to run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config.evaluation import (
    EVAL_HARNESS_FIXTURE_SUFFIX,
    EVAL_HARNESS_FIXTURES_DIRNAME,
    EVAL_HARNESS_LABEL_RECORDS_KEY,
    EVAL_HARNESS_LABEL_SUFFIX,
    EVAL_HARNESS_LABELS_DIRNAME,
)

# A single labeled record: field name -> emitted string value or list of them.
FieldValue = str | list[str]
Record = dict[str, FieldValue]

# The package root (``backend/eval``); fixture/label directories hang off it.
PACKAGE_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class FixtureCase:
    """One fixture HTML page paired with its ground-truth expected facts."""

    stem: str
    html: str
    expected_facts: list[Record]


def _coerce_records(payload: object, source: Path) -> list[Record]:
    """Normalize a parsed label document into a list of record dicts."""
    if isinstance(payload, dict) and EVAL_HARNESS_LABEL_RECORDS_KEY in payload:
        payload = payload[EVAL_HARNESS_LABEL_RECORDS_KEY]
    if not isinstance(payload, list):
        raise ValueError(
            f"label document {source} must be a list of records "
            f"(or an object with a '{EVAL_HARNESS_LABEL_RECORDS_KEY}' list)"
        )
    records: list[Record] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ValueError(
                f"label document {source} record #{index} must be an object"
            )
        records.append(dict(record))
    return records


def load_surface_corpus(
    surface: str,
    *,
    root: Path | None = None,
) -> list[FixtureCase]:
    """Load every fixture/label pair for ``surface``.

    Args:
        surface: Surface key (e.g. ``"ecommerce_listing"``); also the fixture
            and label sub-directory name.
        root: Optional package root override (used by tests to point at a
            temporary corpus). Defaults to this package's directory.

    Returns:
        Fixtures sorted by stem for deterministic ordering. Empty list when the
        surface has no fixtures directory yet (fixtures are authored later).
    """
    base = root or PACKAGE_ROOT
    fixtures_dir = base / EVAL_HARNESS_FIXTURES_DIRNAME / surface
    labels_dir = base / EVAL_HARNESS_LABELS_DIRNAME / surface

    if not fixtures_dir.is_dir():
        return []

    cases: list[FixtureCase] = []
    for fixture_path in sorted(fixtures_dir.glob(f"*{EVAL_HARNESS_FIXTURE_SUFFIX}")):
        stem = fixture_path.stem
        label_path = labels_dir / f"{stem}{EVAL_HARNESS_LABEL_SUFFIX}"
        if not label_path.is_file():
            raise FileNotFoundError(
                f"fixture {fixture_path} has no paired label at {label_path}"
            )
        html = fixture_path.read_text(encoding="utf-8")
        payload = json.loads(label_path.read_text(encoding="utf-8"))
        expected = _coerce_records(payload, label_path)
        cases.append(FixtureCase(stem=stem, html=html, expected_facts=expected))
    return cases
