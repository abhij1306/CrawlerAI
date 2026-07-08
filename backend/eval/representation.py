from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.config.evaluation import EXTRACTION_V3_MAX_INPUT_TOKENS
from app.extraction.documents import HtmlDocument
from app.extraction.representation import build_scoped_flat_map

from eval.corpus import DEFAULT_RUN_DIR


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_SUMMARY = ROOT / "chatgpt_audit" / "summary.json"
DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "representation.json"


def audit_sample_report(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_summary_path: Path = DEFAULT_AUDIT_SUMMARY,
) -> dict[str, Any]:
    samples = _load_samples(audit_summary_path)
    rows = []
    for sample in samples:
        result_id = int(sample["dir"])
        html_path = run_dir / "results" / str(result_id) / "page.html"
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        scoped = build_scoped_flat_map(HtmlDocument("html", html))
        rows.append(
            {
                "dir": result_id,
                "expected_scoped_tokens": sample.get("flatmap_scoped"),
                "expected_full_tokens": sample.get("flatmap_full"),
                "observed_tokens": scoped.token_count,
                "entry_count": len(scoped.flat_map),
                "scope_path": scoped.scope_path,
                "fallback_reason": scoped.fallback_reason,
                "vision_recommended": scoped.vision_recommended,
                "chunk_count": len(scoped.chunks),
                "under_token_cap": scoped.token_count <= EXTRACTION_V3_MAX_INPUT_TOKENS,
                "non_empty": bool(scoped.flat_map),
            }
        )
    return {
        "sample_count": len(rows),
        "all_non_empty": all(row["non_empty"] for row in rows),
        "all_under_token_cap": all(row["under_token_cap"] for row in rows),
        "fallback_dirs": [
            row["dir"] for row in rows if row["fallback_reason"] is not None
        ],
        "vision_dirs": [row["dir"] for row in rows if row["vision_recommended"]],
        "samples": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate extraction V3 flat-map representation."
    )
    parser.add_argument("--audit-samples", action="store_true")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-summary", default=str(DEFAULT_AUDIT_SUMMARY))
    parser.add_argument("--out", default=str(DEFAULT_REPORT))
    parsed = parser.parse_args(argv)
    if not parsed.audit_samples:
        parser.error("choose --audit-samples")
    report = audit_sample_report(
        run_dir=Path(parsed.run_dir),
        audit_summary_path=Path(parsed.audit_summary),
    )
    out = Path(parsed.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _load_samples(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = (
        payload.get("representation_tokens") if isinstance(payload, dict) else None
    )
    if not isinstance(samples, list):
        return []
    return [sample for sample in samples if isinstance(sample, dict)]


if __name__ == "__main__":
    raise SystemExit(main())
