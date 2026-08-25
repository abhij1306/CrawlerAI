from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.extraction import Surface, extract
from app.extraction.contracts import ExtractionResult
from app.extraction.replay import fixture_request_from_inputs

EVAL_REFERENCE = "crawlerai_eval_html_grounded_v3_2.json"
DEFECT_REFERENCE = "crawlerai_defects_html_grounded_v3_2.json"
IGNORED_EXTRACTOR_INPUTS = frozenset({"record.json", "diagnose.json"})
TRACKING_QUERY_KEYS = frozenset(
    {
        "_ga",
        "fbclid",
        "gclid",
        "ref",
        "source",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
CAPTURE_MIN_TOKEN_OVERLAP_RATIO = 0.6
AREA_FIELDS: dict[str, frozenset[str]] = {
    "product_identity_and_page_state": frozenset({"title", "product_family"}),
    "selected_variant_state": frozenset({"color", "selected_fit", "size"}),
    "commercial_fields": frozenset(
        {
            "availability",
            "currency",
            "original_price",
            "price",
            "price_max",
            "price_min",
        }
    ),
    "variants_and_options": frozenset(
        {"model_options", "size_options", "variant_count", "variants"}
    ),
    "product_identifiers": frozenset(
        {"asin", "barcode", "mpn", "product_id", "sku", "style_id"}
    ),
    "core_identity_fields": frozenset({"brand", "title"}),
    "attributes": frozenset(
        {"color", "condition", "gender", "material", "size", "size_options"}
    ),
    "reviews": frozenset({"rating", "review_count"}),
}

__all__ = [
    "audit_artifact_quality_cases",
    "load_artifact_quality_cases",
    "validate_artifact_quality_cases",
]


def load_artifact_quality_cases(
    path: str | Path, defects_path: str | Path | None = None
) -> dict[str, Any]:
    """Load the two canonical compact references without creating a third manifest."""
    evaluation_path = Path(path)
    if evaluation_path.is_dir():
        reference_root = evaluation_path
        evaluation_path = reference_root / EVAL_REFERENCE
    else:
        reference_root = evaluation_path.parent
    defect_reference_path = (
        Path(defects_path) if defects_path else reference_root / DEFECT_REFERENCE
    )
    return {
        "evaluation": _read_json(evaluation_path),
        "defects": _read_json(defect_reference_path),
    }


def validate_artifact_quality_cases(
    references: dict[str, Any], *, backend_root: str | Path
) -> list[str]:
    errors = _reference_errors(references)
    if errors:
        return errors
    try:
        captures = _discover_captures(Path(backend_root) / "artifacts" / "runs")
        _select_all_captures(references["evaluation"]["cases"], captures)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def audit_artifact_quality_cases(
    references: dict[str, Any],
    *,
    backend_root: str | Path,
    partitions: Iterable[str] | None = None,
) -> dict[str, Any]:
    errors = _reference_errors(references)
    if errors:
        raise ValueError("; ".join(errors))
    selected_partitions = _selected_partitions(references, partitions)
    cases = references["evaluation"]["cases"]
    captures = _discover_captures(Path(backend_root) / "artifacts" / "runs")
    selected = _select_all_captures(cases, captures)
    audited = [
        _audit_case(
            case,
            capture=selected[int(case["id"])],
            references=references,
            partitions=selected_partitions,
        )
        for case in sorted(cases, key=lambda row: int(row["id"]))
    ]
    durations = [float(row["extraction_duration_ms"]) for row in audited]
    failed = tuple(row["case_id"] for row in audited if row["failures"])
    capture_limited = tuple(row["case_id"] for row in audited if row["capture_limited"])
    return {
        "quality_clean": not failed,
        "case_count": len(audited),
        "partitions": selected_partitions,
        "failed_case_ids": failed,
        "capture_limited_case_ids": capture_limited,
        "selected_capture_hashes": {
            str(row["case_id"]): row["capture_hashes"] for row in audited
        },
        "timing_ms": _timing_summary(durations),
        "cases": tuple(audited),
    }


def _reference_errors(references: object) -> list[str]:
    if not isinstance(references, dict):
        return ["references must be an object"]
    evaluation = references.get("evaluation")
    defects = references.get("defects")
    if not isinstance(evaluation, dict) or not isinstance(defects, dict):
        return ["evaluation and defects references are required"]
    cases = evaluation.get("cases")
    evaluation_metadata = _first_mapping(evaluation.get("metadata"))
    errors: list[str] = []
    if evaluation_metadata.get("version") != _first_mapping(
        defects.get("metadata")
    ).get("version"):
        errors.append("evaluation and defects versions must match")
    if int(evaluation_metadata.get("cases") or 0) != 82 or not (
        isinstance(cases, list) and len(cases) == 82
    ):
        errors.append("evaluation must contain 82 cases")
        return errors
    ids = [int(row.get("id", 0)) for row in cases if isinstance(row, dict)]
    if len(ids) != 82 or len(set(ids)) != 82:
        errors.append("evaluation must contain 82 unique IDs")
    errors += _defect_case_errors(defects)
    errors += _defect_partition_errors(defects)
    duplicates = _normalized_url_duplicates(cases)
    if duplicates != {(24, 62)}:
        errors.append(f"unexpected normalized URL duplicates: {sorted(duplicates)}")
    return errors


def _defect_case_errors(defects: dict[str, Any]) -> list[str]:
    defect_cases = defects.get("cases")
    expected = int(_first_mapping(defects.get("summary")).get("failing_cases") or 0)
    if expected != 75 or not isinstance(defect_cases, list):
        return ["defects must contain the 75 failing cases"]
    if len(defect_cases) != expected:
        return ["defect case count does not match its summary"]
    return []


def _defect_partition_errors(defects: dict[str, Any]) -> list[str]:
    areas = defects.get("problem_areas")
    summary = _first_mapping(defects.get("summary"))
    if not isinstance(areas, list) or {
        str(row.get("area")) for row in areas if isinstance(row, dict)
    } != set(AREA_FIELDS):
        return ["defect partitions do not match the supported areas"]
    if sum(int(row.get("defects") or 0) for row in areas) != int(
        summary.get("defects") or 0
    ):
        return ["defect partition totals do not match their summary"]
    errors: list[str] = []
    for area in areas:
        declared = int(area.get("defects") or 0)
        if len(set(area.get("case_ids") or ())) != int(area.get("affected_cases") or 0):
            errors.append(f"{area.get('area')} affected case count is inconsistent")
        if (
            sum(int(row.get("count") or 0) for row in area.get("top_fields") or ())
            != declared
        ):
            errors.append(f"{area.get('area')} field totals are inconsistent")
    return errors


def _normalized_url_duplicates(cases: Sequence[object]) -> set[tuple[int, int]]:
    by_url: dict[str, list[int]] = {}
    for row in cases:
        if isinstance(row, dict):
            key = _url_key(str(row.get("url") or ""), query=False)
            by_url.setdefault(key, []).append(int(row.get("id", 0)))
    return {tuple(sorted(ids)) for ids in by_url.values() if len(ids) > 1}


def _selected_partitions(
    references: dict[str, Any], partitions: Iterable[str] | None
) -> tuple[str, ...]:
    available = {
        str(row["area"])
        for row in references["defects"]["problem_areas"]
        if isinstance(row, dict) and row.get("area")
    }
    selected = available if partitions is None else {str(value) for value in partitions}
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown defect partitions: {', '.join(sorted(unknown))}")
    return tuple(sorted(selected))


def _discover_captures(root: Path) -> tuple[dict[str, Any], ...]:
    captures: list[dict[str, Any]] = []
    for diagnose_path in sorted(root.glob("*/results/*/diagnose.json")):
        result_root = diagnose_path.parent
        if not (
            _is_numeric_path_part(result_root.parent.parent.name)
            and _is_numeric_path_part(result_root.name)
        ):
            continue
        page_path = result_root / "page.html"
        if not page_path.is_file():
            raise ValueError(f"capture missing page.html: {result_root}")
        diagnose = _read_json(diagnose_path)
        acquisition = _first_mapping(diagnose.get("acquisition"))
        final_url = str(acquisition.get("final_url") or "").strip()
        if not final_url:
            raise ValueError(f"capture missing final_url: {diagnose_path}")
        captures.append(
            {
                "root": result_root,
                "run_id": _numeric_path_part(result_root.parent.parent.name),
                "url_result_id": _numeric_path_part(result_root.name),
                "final_url": final_url,
            }
        )
    if not captures:
        raise ValueError(f"no captures found under {root}")
    return tuple(captures)


def _select_all_captures(
    cases: Sequence[dict[str, Any]], captures: Sequence[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    selected = {int(case["id"]): _select_capture(case, captures) for case in cases}
    hash_cache: dict[Path, dict[str, str]] = {}
    for case in cases:
        capture = selected[int(case["id"])]
        root = Path(capture["root"])
        if root not in hash_cache:
            hash_cache[root] = _capture_hashes(root)
        actual_hashes = hash_cache[root]
        expected_hashes = _first_mapping(case.get("capture_hashes"))
        for name, expected in expected_hashes.items():
            if actual_hashes.get(str(name)) != str(expected):
                raise ValueError(f"case {case.get('id')} capture hash mismatch: {name}")
        capture["hashes"] = actual_hashes
    return selected


def _select_capture(
    case: Mapping[str, Any], captures: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    requested_url = str(case.get("url") or "")
    scored = [
        (_capture_match_score(requested_url, str(row["final_url"])), row)
        for row in captures
    ]
    matched = [(score, row) for score, row in scored if score > 0]
    if not matched:
        raise ValueError(f"case {case.get('id')} has no matching capture")
    best_score = max(score for score, _ in matched)
    best = [row for score, row in matched if score == best_score]
    newest_rank = max((int(row["run_id"]), int(row["url_result_id"])) for row in best)
    newest = [
        row
        for row in best
        if (int(row["run_id"]), int(row["url_result_id"])) == newest_rank
    ]
    if len(newest) != 1:
        raise ValueError(f"case {case.get('id')} has ambiguous latest captures")
    capture = dict(newest[0])
    return capture


def _capture_match_score(requested_url: str, final_url: str) -> int:
    if _url_key(requested_url, query=True) == _url_key(final_url, query=True):
        return 1000
    requested = urlsplit(requested_url)
    final = urlsplit(final_url)
    if requested.hostname != final.hostname:
        return 0
    queries_match = _normalized_query_pairs(requested_url) == _normalized_query_pairs(
        final_url
    )
    if _url_key(requested_url, query=False) == _url_key(final_url, query=False):
        return 950 if queries_match else 900
    requested_tokens = _url_tokens(requested_url)
    final_tokens = _url_tokens(final_url)
    shared = requested_tokens & final_tokens
    if not shared:
        return 0
    overlap_ratio = len(shared) / len(requested_tokens | final_tokens)
    if overlap_ratio < CAPTURE_MIN_TOKEN_OVERLAP_RATIO and not _url_slugs_related(
        requested_url, final_url
    ):
        return 0
    if queries_match:
        return 950
    return 100 + round(100 * overlap_ratio)


def _url_key(url: str, *, query: bool) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            path,
            urlencode(_normalized_query_pairs(url)) if query else "",
            "",
        )
    )


def _normalized_query_pairs(url: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                (key, value)
                for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
                if key.casefold() not in TRACKING_QUERY_KEYS
                and not key.casefold().startswith("utm_")
            )
        )
    )


def _url_tokens(url: str) -> set[str]:
    parts = urlsplit(url)
    text = f"{parts.path} {' '.join(value for _, value in parse_qsl(parts.query))}"
    return {token.casefold() for token in _split_tokens(text) if len(token) >= 4}


def _url_slugs_related(left: str, right: str) -> bool:
    slugs = [
        tuple(
            token.casefold()
            for token in _split_tokens(urlsplit(url).path.rsplit("/", 1)[-1])
        )
        for url in (left, right)
    ]
    shorter, longer = sorted(slugs, key=len)
    width = len(shorter)
    return width >= 2 and (shorter == longer[:width] or shorter == longer[-width:])


def _split_tokens(value: str) -> list[str]:
    for separator in "/_-?=&.":
        value = value.replace(separator, " ")
    return value.split()


def _audit_case(
    case: dict[str, Any],
    *,
    capture: dict[str, Any],
    references: dict[str, Any],
    partitions: tuple[str, ...],
) -> dict[str, Any]:
    requested_fields = _requested_fields(case, references, partitions)
    started = time.perf_counter()
    result = _replay_case(case, capture=capture, requested_fields=requested_fields)
    duration_ms = (time.perf_counter() - started) * 1000
    public = _public_record(result)
    projection = _evaluation_projection(public)
    failures = _assert_case(case, projection=projection, fields=requested_fields)
    failures += _lineage_failures(public)
    return {
        "case_id": int(case["id"]),
        "reference_source": str(case.get("source") or "captured_html"),
        "capture_limited": case.get("source") == "fallback",
        "url_result_id": int(capture["url_result_id"]),
        "run_id": int(capture["run_id"]),
        "capture_hashes": capture["hashes"],
        "asserted_fields": requested_fields,
        "failures": tuple(failures),
        "verdict": result.verdict,
        "data_integrity": result.data_integrity,
        "extraction_duration_ms": round(duration_ms, 3),
    }


def _requested_fields(
    case: Mapping[str, Any], references: dict[str, Any], partitions: tuple[str, ...]
) -> tuple[str, ...]:
    if case.get("source") == "fallback":
        return ()
    expected = _first_mapping(case.get("expected"))
    constrained = _first_mapping(case.get("constraints"))
    defective: set[str] = set()
    selected: set[str] = set()
    case_id = int(case["id"])
    for area in references["defects"]["problem_areas"]:
        if case_id not in set(area.get("case_ids") or ()):
            continue
        name = str(area["area"])
        defective.update(AREA_FIELDS[name])
        if name in partitions:
            selected.update(AREA_FIELDS[name])
    available = set(expected) | set(constrained)
    if case.get("variants"):
        # The variant specification is a top-level case key, not a member of
        # expected/constraints, so it has to be admitted explicitly or
        # _variant_failures never runs for the 31 cases that declare one.
        available.add("variants")
    return tuple(sorted((((available - defective) | selected) & available)))


def _replay_case(
    case: Mapping[str, Any],
    *,
    capture: Mapping[str, Any],
    requested_fields: tuple[str, ...],
) -> ExtractionResult:
    result_root = Path(str(capture["root"]))
    html = (result_root / "page.html").read_text(encoding="utf-8")
    network_payloads, artifacts = _standalone_artifacts(result_root)
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        str(capture["final_url"]),
        requested_url=str(case["url"]),
        requested_fields=tuple(_runtime_field(field) for field in requested_fields),
        network_payloads=network_payloads,
        artifacts=artifacts,
    )
    return extract(request)


