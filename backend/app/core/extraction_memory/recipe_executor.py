"""Mechanical interpreter for frozen extraction recipes; no discovery or storage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.domain_utils import normalize_domain
from app.core.config.extraction_rules import (
    LISTING_MARKET_LOCALE_GENDER_SEGMENTS,
    LISTING_MARKET_LOCALE_PRODUCT_PREFIX,
    LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS,
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
from app.core.records.normalizers import normalize_decimal_price, normalize_value
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_url_resource_identity,
)
from app.core.config.locale_format_rules import (
    currency_hint_from_page_url,
    locale_hint_from_page_url,
    parse_money,
)
from app.core.shared.field_coerce_price import extract_currency_code
from app.core.shared.text_coerce import clean_text, strip_html_tags
from app.core.shared.url_utils import largest_srcset_url, public_asset_delivery_url
from app.extraction.contracts import ArtifactRef, ExtractionRequest
from app.extraction.documents import HtmlDocument, HtmlNode


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
        values: list[_Value] = []
        collect_many = any(binding.cardinality == "many" for binding in bindings)
        for binding in bindings:
            scopes = _binding_scopes(binding, root, entities)
            binding_values: list[_Value] = []
            for scope in scopes:
                binding_values.extend(
                    _read(request, binding, scope, outcomes, allow_missing=True)
                )
            if binding_values:
                values.extend(binding_values)
                if not collect_many:
                    break
        values = [row for row in values if not _is_excluded(row, excluded)]
        if values:
            if collect_many:
                flattened = [
                    item
                    for value in values
                    for item in (
                        value.value
                        if isinstance(value.value, (list, tuple))
                        else (value.value,)
                    )
                ]
                record[field] = list(dict.fromkeys(map(repr, flattened)))
                marker_values = {repr(item): item for item in flattened}
                record[field] = [marker_values[marker] for marker in record[field]]
            else:
                record[field] = (
                    values[0].value
                    if len(values) == 1
                    else [value.value for value in values]
                )
        elif field in recipe.required:
            raise _RecipeError(
                "recipe_required_field_missing", f"required field missing: {field}"
            )
    if "record.identity" in recipe.required and not identity:
        raise _RecipeError(
            "recipe_identity_mismatch", "record identity not established"
        )
    return record


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
    scope = root if spec.root.scope == "record.root" else None
    values = _read(request, spec.root, scope, outcomes, allow_missing=True)
    if spec.identity or spec.fields:
        identified: list[_Value] = []
        for value in values:
            payload: dict[str, Any] = {}
            lineage: dict[str, dict[str, object]] = {}
            for binding in spec.identity:
                rows = _read(
                    request,
                    binding,
                    None if binding.scope == "document" else value,
                    outcomes,
                    allow_missing=True,
                )
                if rows:
                    output_field = (
                        binding.field or binding.binding_id.rsplit(".", 1)[-1]
                    )
                    payload[output_field] = rows[0].value
                    lineage[output_field] = _binding_lineage(binding, rows[0])
            for field, bindings in spec.fields.items():
                for binding in bindings:
                    rows = _read(
                        request,
                        binding,
                        None if binding.scope == "document" else value,
                        outcomes,
                        allow_missing=True,
                    )
                    if rows:
                        payload[field] = (
                            [row.value for row in rows]
                            if binding.cardinality == "many"
                            else rows[0].value
                        )
                        lineage[field] = _binding_lineage(binding, rows[0])
                        break
            if spec.identity and not any(
                payload.get(binding.field or binding.binding_id.rsplit(".", 1)[-1])
                for binding in spec.identity
            ):
                continue
            if lineage:
                payload["_binding_lineage"] = lineage
            identified.append(
                _Value(payload or value.value, value.source_path, value.node)
            )
        values = identified
    return values


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
        value = _transform(request, row.value, binding)
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
        base: HtmlDocument | HtmlNode
        if scope is not None and scope.node is not None:
            base = scope.node
        else:
            artifact = _artifact(request, binding, html=True)
            if artifact is None:
                return []
            base = request.artifact_reader.document_store.html(artifact.artifact_id)
        nodes = (
            [base]
            if binding.path == "." and isinstance(base, HtmlNode)
            else list(base.safe_css(binding.path))
        )
        if binding.sense == "price_text" and not binding.attribute:
            nodes = [
                node
                for node in nodes
                if re.search(
                    LISTING_VISUAL_PRICE_REGEX_PATTERN,
                    node.attribute(binding.attribute or "") or node.content_text(),
                    re.IGNORECASE,
                )
            ]
        if binding.sense == "listing_title":
            nodes = [
                node
                for node in nodes
                if _valid_listing_title(
                    node.attribute(binding.attribute or "") or node.content_text()
                )
            ]
        if root:
            return [
                _Value(node, f"{node.artifact_id}:{binding.path}", node)
                for node in nodes
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
    if binding.source == "url_component":
        return [
            _Value(
                _url_component(request.capture.final_url, binding.path),
                f"url:{binding.path}",
            )
        ]
    if binding.source == "artifact_text":
        artifact = _artifact(request, binding)
        return (
            [
                _Value(
                    request.artifact_reader.read_text(artifact),
                    f"{artifact.artifact_id}:text",
                )
            ]
            if artifact is not None
            else []
        )
    payload = (
        scope.value
        if scope is not None and (scope.node is None or binding.field == "variants")
        else None
    )
    artifact = _artifact(request, binding)
    if (
        payload is None
        and binding.source == "script_path"
        and (
            artifact is None or artifact.artifact_type in {"rendered_html", "http_html"}
        )
    ):
        payload = read_recipe_json_artifact(request, binding.artifact)
        if payload is None:
            return []
        prefix = str(binding.artifact)
    elif payload is None:
        if artifact is None:
            payload = read_recipe_json_artifact(request, binding.artifact)
            if payload is None:
                return []
            prefix = str(binding.artifact)
        else:
            payload = request.artifact_reader.read_json(artifact)
            prefix = artifact.artifact_id
    else:
        assert scope is not None
        prefix = scope.source_path
    return [
        _Value(value, f"{prefix}:{binding.path}")
        for value in _walk_path(payload, binding.path)
    ]


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
        if requirement == "rendered_dom"
        and "rendered_html" not in available
        or requirement == "network_json"
        and "network_json" not in available
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


def _transform(request: ExtractionRequest, value: Any, binding: RecipeBinding) -> Any:
    if binding.transform == "identity":
        return value
    if binding.transform == "after_colon" and isinstance(value, str):
        value = value.partition(":")[2].strip()
    elif binding.transform == "registered_prefix" and isinstance(value, str):
        match = re.match(r"^(.+?®)(?:\s|$)", value.strip())
        value = match.group(1) if match else None
    elif binding.transform == "first_token" and isinstance(value, str):
        value = value.strip().split(" ", 1)[0].strip("'\"")
    elif binding.transform == "last_token" and isinstance(value, str):
        value = value.strip().rsplit(" ", 1)[-1].strip("'\"")
    elif binding.transform == "strip_quotes" and isinstance(value, str):
        value = value.strip("'\"")
    elif binding.transform == "strip_leading_symbols" and isinstance(value, str):
        value = re.sub(r"^[^A-Za-z0-9]+", "", value).strip()
    elif binding.transform == "restore_market_locale" and isinstance(value, str):
        value = _restore_market_locale(request.capture.final_url, value)
    elif binding.transform == "largest_srcset" and isinstance(value, str):
        value = largest_srcset_url(value)
    elif binding.transform == "semantic_url_title" and isinstance(value, str):
        value = detail_title_from_url(value)
    elif binding.transform == "dom_price":
        value = parse_money(
            value,
            locale_hint=locale_hint_from_page_url(request.capture.final_url),
        )
    elif binding.transform == "dom_currency":
        value = extract_currency_code(value)
    elif binding.transform == "casefold" and isinstance(value, str):
        value = value.strip("'\"").casefold()
    elif binding.transform == "path_leaf_title" and isinstance(value, str):
        value = value.rsplit("/", 1)[-1].title()
    elif binding.transform == "currency_from_page_url":
        value = currency_hint_from_page_url(request.capture.final_url)
    elif binding.transform == "currency_from_price_symbol":
        value = extract_currency_code(value)
    elif binding.transform == "availability_from_stock_quantity":
        try:
            value = "in_stock" if Decimal(str(value)) > 0 else "out_of_stock"
        except (InvalidOperation, ValueError):
            value = None
    elif binding.transform == "job_location" and isinstance(value, dict):
        value = ", ".join(
            str(value.get(key) or "").strip()
            for key in ("addressLocality", "addressRegion", "addressCountry")
            if str(value.get(key) or "").strip()
        )
    elif binding.transform and binding.transform.startswith("value_url_template:"):
        template = binding.transform.partition(":")[2]
        value = template.replace("{value}", str(value))
    elif binding.transform == "attribute_json_availability" and isinstance(value, str):
        try:
            state = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        selectable = state.get("selectable") if isinstance(state, dict) else None
        value = (
            "out_of_stock"
            if selectable in {False, 0, "0", "false", "False"}
            else "in_stock"
            if selectable in {True, 1, "1", "true", "True"}
            else None
        )
    elif binding.transform and binding.transform.startswith("prefix_words:"):
        count = int(binding.transform.rsplit(":", 1)[1])
        value = " ".join(str(value).split()[:count])
    elif binding.transform and binding.transform.startswith("host_words:"):
        lengths = [int(item) for item in binding.transform.partition(":")[2].split(",")]
        ignored = {
            "",
            "www",
            "shop",
            "store",
            "us",
            "usa",
            "uk",
            "in",
            "com",
            "co",
            "net",
            "org",
        }
        labels = [
            label for label in str(value).casefold().split(".") if label not in ignored
        ]
        compact = re.sub(r"[^a-z0-9]", "", max(labels, key=len) if labels else "")
        for suffix in ("beauty", "cosmetics", "official", "online", "shop", "store"):
            if compact.endswith(suffix):
                compact = compact[: -len(suffix)]
                break
        pieces = []
        offset = 0
        for segment_length in lengths:
            pieces.append(compact[offset : offset + segment_length])
            offset += segment_length
        value = " ".join(piece.title() for piece in pieces)
    elif binding.transform and binding.transform.startswith("uppercase_host_words:"):
        lengths = [int(item) for item in binding.transform.rsplit(":", 1)[1].split(",")]
        host = urlsplit(str(value)).hostname or str(value)
        compact = re.sub(r"[^a-z0-9]", "", host.casefold().split(".")[0])
        pieces = []
        offset = 0
        for segment_length in lengths:
            pieces.append(compact[offset : offset + segment_length])
            offset += segment_length
        value = " ".join(pieces).upper()
    elif binding.transform and binding.transform.startswith("slug_words:"):
        _name, start, raw_lengths = binding.transform.split(":", 2)
        words = re.findall(r"[a-z0-9]+", str(value).casefold())
        index = int(start)
        count = len(raw_lengths.split(","))
        value = " ".join(word.title() for word in words[index : index + count])
    elif binding.transform and binding.transform.startswith("uppercase_slug_words:"):
        _name, start, raw_lengths = binding.transform.split(":", 2)
        words = re.findall(r"[a-z0-9]+", str(value).casefold())
        index = int(start)
        count = len(raw_lengths.split(","))
        value = " ".join(words[index : index + count]).upper()
    elif binding.transform and binding.transform.startswith("selected_slice:"):
        _name, start, length = binding.transform.split(":", 2)
        value = str(value)[int(start) : int(start) + int(length)]
    elif binding.transform and binding.transform.startswith("selected_slice_upper:"):
        _name, start, length = binding.transform.split(":", 2)
        value = str(value)[int(start) : int(start) + int(length)].upper()
    elif binding.transform and binding.transform.startswith("substring:"):
        _name, start, length = binding.transform.split(":", 2)
        value = str(value)[int(start) : int(start) + int(length)]
    if binding.transform and binding.transform.startswith("query_param:"):
        if not isinstance(value, str):
            return None
        name = binding.transform.partition(":")[2]
        values = parse_qs(urlsplit(value).query).get(name, ())
        value = values[0] if values else None
    if binding.field in {
        "url",
        "apply_url",
        "image_url",
        "additional_images",
    } and isinstance(value, str):
        value = urljoin(request.capture.final_url, value)
    if binding.field in {"image_url", "additional_images"}:
        value = public_asset_delivery_url(value)
    if binding.field == "additional_images" and isinstance(value, str):
        return value
    if binding.field == "variants":
        return value
    if binding.field in {"title", "brand", "description"}:
        value = clean_text(strip_html_tags(value))
    if binding.field in {"variant_id", "sku", "gtin"} and value is not None:
        value = str(value).strip()
    if binding.unit == "minor" and binding.field and "price" in binding.field:
        normalized = normalize_decimal_price(value, interpret_integral_as_cents=True)
        try:
            return f"{Decimal(str(normalized)).quantize(Decimal('0.01')):f}"
        except (InvalidOperation, ValueError):
            return normalized
    if binding.unit == "major" and binding.field and "price" in binding.field:
        try:
            return f"{Decimal(str(value).replace(',', '')).quantize(Decimal('0.01')):f}"
        except (InvalidOperation, ValueError):
            return normalize_decimal_price(value)
    if binding.field == "currency" and isinstance(value, str):
        return value.strip().upper()
    if binding.transform or binding.field:
        return normalize_value(binding.field or "", value)
    return value


def _member(value: _Value, field: str) -> Any:
    return value.value.get(field) if isinstance(value.value, dict) else None


def _comparable(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _identity_value(field: str | None, value: Any) -> str:
    if field in {"url", "apply_url"}:
        return detail_url_resource_identity(str(value or ""))
    return _comparable(value)


def _url_component(url: str, component: str) -> str | None:
    parsed = urlsplit(url)
    if component == "final_url":
        return url
    if component == "path":
        return parsed.path
    if component == "host":
        return parsed.hostname
    if component.startswith("query."):
        return next(
            iter(parse_qs(parsed.query).get(component.removeprefix("query."), [])), None
        )
    return None


def _restore_market_locale(page_url: str, href: str) -> str:
    product_url = urljoin(page_url, href)
    page = urlsplit(page_url)
    product = urlsplit(product_url)
    if normalize_domain(page_url) != normalize_domain(product_url):
        return product_url
    page_parts = tuple(part for part in page.path.split("/") if part)
    product_parts = tuple(part for part in product.path.split("/") if part)
    category_index = next(
        (
            index
            for index, part in enumerate(page_parts)
            if part.casefold() in LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS
        ),
        None,
    )
    if category_index is None:
        return product_url
    prefix = page_parts[:category_index]
    if not prefix or product_parts[: len(prefix)] == prefix or not product_parts:
        return product_url
    first = product_parts[0].casefold()
    if first == LISTING_MARKET_LOCALE_PRODUCT_PREFIX:
        parts = (*prefix, *product_parts)
    elif first in LISTING_MARKET_LOCALE_GENDER_SEGMENTS:
        parts = (*prefix, LISTING_MARKET_LOCALE_PRODUCT_PREFIX, *product_parts)
    else:
        return product_url
    return product._replace(path="/" + "/".join(parts)).geturl()
