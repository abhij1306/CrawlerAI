from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config.evaluation import (
    EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
    EXTRACTION_V3_EXCLUDED_RESULT_DIRS,
    EXTRACTION_V3_LABEL_CORE_FIELDS,
    EXTRACTION_V3_LABEL_SCHEMA_VERSION,
    EXTRACTION_V3_VARIANT_BUCKETS,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = ROOT / "artifacts" / "runs" / "1"
DEFAULT_AUDIT_PATH = ROOT.parent / "chatgpt_audit" / "audit_data.json"
DEFAULT_LABEL_DIR = Path(__file__).resolve().parent / "labels"


@dataclass(frozen=True, slots=True)
class CorpusPage:
    result_id: int
    result_dir: Path
    url: str
    variant_bucket: str
    platform: str
    label_path: Path
    label: dict[str, Any] | None

    @property
    def is_verified(self) -> bool:
        return bool((self.label or {}).get("human_verified"))


def load_pages(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> tuple[CorpusPage, ...]:
    audit_pages = {
        int(page["dir"]): page
        for page in _load_json(audit_path).get("pages", [])
        if page.get("surface") == "detail"
        and int(page.get("dir", 0)) not in EXTRACTION_V3_EXCLUDED_RESULT_DIRS
    }
    pages: list[CorpusPage] = []
    for result_id in sorted(audit_pages):
        audit_page = audit_pages[result_id]
        label_path = label_dir / f"{result_id}.json"
        pages.append(
            CorpusPage(
                result_id=result_id,
                result_dir=run_dir / "results" / str(result_id),
                url=str(audit_page.get("url") or ""),
                variant_bucket=str(audit_page.get("variant_bucket") or "unknown"),
                platform=str(audit_page.get("platform") or "unknown"),
                label_path=label_path,
                label=_load_json(label_path) if label_path.exists() else None,
            )
        )
    return tuple(pages)


def build_label_proposal(page: CorpusPage, audit_page: dict[str, Any]) -> dict[str, Any]:
    record = _load_record(page.result_dir)
    first_record = record["records"][0] if record["records"] else {}
    structured = audit_page.get("structured") if isinstance(audit_page, dict) else {}
    return {
        "schema_version": EXTRACTION_V3_LABEL_SCHEMA_VERSION,
        "result_id": page.result_id,
        "surface": EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
        "url": page.url,
        "human_verified": False,
        "verification_notes": "Bootstrap proposal. Human must confirm before scoring as gold.",
        "metadata": {
            "platform": page.platform,
            "variant_bucket": page.variant_bucket,
        },
        "fields": {
            field: _proposal_value(field, first_record, structured)
            for field in EXTRACTION_V3_LABEL_CORE_FIELDS
        },
        "variants": list(first_record.get("variants") or []),
    }


def stats(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> dict[str, Any]:
    pages = load_pages(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)
    bucket_counts = {bucket: 0 for bucket in EXTRACTION_V3_VARIANT_BUCKETS}
    for page in pages:
        bucket_counts[page.variant_bucket] = bucket_counts.get(page.variant_bucket, 0) + 1
    verified = sum(1 for page in pages if page.is_verified)
    return {
        "surface": EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
        "registered": len(pages),
        "human_verified": verified,
        "unverified": len(pages) - verified,
        "missing_label_files": sum(1 for page in pages if page.label is None),
        "variant_buckets": bucket_counts,
        "valid": _validate_pages(pages),
    }


def write_proposals(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
) -> int:
    label_dir.mkdir(parents=True, exist_ok=True)
    audit_pages = {int(page["dir"]): page for page in _load_json(audit_path).get("pages", [])}
    written = 0
    for page in load_pages(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir):
        if page.label_path.exists():
            continue
        proposal = build_label_proposal(page, audit_pages[page.result_id])
        page.label_path.write_text(
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage extraction V3 eval corpus.")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--write-proposals", action="store_true")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH))
    parser.add_argument("--label-dir", default=str(DEFAULT_LABEL_DIR))
    parsed = parser.parse_args(argv)
    run_dir = Path(parsed.run_dir)
    audit_path = Path(parsed.audit_path)
    label_dir = Path(parsed.label_dir)
    if parsed.write_proposals:
        print(f"wrote {write_proposals(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir)} proposals")
    if parsed.stats or not parsed.write_proposals:
        print(json.dumps(stats(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir), indent=2, sort_keys=True))
    return 0


def _validate_pages(pages: tuple[CorpusPage, ...]) -> bool:
    for page in pages:
        label = page.label
        if label is None:
            continue
        if label.get("schema_version") != EXTRACTION_V3_LABEL_SCHEMA_VERSION:
            return False
        if label.get("surface") != EXTRACTION_V3_COMMERCE_DETAIL_SURFACE:
            return False
        if not isinstance(label.get("fields"), dict):
            return False
        if not isinstance(label.get("variants"), list):
            return False
    return True


def _load_record(result_dir: Path) -> dict[str, Any]:
    path = result_dir / "record.json"
    if not path.exists():
        return {"record_count": 0, "records": []}
    payload = _load_json(path)
    records = payload.get("records") if isinstance(payload, dict) else []
    return {
        "record_count": int(payload.get("record_count", len(records)) or 0),
        "records": records if isinstance(records, list) else [],
    }


def _proposal_value(field: str, record: dict[str, Any], structured: object) -> Any:
    if field == "images":
        image = record.get("image_url")
        return [image] if image else []
    if field == "category":
        return record.get("category") or (
            structured.get("category_breadcrumb") if isinstance(structured, dict) else None
        )
    return record.get(field) or (structured.get(field) if isinstance(structured, dict) else None)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