def _standalone_artifacts(
    root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    network: list[dict[str, object]] = []
    artifacts: dict[str, object] = {}
    for path in sorted(root.glob("*.json")):
        if path.name in IGNORED_EXTRACTOR_INPUTS:
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if path.stem.startswith("network"):
            rows = value if isinstance(value, list) else [value]
            network.extend(dict(row) for row in rows if isinstance(row, dict))
        elif path.stem in {"js_state", "js_state_objects"} and isinstance(value, dict):
            artifacts["js_state_objects"] = value
    return network, artifacts


def _runtime_field(field: str) -> str:
    return {
        "asin": "product_id",
        "material": "materials",
        "model_options": "variants",
        "product_family": "variants",
        "selected_fit": "variants",
        "size_options": "variants",
    }.get(field, field)


def _public_record(result: ExtractionResult) -> dict[str, Any]:
    if not result.records:
        return {}
    return result.records[0].model_dump(mode="python", exclude_none=True)


def _evaluation_projection(public: dict[str, Any]) -> dict[str, Any]:
    variants = [
        dict(row) for row in public.get("variants") or () if isinstance(row, Mapping)
    ]
    model_options = [
        {
            key: row[key]
            for key in ("model", "price", "currency")
            if row.get(key) is not None
        }
        for row in variants
        if row.get("model") is not None
    ]
    projection = dict(public)
    projection.update(
        {
            # No cross-field fallback: a value published as `product_id` or
            # `mpn` must not satisfy an `asin` or `style_id` assertion. Those
            # are distinct identifiers, and crediting one for another hides a
            # miss as a pass.
            "asin": public.get("asin"),
            "material": public.get("materials"),
            "model_options": model_options,
            "product_family": bool(
                len({str(row.get("model")) for row in variants if row.get("model")}) > 1
                and public.get("price_min") is not None
                and public.get("price_max") is not None
            ),
            "selected_fit": next(
                (row.get("fit") for row in variants if row.get("fit")), None
            ),
            "size_options": sorted(
                {str(row["size"]) for row in variants if row.get("size")}
            ),
            "style_id": public.get("style_id"),
        }
    )
    return projection


def _assert_case(
    case: Mapping[str, Any], *, projection: dict[str, Any], fields: tuple[str, ...]
) -> list[str]:
    failures: list[str] = []
    expected = _first_mapping(case.get("expected"))
    constraints = _first_mapping(case.get("constraints"))
    for field in fields:
        if (
            field in expected
            and field not in constraints
            and not _values_match(projection.get(field), expected[field])
        ):
            failures.append(
                f"{field}: expected {expected[field]!r}, actual {projection.get(field)!r}"
            )
        if field in constraints and not _constraint_matches(
            projection.get(field), constraints[field], projection, field
        ):
            failures.append(
                f"{field}: constraint {constraints[field]!r}, actual {projection.get(field)!r}"
            )
    for field, forbidden in _first_mapping(case.get("forbidden")).items():
        if _contains_forbidden(projection.get(str(field)), forbidden):
            failures.append(f"{field}: forbidden value published")
    variant_spec = _first_mapping(case.get("variants"))
    if "variants" in fields and variant_spec:
        failures.extend(_variant_failures(projection.get("variants"), variant_spec))
    return failures


def _values_match(actual: object, expected: object) -> bool:
    if isinstance(expected, list):
        actual_rows = (
            list(actual) if isinstance(actual, (list, tuple, set, frozenset)) else []
        )
        return all(
            any(_values_match(candidate, row) for candidate in actual_rows)
            for row in expected
        )
    if isinstance(expected, dict):
        return isinstance(actual, Mapping) and all(
            _values_match(actual.get(key), value) for key, value in expected.items()
        )
    if isinstance(actual, (list, tuple, set, frozenset)):
        return any(_values_match(value, expected) for value in actual)
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except InvalidOperation:
            return False
    return str(actual or "").strip() == str(expected or "").strip()


_MONETARY_CONSTRAINT_FIELDS = frozenset(
    {"original_price", "price", "price_max", "price_min"}
)


def _constraint_matches(
    actual: object,
    constraint: object,
    projection: Mapping[str, Any],
    field: str = "",
) -> bool:
    row = constraint if isinstance(constraint, Mapping) else {}
    mode = str(row.get("mode") or "exact")
    if mode == "exact":
        return _values_match(actual, row.get("value"))
    if mode not in {"volatile", "locale_sensitive"}:
        return False
    try:
        amount = Decimal(str(actual))
    except (InvalidOperation, TypeError):
        return False
    # Money must be positive and carry a currency. A volatile rating or review
    # count only has to be a real non-negative number: case 71 legitimately
    # reports a 0.0 rating, and a currency is unrelated to either field.
    if field in _MONETARY_CONSTRAINT_FIELDS:
        return amount > 0 and bool(str(projection.get("currency") or "").strip())
    return amount >= 0


def _contains_forbidden(actual: object, forbidden: object) -> bool:
    values = (
        forbidden
        if isinstance(forbidden, (list, tuple, set, frozenset))
        else (forbidden,)
    )
    return any(_values_match(actual, value) for value in values)


def _variant_failures(actual: object, spec: Mapping[str, Any]) -> list[str]:
    variants = list(actual) if isinstance(actual, (list, tuple)) else []
    failures: list[str] = []
    if "count" in spec and len(variants) != int(spec["count"]):
        failures.append(
            f"variants: expected count {spec['count']}, actual {len(variants)}"
        )
    fields = tuple(str(value) for value in spec.get("fields") or ())
    if fields and any(
        not isinstance(row, Mapping) or any(row.get(field) is None for field in fields)
        for row in variants
    ):
        failures.append("variants: required fields missing")
    for example in spec.get("examples") or ():
        if not any(_values_match(row, example) for row in variants):
            failures.append(f"variants: missing example {example!r}")
    return failures


def _lineage_failures(public: Mapping[str, Any]) -> list[str]:
    lineage = public.get("_lineage")
    if not isinstance(lineage, Mapping):
        return [] if not public else ["published record has no lineage"]
    excluded = {"additional_images", "variant_count", "variants"}
    return [
        f"{field}: published value has no lineage"
        for field, value in public.items()
        if not str(field).startswith("_")
        and field not in excluded
        and value not in (None, "", (), [], {})
        and field != "url"
        and field not in lineage
    ]


def _capture_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name not in IGNORED_EXTRACTOR_INPUTS:
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _timing_summary(durations: Sequence[float]) -> dict[str, float]:
    if not durations:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    ordered = sorted(durations)
    p95_index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return {
        "mean": round(statistics.fmean(ordered), 3),
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
    }


def _is_numeric_path_part(value: str) -> bool:
    return value.isdigit()


def _numeric_path_part(value: str) -> int:
    """Capture directories are numbered; a non-numeric name is not a capture.

    Mapping a malformed name to 0 made it rank alongside genuine captures and
    could surface as an "ambiguous latest captures" failure instead of being
    skipped, so callers filter on ``_is_numeric_path_part`` first.
    """
    try:
        return int(value)
    except ValueError:
        return 0


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value
