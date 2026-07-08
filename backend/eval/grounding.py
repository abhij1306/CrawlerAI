from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.extraction.documents import HtmlDocument
from app.extraction.representation import build_scoped_flat_map, ground

from eval.corpus import (
    DEFAULT_AUDIT_PATH,
    DEFAULT_LABEL_DIR,
    DEFAULT_RUN_DIR,
    load_pages,
)


DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "grounding.json"
SKIPPED_GROUNDING_FIELDS = frozenset({"images", "category"})


def grounding_report(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> dict[str, Any]:
    pages = tuple(
        page
        for page in load_pages(
            run_dir=run_dir,
            audit_path=audit_path,
            label_dir=label_dir,
        )
        if page.is_verified
    )
    field_counts: dict[str, Counter[str]] = {}
    examples: list[dict[str, object]] = []
    for page in pages:
        html_path = page.result_dir / "page.html"
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        scoped = build_scoped_flat_map(HtmlDocument("html", html))
        for field, value in (page.label or {}).get("fields", {}).items():
            if field in SKIPPED_GROUNDING_FIELDS or not _groundable(value):
                continue
            result = ground(value, scoped.flat_map)
            counts = field_counts.setdefault(field, Counter())
            counts[result.match_type] += 1
            if not result.grounded and len(examples) < 20:
                examples.append(
                    {
                        "dir": page.result_id,
                        "field": field,
                        "value": _preview(value),
                    }
                )
    by_field = {
        field: _field_summary(counts) for field, counts in sorted(field_counts.items())
    }
    total: Counter[str] = Counter()
    for counts in field_counts.values():
        total.update(counts)
    return {
        "verified_pages": len(pages),
        "field_grounding": by_field,
        "grounded_values": int(total["exact"] + total["normalized"]),
        "ungrounded_values": int(total["none"]),
        "grounding_failure_rate": _ratio(total["none"], sum(total.values())),
        "ungrounded_examples": examples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate grounding coverage for extraction V3 labels."
    )
    parser.add_argument("--verified-labels", action="store_true")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH))
    parser.add_argument("--label-dir", default=str(DEFAULT_LABEL_DIR))
    parser.add_argument("--out", default=str(DEFAULT_REPORT))
    parsed = parser.parse_args(argv)
    if not parsed.verified_labels:
        parser.error("choose --verified-labels")
    report = grounding_report(
        run_dir=Path(parsed.run_dir),
        audit_path=Path(parsed.audit_path),
        label_dir=Path(parsed.label_dir),
    )
    out = Path(parsed.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _field_summary(counts: Counter[str]) -> dict[str, float | int]:
    exact = int(counts["exact"])
    normalized = int(counts["normalized"])
    none = int(counts["none"])
    total = exact + normalized + none
    return {
        "exact": exact,
        "normalized": normalized,
        "none": none,
        "grounding_rate": _ratio(exact + normalized, total),
    }


def _groundable(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (int, float))


def _preview(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= 120 else f"{text[:117]}..."


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
