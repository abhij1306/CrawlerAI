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
    EXTRACTION_V3_VARIANT_EXPECTED_BUCKETS,
)

from eval.corpus import DEFAULT_AUDIT_PATH, DEFAULT_RUN_DIR, CorpusPage, load_pages


@dataclass(frozen=True, slots=True)
class ScoreReport:
    page_count: int
    field_metrics: dict[str, dict[str, float]]
    field_counts: dict[str, dict[str, int]]
    variant_matrix_accuracy: float
    variant_metrics: dict[str, float | int]
    hallucination_proxy_rate: float
    defect_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "field_metrics": self.field_metrics,
            "field_counts": self.field_counts,
            "variant_matrix_accuracy": self.variant_matrix_accuracy,
            "variant_metrics": self.variant_metrics,
            "hallucination_proxy_rate": self.hallucination_proxy_rate,
            "defect_counts": self.defect_counts,
        }


def score_records_against_labels(
    pages: tuple[CorpusPage, ...],
    *,
    record_payloads: dict[int, dict[str, Any]] | None = None,
) -> ScoreReport:
    counts: dict[str, Counter[str]] = {
        field: Counter() for field in EXTRACTION_V3_LABEL_CORE_FIELDS
    }
    variant_scores: list[float] = []
    variant_exact = 0
    hallucination_values = 0
    extracted_values = 0
    for page in pages:
        if not page.label:
            continue
        record = _first_record(page, record_payloads)
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
        expected_variants = _variant_rows(page.label.get("variants"))
        if expected_variants:
            score = _variant_matrix_score(expected_variants, record.get("variants"))
            variant_scores.append(score)
            if score == 1.0:
                variant_exact += 1
    variant_score = _ratio(sum(variant_scores), len(variant_scores))
    return ScoreReport(
        page_count=len(pages),
        field_metrics={field: _metrics(counter) for field, counter in counts.items()},
        field_counts={
            field: _field_count_dict(counter) for field, counter in counts.items()
        },
        variant_matrix_accuracy=variant_score,
        variant_metrics={
            "pages_with_expected_variants": len(variant_scores),
            "exact_pages": variant_exact,
            "mean_page_score": variant_score,
        },
        hallucination_proxy_rate=_ratio(hallucination_values, extracted_values),
        defect_counts=baseline_defects(pages, record_payloads=record_payloads),
    )


def baseline_defects(
    pages: tuple[CorpusPage, ...],
    *,
    record_payloads: dict[int, dict[str, Any]] | None = None,
) -> dict[str, int]:
    defects: Counter[str] = Counter()
    for page in pages:
        record_payload = _record_payload_for_page(page, record_payloads)
        records = record_payload.get("records") or []
        if int(record_payload.get("record_count", len(records)) or 0) == 0:
            defects["empty_records"] += 1
            defects["missing_price_on_commerce_detail"] += 1
            if page.variant_bucket in EXTRACTION_V3_VARIANT_EXPECTED_BUCKETS:
                defects["empty_variants_where_expected"] += 1
            continue
        first = records[0] if records else {}
        if not _present(first.get("price")):
            defects["missing_price_on_commerce_detail"] += 1
        if (
            page.variant_bucket in EXTRACTION_V3_VARIANT_EXPECTED_BUCKETS
            and not first.get("variants")
        ):
            defects["empty_variants_where_expected"] += 1
    return {
        key: int(defects.get(key, 0)) for key in EXTRACTION_V3_BASELINE_EXPECTED_DEFECTS
    }


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


def _field_count_dict(counter: Counter[str]) -> dict[str, int]:
    return {
        "tp": int(counter["tp"]),
        "fp": int(counter["fp"]),
        "fn": int(counter["fn"]),
    }


def _actual_field(field: str, record: dict[str, Any]) -> Any:
    if field == "images":
        images = []
        image = record.get("image_url")
        if image:
            images.append(image)
        for value in record.get("additional_images") or []:
            if value and value not in images:
                images.append(value)
        return images
    if field == "category":
        # Mirror the proposal-time fallback (corpus.py `_proposal_value`): labels
        # built from `category_breadcrumb` must be scored against the same source,
        # else every breadcrumb-derived category reads as a false negative.
        category = record.get("category")
        if category:
            return category
        structured = record.get("structured")
        return (
            structured.get("category_breadcrumb")
            if isinstance(structured, dict)
            else None
        )
    return record.get(field)


def _first_record(
    page: CorpusPage, record_payloads: dict[int, dict[str, Any]] | None
) -> dict[str, Any]:
    records = _record_payload_for_page(page, record_payloads).get("records") or []
    return records[0] if records else {}


def _record_payload_for_page(
    page: CorpusPage, record_payloads: dict[int, dict[str, Any]] | None
) -> dict[str, Any]:
    if record_payloads is not None:
        return record_payloads.get(
            page.result_id,
            {"record_count": 0, "records": []},
        )
    return _record_payload(page.result_dir)


def _record_payload(result_dir: Path) -> dict[str, Any]:
    path = result_dir / "record.json"
    if not path.exists():
        return {"record_count": 0, "records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"record_count": 0, "records": []}
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
    if isinstance(expected, list) and isinstance(actual, list):
        return _list_match(expected, actual)
    return _normalize_scalar(expected) == _normalize_scalar(actual)


def _list_match(expected: list[Any], actual: list[Any]) -> bool:
    expected_values = {
        _normalize_scalar(value) for value in expected if _present(value)
    }
    actual_values = {_normalize_scalar(value) for value in actual if _present(value)}
    if not expected_values:
        return not actual_values
    return expected_values <= actual_values


def _normalize_scalar(value: Any) -> str:
    text = (
        json.dumps(value, sort_keys=True, default=str)
        if not isinstance(value, str)
        else value
    )
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _variant_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _variant_matrix_score(
    expected_variants: list[dict[str, Any]],
    actual_variants: Any,
) -> float:
    actual_rows = _variant_rows(actual_variants)
    if not expected_variants:
        return 1.0 if not actual_rows else 0.0
    if not actual_rows:
        return 0.0
    expected_keys = set().union(*(row.keys() for row in expected_variants))
    score_total = 0.0
    used_actual: set[int] = set()
    for expected in expected_variants:
        best_index = -1
        best_score = 0.0
        for index, actual in enumerate(actual_rows):
            if index in used_actual:
                continue
            row_score = _variant_row_score(expected, actual, expected_keys)
            if row_score > best_score:
                best_index = index
                best_score = row_score
        if best_index >= 0:
            used_actual.add(best_index)
        score_total += best_score
    coverage = min(len(actual_rows), len(expected_variants)) / len(expected_variants)
    return round((score_total / len(expected_variants)) * coverage, 6)


def _variant_row_score(
    expected: dict[str, Any],
    actual: dict[str, Any],
    expected_keys: set[str],
) -> float:
    keys = [key for key in sorted(expected_keys) if _present(expected.get(key))]
    if not keys:
        return 0.0
    matched = sum(
        1
        for key in keys
        if _normalize_variant_value(expected.get(key))
        == _normalize_variant_value(actual.get(key))
    )
    return matched / len(keys)


def _normalize_variant_value(value: Any) -> str:
    text = _normalize_scalar(value)
    if text in {"instock", "available"}:
        return "in_stock"
    if text in {"outofstock", "soldout", "unavailable"}:
        return "out_of_stock"
    return text


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
        "empty_variants_where_expected": quality.get("empty_variants_where_expected"),
    }
    if any(value is None for value in values.values()):
        return None
    return {key: int(value) for key, value in values.items() if value is not None}
