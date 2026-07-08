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
    EXTRACTION_V3_MIN_HUMAN_LABELS_PER_NEW_SURFACE,
    EXTRACTION_V3_SURFACE_LABEL_FIELDS,
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
    surface: str
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
    surface: str = EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
) -> tuple[CorpusPage, ...]:
    surface = _normalize_surface(surface)
    if surface != EXTRACTION_V3_COMMERCE_DETAIL_SURFACE:
        return _load_surface_label_pages(
            run_dir=run_dir, label_dir=label_dir, surface=surface
        )
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
                surface=surface,
                url=str(audit_page.get("url") or ""),
                variant_bucket=str(audit_page.get("variant_bucket") or "unknown"),
                platform=str(audit_page.get("platform") or "unknown"),
                label_path=label_path,
                label=_load_json(label_path) if label_path.exists() else None,
            )
        )
    return tuple(pages)


def build_label_proposal(
    page: CorpusPage, audit_page: dict[str, Any]
) -> dict[str, Any]:
    record = _load_record(page.result_dir)
    first_record = record["records"][0] if record["records"] else {}
    structured = audit_page.get("structured") if isinstance(audit_page, dict) else {}
    fields = EXTRACTION_V3_SURFACE_LABEL_FIELDS.get(
        page.surface, EXTRACTION_V3_LABEL_CORE_FIELDS
    )
    return {
        "schema_version": EXTRACTION_V3_LABEL_SCHEMA_VERSION,
        "result_id": page.result_id,
        "surface": page.surface,
        "url": page.url,
        "human_verified": False,
        "verification_notes": "Bootstrap proposal. Human must confirm before scoring as gold.",
        "metadata": {
            "platform": page.platform,
            "variant_bucket": page.variant_bucket,
        },
        "fields": {
            field: _proposal_value(field, first_record, structured) for field in fields
        },
        "variants": list(first_record.get("variants") or []),
    }


def stats(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
    surface: str = EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
) -> dict[str, Any]:
    surface = _normalize_surface(surface)
    pages = load_pages(
        run_dir=run_dir, audit_path=audit_path, label_dir=label_dir, surface=surface
    )
    bucket_counts = {bucket: 0 for bucket in EXTRACTION_V3_VARIANT_BUCKETS}
    for page in pages:
        bucket_counts[page.variant_bucket] = (
            bucket_counts.get(page.variant_bucket, 0) + 1
        )
    verified = sum(1 for page in pages if page.is_verified)
    target = (
        0
        if surface == EXTRACTION_V3_COMMERCE_DETAIL_SURFACE
        else EXTRACTION_V3_MIN_HUMAN_LABELS_PER_NEW_SURFACE
    )
    return {
        "surface": surface,
        "registered": len(pages),
        "human_verified": verified,
        "unverified": len(pages) - verified,
        "missing_label_files": sum(1 for page in pages if page.label is None),
        "target_human_verified": target,
        "ready_for_gate": target == 0 or verified >= target,
        "variant_buckets": bucket_counts,
        "valid": _validate_pages(pages),
    }


def write_proposals(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
    label_dir: Path = DEFAULT_LABEL_DIR,
    surface: str = EXTRACTION_V3_COMMERCE_DETAIL_SURFACE,
) -> int:
    surface = _normalize_surface(surface)
    if surface != EXTRACTION_V3_COMMERCE_DETAIL_SURFACE:
        return _write_surface_proposals(
            run_dir=run_dir, label_dir=label_dir, surface=surface
        )
    label_dir.mkdir(parents=True, exist_ok=True)
    audit_pages = {
        int(page["dir"]): page for page in _load_json(audit_path).get("pages", [])
    }
    written = 0
    for page in load_pages(
        run_dir=run_dir, audit_path=audit_path, label_dir=label_dir, surface=surface
    ):
        if page.label_path.exists():
            continue
        proposal = build_label_proposal(page, audit_pages[page.result_id])
        page.label_path.write_text(
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def _write_surface_proposals(*, run_dir: Path, label_dir: Path, surface: str) -> int:
    surface_dir = label_dir / surface
    surface_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for result_dir in _result_dirs(run_dir):
        label_path = surface_dir / f"{result_dir.name}.json"
        if label_path.exists():
            continue
        page = _captured_surface_page(
            result_dir=result_dir,
            surface=surface,
            label_path=label_path,
        )
        if page is None:
            continue
        proposal = build_label_proposal(page, {})
        records = _load_record(result_dir)["records"]
        if "listing" in surface:
            proposal["records"] = records
        label_path.write_text(
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def _captured_surface_page(
    *, result_dir: Path, surface: str, label_path: Path
) -> CorpusPage | None:
    record = _load_record(result_dir)
    if not record["records"]:
        return None
    return CorpusPage(
        result_id=int(result_dir.name),
        result_dir=result_dir,
        surface=surface,
        url=_captured_url(result_dir, record),
        variant_bucket="unknown",
        platform=_captured_platform(result_dir),
        label_path=label_path,
        label=None,
    )


def _result_dirs(run_dir: Path) -> tuple[Path, ...]:
    results_dir = run_dir / "results"
    if not results_dir.exists():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in results_dir.iterdir()
                if path.is_dir() and path.name.isdigit()
            ),
            key=lambda path: int(path.name),
        )
    )


