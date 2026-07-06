from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config.evaluation import (
    EXTRACTION_V3_BASELINE_EXPECTED_DEFECTS,
    EXTRACTION_V3_LABEL_CORE_FIELDS,
)

from eval.corpus import DEFAULT_AUDIT_PATH, DEFAULT_RUN_DIR, CorpusPage, load_pages


@dataclass(frozen=True, slots=True)
class ScoreReport:
    field_metrics: dict[str, dict[str, float]]
    variant_matrix_accuracy: float
    hallucination_proxy_rate: float
    defect_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_metrics": self.field_metrics,
            "variant_matrix_accuracy": self.variant_matrix_accuracy,
            "hallucination_proxy_rate": self.hallucination_proxy_rate,
            "defect_counts": self.defect_counts,
        }


def score_records_against_labels(pages: tuple[CorpusPage, ...]) -> ScoreReport:
    counts = {field: Counter() for field in EXTRACTION_V3_LABEL_CORE_FIELDS}
    variant_total = 0
    variant_exact = 0
    hallucination_values = 0
    extracted_values = 0
    for page in pages:
        if not page.label:
            continue
        record = _first_record(page.result_dir)
        html = _page_html(page.result_dir)
        for field in EXTRACTION_V3_LABEL_CORE_FIELDS:
            expected = page.label.get("fields", {}).get(field)
            actual = _actual_field(field, record)
            present_expected = _present(expected)
            present_actual = _present(actual)
            if present_expected and present_actual and _matches(expected, actual):
                counts[field]["tp"] += 1
            elif present_actual and not present_expected:
                counts[field]["fp"] += 1
            elif present_expected and not present_actual:
                counts[field]["fn"] += 1
            elif present_actual:
                counts[field]["fp"] += 1
                counts[field]["fn"] += 1
            if present_actual:
                extracted_values += 1
                if _normalize_scalar(actual) not in _normalize_scalar(html):
                    hallucination_values += 1
        expected_variants = page.label.get("variants") or []
        actual_variants = record.get("variants") or []
        variant_total += 1 if expected_variants else 0
        if expected_variants and _normalize_scalar(expected_variants) == _normalize_scalar(actual_variants):
            variant_exact += 1
    return ScoreReport(
        field_metrics={field: _metrics(counter) for field, counter in counts.items()},
        variant_matrix_accuracy=_ratio(variant_exact, variant_total),
        hallucination_proxy_rate=_ratio(hallucination_values, extracted_values),
        defect_counts=baseline_defects(pages),
    )


def baseline_defects(pages: tuple[CorpusPage, ...]) -> dict[str, int]:
    defects = Counter()
    for page in pages:
        record_payload = _record_payload(page.result_dir)
        records = record_payload.get("records") or []
        if int(record_payload.get("record_count", len(records)) or 0) == 0:
            defects["empty_records"] += 1
            defects["missing_price_on_commerce_detail"] += 1
            if page.variant_bucket in {"embedded_json", "dom_only", "partial"}:
                defects["empty_variants_where_expected"] += 1
            continue
        first = records[0] if records else {}
        if not _present(first.get("price")):
            defects["missing_price_on_commerce_detail"] += 1
        if page.variant_bucket in {"embedded_json", "dom_only", "partial"} and not first.get("variants"):
            defects["empty_variants_where_expected"] += 1
    return {key: int(defects.get(key, 0)) for key in EXTRACTION_V3_BASELINE_EXPECTED_DEFECTS}


def baseline_report(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    audit_path: Path = DEFAULT_AUDIT_PATH,
) -> dict[str, Any]:
    pages = load_pages(run_dir=run_dir, audit_path=audit_path)
    observed = baseline_defects(pages)
    defects = _audit_baseline_defects(audit_path) or observed
    expected = EXTRACTION_V3_BASELINE_EXPECTED_DEFECTS
    return {
        "defect_counts": defects,
        "artifact_observed_defect_counts": observed,
        "expected_defect_counts": expected,
        "matches_expected": all(
            abs(defects[key] - expected[key]) <= 1 for key in expected
        ),
    }


def _metrics(counter: Counter[str]) -> dict[str, float]:
    precision = _ratio(counter["tp"], counter["tp"] + counter["fp"])
    recall = _ratio(counter["tp"], counter["tp"] + counter["fn"])
    return {
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
    }


def _actual_field(field: str, record: dict[str, Any]) -> Any:
    if field == "images":
        image = record.get("image_url")
        return [image] if image else []
    if field == "category":
        return record.get("category")
    return record.get(field)


def _first_record(result_dir: Path) -> dict[str, Any]:
    records = _record_payload(result_dir).get("records") or []
    return records[0] if records else {}


def _record_payload(result_dir: Path) -> dict[str, Any]:
    path = result_dir / "record.json"
    if not path.exists():
        return {"record_count": 0, "records": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"record_count": 0, "records": []}


def _page_html(result_dir: Path) -> str:
    path = result_dir / "page.html"
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _matches(expected: Any, actual: Any) -> bool:
    return _normalize_scalar(expected) == _normalize_scalar(actual)


def _normalize_scalar(value: Any) -> str:
    text = (
        json.dumps(value, sort_keys=True, default=str)
        if not isinstance(value, str)
        else value
    )
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _audit_baseline_defects(audit_path: Path) -> dict[str, int] | None:
    summary_path = audit_path.with_name("summary.json")
    if not summary_path.exists():
        return None
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    quality = payload.get("baseline_quality")
    if not isinstance(quality, dict):
        return None
    values = {
        "empty_records": quality.get("empty"),
        "missing_price_on_commerce_detail": quality.get(
            "missing_price_on_commerce_detail"
        ),
        "empty_variants_where_expected": quality.get(
            "empty_variants_where_expected"
        ),
    }
    if any(value is None for value in values.values()):
        return None
    return {key: int(value) for key, value in values.items()}
