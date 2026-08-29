"""Mechanical interpreter for frozen extraction recipes; no discovery or storage."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

from app.core.domain_utils import normalize_domain
from app.core.config.cascade import CASCADE_LISTING_MIN_REPEATED_RECORDS
from app.core.config.extraction_rules import (
    LISTING_TITLE_CTA_TITLES,
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
)
from app.core.extraction_memory.recipe_contracts import (
    BindingOutcome,
    ExtractionRecipe,
    RecipeBinding,
    RecipeEntity,
    RecipeExecutionResult,
    RecipeFailureCode,
)
from app.core.extraction_memory.recipe_artifacts import read_recipe_json_artifact
from app.core.extraction_memory.recipe_transforms import transform_value, url_component
from app.core.records.url_identity import (
    detail_url_resource_identity,
)
from app.extraction.contracts import ArtifactRef, ExtractionRequest
from app.extraction.documents import HtmlDocument, HtmlNode
from app.extraction.surfaces import listing_schema


@dataclass(frozen=True, slots=True)
class _Value:
    value: Any
    source_path: str
    node: HtmlNode | None = None


class _RecipeError(Exception):
    def __init__(self, code: RecipeFailureCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def execute_recipe(
    request: ExtractionRequest, recipe: ExtractionRecipe
) -> RecipeExecutionResult:
    """Read only declared bindings and return internal values with provenance."""

    outcomes: list[BindingOutcome] = []
    try:
        _check_scope(request, recipe)
        _check_capture_requirements(request, recipe)
        roots = _read(request, recipe.record_root, None, outcomes, root=True)
        _check_record_root_minimum(request, recipe, len(roots))
        records = tuple(
            _record(request, recipe, root, outcomes)
            for root in roots[: request.max_records]
        )
        if not records:
            raise _RecipeError("recipe_root_not_found", "record root not found")
        return RecipeExecutionResult(
            recipe_id=recipe.recipe_id,
            records=records,
            outcomes=tuple(outcomes),
        )
    except _RecipeError as exc:
        return RecipeExecutionResult(
            recipe_id=recipe.recipe_id,
            outcomes=tuple(outcomes),
            failure_code=exc.code,
            detail=exc.detail,
        )


def _record(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    root: _Value,
    outcomes: list[BindingOutcome],
) -> dict[str, Any]:
    identity = _identity(request, recipe.identity, root, outcomes)
    excluded = _excluded_nodes(request, recipe, root, outcomes)
    entities = {
        name: _entity_values(request, name, spec, root, outcomes)
        for name, spec in recipe.entities.items()
    }
    _apply_joins(recipe.entities, entities, outcomes)
    record: dict[str, Any] = dict(identity)
    for field, bindings in recipe.fields.items():
        values, collect_many = _record_field_values(
            request, bindings, root, entities, outcomes, excluded
        )
        if values:
            record[field] = _published_field_value(values, collect_many)
        elif field in recipe.required:
            raise _RecipeError(
                "recipe_required_field_missing", f"required field missing: {field}"
            )
    if "record.identity" in recipe.required and not identity:
        raise _RecipeError(
            "recipe_identity_mismatch", "record identity not established"
        )
    return record


def _record_field_values(
    request, bindings, root, entities, outcomes, excluded
) -> tuple[list[_Value], bool]:
    values: list[_Value] = []
    collect_many = any(binding.cardinality == "many" for binding in bindings)
    for binding in bindings:
        binding_values = [
            value
            for scope in _binding_scopes(binding, root, entities)
            for value in _read(request, binding, scope, outcomes, allow_missing=True)
        ]
        if binding_values:
            values.extend(binding_values)
            if not collect_many:
                break
    return [row for row in values if not _is_excluded(row, excluded)], collect_many


def _published_field_value(values: list[_Value], collect_many: bool) -> Any:
    if not collect_many:
        return values[0].value if len(values) == 1 else [row.value for row in values]
    flattened = [
        item
        for row in values
        for item in (
            row.value if isinstance(row.value, (list, tuple)) else (row.value,)
        )
    ]
    unique = {repr(item): item for item in flattened}
    return list(unique.values())


def _identity(
    request: ExtractionRequest,
    bindings: tuple[RecipeBinding, ...],
    root: _Value,
    outcomes: list[BindingOutcome],
) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for binding in bindings:
        values = _read(
            request,
            binding,
            None if binding.scope == "document" else root,
            outcomes,
            allow_missing=True,
        )
        if not values:
            if binding.required:
                raise _RecipeError(
                    "recipe_identity_mismatch",
                    f"identity binding missing: {binding.binding_id}",
                )
            continue
        value = values[0].value
        expected = _expected_value(request, binding.compare_to)
        if expected is not None and _identity_value(
            binding.field, value
        ) != _identity_value(binding.field, expected):
            raise _RecipeError(
                "recipe_identity_mismatch",
                f"identity mismatch: {binding.binding_id}",
            )
        identity[binding.field or binding.binding_id.rsplit(".", 1)[-1]] = value
    return identity


def _entity_values(
    request: ExtractionRequest,
    name: str,
    spec: RecipeEntity,
    root: _Value,
    outcomes: list[BindingOutcome],
) -> list[_Value]:
    del name
    scope = root if spec.root.scope == "record.root" else None
    values = _read(request, spec.root, scope, outcomes, allow_missing=True)
    if not (spec.identity or spec.fields):
        return values
    identified: list[_Value] = []
    for value in values:
        payload = _entity_payload(request, spec, value, outcomes)
        if payload is not None:
            identified.append(
                _Value(payload or value.value, value.source_path, value.node)
            )
    return identified


def _entity_payload(request, spec, value, outcomes) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    lineage: dict[str, dict[str, object]] = {}
    for binding in spec.identity:
        rows = _entity_binding_values(request, binding, value, outcomes)
        if rows:
            field = binding.field or binding.binding_id.rsplit(".", 1)[-1]
            payload[field] = rows[0].value
            lineage[field] = _binding_lineage(binding, rows[0])
    for field, bindings in spec.fields.items():
        resolved = _first_entity_field(request, bindings, value, outcomes)
        if resolved is not None:
            binding, rows = resolved
            payload[field] = (
                [row.value for row in rows]
                if binding.cardinality == "many"
                else rows[0].value
            )
            lineage[field] = _binding_lineage(binding, rows[0])
    if spec.identity and not _has_entity_identity(payload, spec.identity):
        return None
    if lineage:
        payload["_binding_lineage"] = lineage
    return payload


def _entity_binding_values(request, binding, value, outcomes):
    scope = None if binding.scope == "document" else value
    return _read(request, binding, scope, outcomes, allow_missing=True)


def _first_entity_field(request, bindings, value, outcomes):
    for binding in bindings:
        rows = _entity_binding_values(request, binding, value, outcomes)
        if rows:
            return binding, rows
    return None


def _has_entity_identity(payload, bindings) -> bool:
    return any(
        payload.get(binding.field or binding.binding_id.rsplit(".", 1)[-1])
        for binding in bindings
    )


def _binding_lineage(binding: RecipeBinding, value: _Value) -> dict[str, object]:
    return {
        "binding_id": binding.binding_id,
        "source_path": value.source_path,
        "rule_id": binding.rule_id,
    }


def _apply_joins(
    specs: dict[str, RecipeEntity],
    entities: dict[str, list[_Value]],
    outcomes: list[BindingOutcome],
) -> None:
    for name, spec in specs.items():
        for join in spec.joins:
            left_entity, _, left_field = join.left.partition(".")
            right_entity, _, right_field = join.right.partition(".")
            left = {
                _comparable(_member(row, left_field))
                for row in entities.get(left_entity, [])
            }
            matched = [
                row
                for row in entities.get(right_entity, [])
                if _comparable(_member(row, right_field)) in left
            ]
            entities[name] = matched
            if join.required and not matched:
                outcomes.append(
                    BindingOutcome(
                        binding_id=f"join.{join.left}.{join.right}",
                        status="join_failed",
                    )
                )
                raise _RecipeError(
                    "recipe_join_failed",
                    f"required join failed: {join.left}={join.right}",
                )


def _binding_scopes(
    binding: RecipeBinding,
    root: _Value,
    entities: dict[str, list[_Value]],
) -> list[_Value | None]:
    if binding.scope in {"document", ""}:
        return [None]
    if binding.scope == "record.root":
        return [root]
    if binding.scope.startswith("entity."):
        return list(entities.get(binding.scope.removeprefix("entity."), []))
    return [root]


def _read(
    request: ExtractionRequest,
    binding: RecipeBinding,
    scope: _Value | None,
    outcomes: list[BindingOutcome],
    *,
    root: bool = False,
    allow_missing: bool = False,
) -> list[_Value]:
    values = _raw_values(request, binding, scope, root=root)
    transformed_values: list[_Value] = []
    for row in values:
        value = transform_value(request, row.value, binding)
        if value in (None, "", [], {}):
            continue
        transformed_values.append(_Value(value, row.source_path, row.node))
    values = transformed_values
    if not root:
        deduplicated: list[_Value] = []
        seen: set[str] = set()
        for row in values:
            marker = repr(row.value)
            if marker not in seen:
                seen.add(marker)
                deduplicated.append(row)
        values = deduplicated
    status: Literal["resolved", "missing"] = "resolved" if values else "missing"
    outcomes.append(
        BindingOutcome(
            binding_id=binding.binding_id,
            status=status,
            source_path=values[0].source_path if values else None,
            value=values[0].value if values else None,
        )
    )
    _check_cardinality(binding, len(values), root=root, allow_missing=allow_missing)
    return values


def _raw_values(
    request: ExtractionRequest,
    binding: RecipeBinding,
    scope: _Value | None,
    *,
    root: bool,
) -> list[_Value]:
    if binding.source in {"dom_text", "dom_attribute"}:
        return _dom_values(request, binding, scope, root=root)
    if binding.source == "url_component":
        return [
            _Value(
                url_component(request.capture.final_url, binding.path),
                f"url:{binding.path}",
            )
        ]
    if binding.source == "artifact_text":
        return _artifact_text_values(request, binding)
    return _json_values(request, binding, scope)


def _dom_values(request, binding, scope, *, root: bool) -> list[_Value]:
    base = _dom_base(request, binding, scope)
    if base is None:
        return []
    nodes = (
        [base]
        if binding.path == "." and isinstance(base, HtmlNode)
        else list(base.safe_css(binding.path))
    )
    nodes = _filtered_dom_nodes(nodes, binding)
    if root:
        return [
            _Value(node, f"{node.artifact_id}:{binding.path}", node) for node in nodes
        ]
    return [
        _Value(
            node.attribute(binding.attribute or "")
            if binding.source == "dom_attribute"
            else node.content_text(),
            f"{node.artifact_id}:{binding.path}",
            node,
        )
        for node in nodes
    ]


def _dom_base(request, binding, scope) -> HtmlDocument | HtmlNode | None:
    if scope is not None and scope.node is not None:
        return scope.node
    artifact = _artifact(request, binding, html=True)
    if artifact is None:
        return None
    return request.artifact_reader.document_store.html(artifact.artifact_id)


def _filtered_dom_nodes(nodes, binding):
    if binding.sense == "price_text" and not binding.attribute:
        return [
            node
            for node in nodes
            if re.search(
                LISTING_VISUAL_PRICE_REGEX_PATTERN,
                node.attribute(binding.attribute or "") or node.content_text(),
                re.IGNORECASE,
            )
        ]
    if binding.sense == "listing_title":
        return [
            node
            for node in nodes
            if _valid_listing_title(
                node.attribute(binding.attribute or "") or node.content_text()
            )
        ]
    return nodes


def _artifact_text_values(request, binding) -> list[_Value]:
    artifact = _artifact(request, binding)
    if artifact is None:
        return []
    return [
        _Value(
            request.artifact_reader.read_text(artifact),
            f"{artifact.artifact_id}:text",
        )
    ]


def _json_values(request, binding, scope) -> list[_Value]:
    payload, prefix = _json_payload(request, binding, scope)
    if payload is None:
        return []
    return [
        _Value(value, f"{prefix}:{binding.path}")
        for value in _walk_path(payload, binding.path)
    ]


def _json_payload(request, binding, scope):
    if scope is not None and (scope.node is None or binding.field == "variants"):
        return scope.value, scope.source_path
    artifact = _artifact(request, binding)
    if binding.source == "script_path" and (
        artifact is None or artifact.artifact_type in {"rendered_html", "http_html"}
    ):
        payload = read_recipe_json_artifact(request, binding.artifact)
        return payload, str(binding.artifact)
    if artifact is None:
        payload = read_recipe_json_artifact(request, binding.artifact)
        return payload, str(binding.artifact)
    return request.artifact_reader.read_json(artifact), artifact.artifact_id


def _artifact(
    request: ExtractionRequest, binding: RecipeBinding, *, html: bool = False
) -> ArtifactRef | None:
    if binding.artifact:
        return next(
            (
                row
                for row in request.capture.artifacts
                if row.artifact_id == binding.artifact
            ),
            None,
        )
    types = {"rendered_html", "http_html"} if html else {"network_json", "js_state"}
    return next(
        (row for row in request.capture.artifacts if row.artifact_type in types), None
    )


def _valid_listing_title(value: str) -> bool:
    normalized = " ".join(value.split()).casefold()
    return (
        bool(normalized)
        and normalized not in LISTING_TITLE_CTA_TITLES
        and not any(
            re.search(pattern, normalized) for pattern in LISTING_UTILITY_TITLE_PATTERNS
        )
    )


def _walk_path(payload: Any, path: str) -> list[Any]:
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in path.strip("/").split("/")
        if part
    ]
    values = [payload]
    for part in parts:
        next_values: list[Any] = []
        for value in values:
            if part == "*" and isinstance(value, dict):
                next_values.extend(value.values())
            elif part == "*" and isinstance(value, list):
                next_values.extend(value)
            elif isinstance(value, dict) and part in value:
                next_values.append(value[part])
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                next_values.append(value[int(part)])
        values = next_values
    return values


def _check_cardinality(
    binding: RecipeBinding, count: int, *, root: bool, allow_missing: bool
) -> None:
    if count == 0 and (root or (binding.required and not allow_missing)):
        raise _RecipeError(
            "recipe_root_not_found" if root else "recipe_binding_not_found",
            f"binding missing: {binding.binding_id}",
        )
    if binding.cardinality == "one" and count > 1:
        raise _RecipeError(
            "recipe_cardinality_changed", f"expected one: {binding.binding_id}"
        )
    if binding.cardinality == "many" and binding.required and count == 0:
        raise _RecipeError(
            "recipe_cardinality_changed",
            f"expected repeated values: {binding.binding_id}",
        )


def _check_record_root_minimum(
    request: ExtractionRequest, recipe: ExtractionRecipe, root_count: int
) -> None:
    """Enforce the min-repeated-records floor on the RAW record-root count.

    Finding 7: applied to the roots BEFORE the ``max_records`` slice so a
    ``max_records=1`` request cannot mask a real multi-record grid. The listing
    floor is derived from the request surface + config at replay time rather than
    trusting the persisted ``min_count`` alone, so legacy payloads (which default
    to ``min_count=1``) are still held to the min-2 listing floor.
    """

    if recipe.record_root.cardinality != "many":
        return
    is_listing = listing_schema(request.surface) is not None
    listing_floor = CASCADE_LISTING_MIN_REPEATED_RECORDS if is_listing else 1
    minimum = max(recipe.record_root.min_count, listing_floor)
    if 0 < root_count < minimum:
        raise _RecipeError(
            "recipe_cardinality_changed",
            f"record root grounded {root_count} < required {minimum}",
        )


def _check_scope(request: ExtractionRequest, recipe: ExtractionRecipe) -> None:
    host = normalize_domain(request.capture.final_url)
    if (
        request.surface.value != recipe.scope.surface
        or host != recipe.scope.domain.lower()
    ):
        raise _RecipeError(
            "recipe_template_mismatch", "recipe scope does not match request"
        )


def _check_capture_requirements(
    request: ExtractionRequest, recipe: ExtractionRecipe
) -> None:
    available = {row.artifact_type for row in request.capture.artifacts}
    missing = [
        requirement
        for requirement in recipe.capture_requirements
        if (requirement == "rendered_dom" and "rendered_html" not in available)
        or (requirement == "network_json" and "network_json" not in available)
    ]
    if missing:
        raise _RecipeError(
            "recipe_capture_requirement_missing",
            f"missing capture: {', '.join(missing)}",
        )


def _excluded_nodes(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    root: _Value,
    outcomes: list[BindingOutcome],
) -> set[int]:
    values = [
        value
        for binding in recipe.exclusions
        for value in _read(request, binding, root, outcomes, allow_missing=True)
    ]
    return {value.node.identity() for value in values if value.node is not None}


def _is_excluded(value: _Value, excluded: set[int]) -> bool:
    return bool(
        value.node
        and (
            value.node.identity() in excluded
            or any(node.identity() in excluded for node in value.node.ancestors())
        )
    )


def _expected_value(request: ExtractionRequest, compare_to: str | None) -> Any:
    if compare_to == "request.final_url":
        return request.capture.final_url
    if compare_to and compare_to.startswith("request."):
        return request.runtime_snapshot.get(compare_to.removeprefix("request."))
    return None


def _member(value: _Value, field: str) -> Any:
    return value.value.get(field) if isinstance(value.value, dict) else None


def _comparable(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _identity_value(field: str | None, value: Any) -> str:
    if field in {"url", "apply_url"}:
        return detail_url_resource_identity(str(value or ""))
    return _comparable(value)