def _captured_url(result_dir: Path, record: dict[str, Any]) -> str:
    first_record = record["records"][0] if record["records"] else {}
    diagnose = _load_optional_json(result_dir / "diagnose.json")
    acquisition = diagnose.get("acquisition") if isinstance(diagnose, dict) else {}
    if isinstance(acquisition, dict) and acquisition.get("final_url"):
        return str(acquisition["final_url"])
    return str(first_record.get("url") or "")


def _captured_platform(result_dir: Path) -> str:
    diagnose = _load_optional_json(result_dir / "diagnose.json")
    acquisition = diagnose.get("acquisition") if isinstance(diagnose, dict) else {}
    if isinstance(acquisition, dict) and acquisition.get("platform_family"):
        return str(acquisition["platform_family"])
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage extraction V3 eval corpus.")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--write-proposals", action="store_true")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--audit-path", default=str(DEFAULT_AUDIT_PATH))
    parser.add_argument("--label-dir", default=str(DEFAULT_LABEL_DIR))
    parser.add_argument("--surface", default=EXTRACTION_V3_COMMERCE_DETAIL_SURFACE)
    parsed = parser.parse_args(argv)
    run_dir = Path(parsed.run_dir)
    audit_path = Path(parsed.audit_path)
    label_dir = Path(parsed.label_dir)
    if parsed.write_proposals:
        print(
            "wrote "
            f"{write_proposals(run_dir=run_dir, audit_path=audit_path, label_dir=label_dir, surface=parsed.surface)} proposals"
        )
    if parsed.stats or not parsed.write_proposals:
        print(
            json.dumps(
                stats(
                    run_dir=run_dir,
                    audit_path=audit_path,
                    label_dir=label_dir,
                    surface=parsed.surface,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def _validate_pages(pages: tuple[CorpusPage, ...]) -> bool:
    for page in pages:
        label = page.label
        if label is None:
            continue
        if label.get("schema_version") != EXTRACTION_V3_LABEL_SCHEMA_VERSION:
            return False
        if label.get("surface") != page.surface:
            return False
        if not isinstance(label.get("fields"), dict):
            return False
        if not isinstance(label.get("variants"), list):
            return False
    return True


def _load_surface_label_pages(
    *, run_dir: Path, label_dir: Path, surface: str
) -> tuple[CorpusPage, ...]:
    surface_dir = label_dir / surface
    label_paths = sorted(surface_dir.glob("*.json")) if surface_dir.exists() else []
    pages: list[CorpusPage] = []
    for label_path in label_paths:
        label = _load_json(label_path)
        if not isinstance(label, dict) or label.get("surface") != surface:
            continue
        result_id = int(label.get("result_id") or label_path.stem)
        pages.append(
            CorpusPage(
                result_id=result_id,
                result_dir=run_dir / "results" / str(result_id),
                surface=surface,
                url=str(label.get("url") or ""),
                variant_bucket=str(
                    label.get("metadata", {}).get("variant_bucket") or "unknown"
                )
                if isinstance(label.get("metadata"), dict)
                else "unknown",
                platform=str(label.get("metadata", {}).get("platform") or "unknown")
                if isinstance(label.get("metadata"), dict)
                else "unknown",
                label_path=label_path,
                label=label,
            )
        )
    return tuple(pages)


def _normalize_surface(surface: str) -> str:
    normalized = str(surface or EXTRACTION_V3_COMMERCE_DETAIL_SURFACE).strip().lower()
    if normalized == "ecommerce_detail":
        return EXTRACTION_V3_COMMERCE_DETAIL_SURFACE
    return normalized


def _load_record(result_dir: Path) -> dict[str, Any]:
    path = result_dir / "record.json"
    if not path.exists():
        return {"record_count": 0, "records": []}
    payload = _load_json(path)
    raw_records = payload.get("records") if isinstance(payload, dict) else []
    records = raw_records if isinstance(raw_records, list) else []
    return {
        "record_count": int(payload.get("record_count", len(records)) or 0),
        "records": records,
    }


def _proposal_value(field: str, record: dict[str, Any], structured: object) -> Any:
    if field == "images":
        image = record.get("image_url")
        return [image] if image else []
    if field == "category":
        return record.get("category") or (
            structured.get("category_breadcrumb")
            if isinstance(structured, dict)
            else None
        )
    return record.get(field) or (
        structured.get(field) if isinstance(structured, dict) else None
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return _load_json(path)


if __name__ == "__main__":
    raise SystemExit(main())
