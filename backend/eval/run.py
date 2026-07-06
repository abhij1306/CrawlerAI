from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.config.evaluation import EXTRACTION_V3_BASELINE_SCHEMA_VERSION

from eval.corpus import DEFAULT_AUDIT_PATH, DEFAULT_LABEL_DIR, DEFAULT_RUN_DIR, load_pages
from eval.score import baseline_report, score_records_against_labels


DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "baseline.json"


def run_baseline(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    out: Path | None = DEFAULT_REPORT,
) -> dict[str, Any]:
    report = {
        "schema_version": EXTRACTION_V3_BASELINE_SCHEMA_VERSION,
        "engine": "baseline",
        **baseline_report(run_dir=run_dir, audit_path=audit_path),
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def run_label_score(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> dict[str, Any]:
    pages = load_pages(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)
    verified_pages = tuple(page for page in pages if page.is_verified)
    report = score_records_against_labels(verified_pages).to_dict()
    report["verified_pages"] = len(verified_pages)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run extraction V3 eval.")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--score-labels", action="store_true")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH))
    parser.add_argument("--label-dir", default=str(DEFAULT_LABEL_DIR))
    parser.add_argument("--out", default=str(DEFAULT_REPORT))
    parsed = parser.parse_args(argv)
    run_dir = Path(parsed.run_dir)
    audit_path = Path(parsed.audit_path)
    if parsed.baseline:
        report = run_baseline(run_dir=run_dir, audit_path=audit_path, out=Path(parsed.out))
    elif parsed.score_labels:
        report = run_label_score(
            run_dir=run_dir,
            audit_path=audit_path,
            label_dir=Path(parsed.label_dir),
        )
    else:
        parser.error("choose --baseline or --score-labels")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
