"""Grounding primitives for executable extraction recipes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    ExtractionRecipe,
    RecipeBinding,
    RecipeEntity,
    RecipeScope,
)
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.core.extraction_memory.recipe_artifacts import read_recipe_json_artifact
from app.core.records.normalizers import normalize_value
from app.core.records.normalizers import normalize_decimal_price
from app.core.shared.text_coerce import clean_text, strip_html_tags
from app.core.shared.url_utils import public_asset_delivery_url
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    PublicationEntry,
)
from app.extraction.json_walk import walk_json
from app.extraction.surfaces import Surface


def _detail_root(request: ExtractionRequest, artifact_id: str) -> RecipeBinding | None:
    artifact = next(
        (row for row in request.capture.artifacts if row.artifact_id == artifact_id),
        None,
    )
    if artifact is None and artifact_id.startswith("jsonld:"):
        return RecipeBinding(
            binding_id="record.root",
            source="json_pointer",
            artifact=artifact_id,
            path="/",
            cardinality="one",
            required=True,
        )
    if artifact is None:
        artifact = next(
            (
                item
                for item in request.capture.artifacts
                if item.artifact_type in {"rendered_html", "http_html"}
            ),
            None,
        )
    if artifact is None:
        return None
    artifact_id = artifact.artifact_id
    if artifact.artifact_type in {"rendered_html", "http_html"}:
        doc = request.artifact_reader.document_store.html(artifact_id)
        selector = "main" if doc.css_first("main") is not None else "body"
        return RecipeBinding(
            binding_id="record.root",
            source="dom_text",
            artifact=artifact_id,
            path=selector,
            cardinality="one",
            required=True,
        )
    return RecipeBinding(
        binding_id="record.root",
        source="artifact_text",
        artifact=artifact_id,
        path=".",
        cardinality="one",
        required=True,
    )


def _binding(
    row: Evidence,
    *,
    field: str,
    scope: str,
    request: ExtractionRequest | None = None,
) -> RecipeBinding | None:
    source = _source(row)
    if source is None:
        return None
    state = _grounded_binding_state(row, field, scope, request, source)
    if state is None:
        return None
    source, path, attribute, artifact_id, transform, binding_scope = state
    transform = _url_binding_transform(request, row, field, source, path, transform)
    return RecipeBinding(
        binding_id=f"field.{field}",
        source=source,
        artifact=artifact_id,
        collector_id=row.collector_id,
        path=path,
        scope=binding_scope,
        field=field,
        attribute=attribute,
        transform=transform,
        unit=_binding_unit(row, field),
        required=field in {"url", "title"},
    )


def _grounded_binding_state(row, field, scope, request, source):
    path = row.locator.value
    if source == "url_component" and path == "url":
        path = "final_url"
    state = (
        source,
        path,
        _attribute(field) if source == "dom_attribute" else None,
        row.artifact_id,
        "canonical",
        scope if source.startswith("dom_") else "document",
    )
    if request is None:
        return state
    if row.locator.kind in {"dom_path", "css_selector"}:
        from app.extraction.recipe_compiler_dom import _ground_detail_dom

        grounded = _ground_detail_dom(request, row, field)
        if grounded is None:
            return None
        path, attribute, artifact_id, transform = grounded
        return (
            "dom_attribute" if attribute else "dom_text",
            path,
            attribute,
            artifact_id,
            transform,
            "document",
        )
    if row.locator.kind in {"json_pointer", "network_json_pointer", "script_path"}:
        grounded = _grounded_json_path(request, row, field)
        transform = None
        if grounded is None:
            transformed = _grounded_json_transform(request, row, field)
            if transformed is None:
                return None
            grounded, transform = transformed
        transform = (
            transform
            or _grounded_value_transform(request, row, field, grounded)
            or _selected_representation_transform(row)
            or "canonical"
        )
        return source, grounded, state[2], row.artifact_id, transform, "document"
    return state


def _url_binding_transform(request, row, field, source, path, transform):
    if source != "url_component":
        return transform
    if field == "title":
        return "semantic_url_title"
    if field != "sku" or request is None:
        return transform
    selected = str(row.value or "")
    start = request.capture.final_url.casefold().find(selected.casefold())
    if not selected or start < 0:
        return transform
    prefix = "selected_slice_upper" if selected.isupper() else "selected_slice"
    return f"{prefix}:{start}:{len(selected)}"


def _source(row: Evidence):
    if row.locator.kind in {"css_selector", "dom_path"}:
        return (
            "dom_attribute"
            if _field_from_fact(row.fact_type) in {"url", "image_url"}
            else "dom_text"
        )
    if row.locator.kind == "json_pointer":
        return (
            "network_json_pointer"
            if row.collector_id in {"network_listing", "internal_api"}
            else "json_pointer"
        )
    if row.locator.kind == "network_json_pointer":
        return "network_json_pointer"
    if row.locator.kind == "script_path":
        return "script_path"
    if row.locator.kind == "url_component":
        return "url_component"
    return None


def _entry_evidence(
    entry: PublicationEntry, evidence: dict[str, Evidence]
) -> Evidence | None:
    rows = [
        evidence[evidence_id]
        for evidence_id in entry.evidence_ids
        if evidence_id in evidence
    ]
    field = _field(entry.path)
    expected = " ".join(str(entry.value or "").split()).casefold()
    expected_price = _decimal_price(entry.value) if "price" in field else None
    row = (
        rows[0]
        if rows
        and entry.rule_id in {"explicit_minor_unit_price", "corroborated_price_scale"}
        else next(
            (
                candidate
                for candidate in rows
                if " ".join(str(candidate.value or "").split()).casefold() == expected
                or (
                    expected_price is not None
                    and _decimal_price(candidate.value) == expected_price
                )
            ),
            rows[0] if rows else None,
        )
    )
    return (
        row.model_copy(
            update={
                "value": entry.value,
                "metadata": {
                    **row.metadata,
                    "recipe_source_value": row.value,
                    "recipe_selected_value": entry.value,
                },
            }
        )
        if row is not None
        else None
    )


def _decimal_price(value: object) -> Decimal | None:
    normalized = normalize_decimal_price(value)
    raw = normalized if normalized is not None else str(value).replace(",", "")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _field(path: str) -> str:
    if path.startswith("asset[") and path.endswith(".url"):
        return "image_url"
    if path.startswith("asset["):
        return ""
    return path.rsplit(".", 1)[-1] if "." in path else ""


def _binding_unit(row: Evidence, field: str) -> str | None:
    if "price" not in field:
        return None
    if row.metadata.get("recipe_rule_id") in {
        "explicit_minor_unit_price",
        "corroborated_price_scale",
    }:
        return "minor"
    if row.locator.value.casefold().endswith(
        ("priceincents", "price_in_cents", "priceinpaise", "price_in_paise")
    ):
        return "minor"
    unit = str(
        row.metadata.get("unit")
        or row.metadata.get("price_unit")
        or row.metadata.get("source_unit")
        or ""
    ).lower()
    return "minor" if unit in {"minor", "cents", "cent"} else "major"


def _grounded_json_path(
    request: ExtractionRequest, row: Evidence, field: str
) -> str | None:
    payload = read_recipe_json_artifact(request, row.artifact_id)
    if payload is None:
        return None
    target = _comparable_value(
        request, field, row.metadata.get("recipe_source_value", row.value)
    )
    candidates = _matching_json_paths(request, payload, field, target)
    if not candidates:
        candidates = _fallback_json_paths(request, payload, row, field, target)
    return _ranked_json_path(candidates, row.locator.value)


def _matching_json_paths(request, payload, field, target):
    return [
        node.pointer
        for node in walk_json(payload)
        if not isinstance(node.value, (dict, list))
        and _comparable_value(request, field, node.value) == target
    ]


def _fallback_json_paths(request, payload, row, field, target):
    if field in {"url", "apply_url"}:
        selected_url = str(row.value or "")
        return [
            node.pointer
            for node in walk_json(payload)
            if not isinstance(node.value, (dict, list))
            and len(str(node.value or "")) >= 4
            and str(node.value) in selected_url
        ]
    if field == "color":
        return [
            node.pointer
            for node in walk_json(payload)
            if isinstance(node.value, str)
            and _query_value(node.value, "shade") == target
        ]
    return []


def _ranked_json_path(candidates, locator_hint):
    if not candidates:
        return None
    hint_parts = locator_hint.casefold().strip("/").split("/")
    hint = set(hint_parts)
    return max(
        candidates,
        key=lambda path: (
            sum(
                left == right
                for left, right in zip(
                    hint_parts,
                    path.casefold().strip("/").split("/"),
                    strict=False,
                )
            ),
            len(hint.intersection(path.casefold().strip("/").split("/"))),
            -len(path),
        ),
    )


def _grounded_json_transform(
    request: ExtractionRequest, row: Evidence, field: str
) -> tuple[str, str] | None:
    payload = read_recipe_json_artifact(request, row.artifact_id)
    if payload is None:
        return None
    target = _comparable_value(request, field, row.value)
    if field == "brand" and (result := _brand_json_transform(payload, target)):
        return result
    if field == "location" and (
        result := _location_json_transform(request, payload, field, target)
    ):
        return result
    return _text_json_transform(payload, row, target)


def _brand_json_transform(payload, target):
    leaf = next(
        (
            node
            for node in walk_json(payload)
            if isinstance(node.value, str)
            and node.value.rsplit("/", 1)[-1].casefold() == target
        ),
        None,
    )
    return (leaf.pointer, "brand_path_leaf") if leaf is not None else None


def _location_json_transform(request, payload, field, target):
    for node in walk_json(payload):
        if not isinstance(node.value, dict):
            continue
        parts = [
            str(node.value.get(key) or "").strip()
            for key in ("addressLocality", "addressRegion", "addressCountry")
            if str(node.value.get(key) or "").strip()
        ]
        if parts and _comparable_value(request, field, ", ".join(parts)) == target:
            return node.pointer, "job_location"
    return None


def _text_json_transform(payload, row, target):
    from app.extraction.recipe_compiler_dom import _derived_text_transform

    for node in walk_json(payload):
        if not isinstance(node.value, str):
            continue
        stripped = node.value.strip("'\"")
        if stripped.casefold() == target:
            selected = str(row.value).strip()
            transform = (
                "casefold"
                if selected == selected.casefold() and stripped != selected
                else "strip_quotes"
            )
            return node.pointer, transform
        if transform := _derived_text_transform(node.value, target):
            return node.pointer, transform
    return None


def _comparable_value(request: ExtractionRequest, field: str, value: object) -> str:
    if "price" in field:
        normalized_price = normalize_decimal_price(value)
        if normalized_price is not None:
            try:
                return format(Decimal(normalized_price).normalize(), "f")
            except (InvalidOperation, ValueError):
                return normalized_price
        try:
            return format(Decimal(str(value).replace(",", "")).normalize(), "f")
        except (InvalidOperation, ValueError):
            pass
    normalized = normalize_value(field, value)
    if field in {"title", "brand", "description"}:
        normalized = clean_text(strip_html_tags(normalized))
    if field in {"url", "apply_url", "image_url", "additional_images"}:
        normalized = urljoin(request.capture.final_url, str(normalized or value or ""))
    if field in {"image_url", "additional_images"}:
        normalized = public_asset_delivery_url(normalized)
    return " ".join(str(normalized or "").split()).casefold()


def _selected_representation_transform(row: Evidence) -> str | None:
    source = str(row.metadata.get("recipe_source_value") or "").strip("'\"")
    selected = str(row.value or "").strip()
    if not source or not selected or source == selected:
        return None
    if source.casefold() == selected.casefold() and selected == selected.casefold():
        return "casefold"
    if source.rsplit("/", 1)[-1].casefold() == selected.casefold():
        return "path_leaf_title"
    return None


def _grounded_value_transform(
    request: ExtractionRequest,
    row: Evidence,
    field: str,
    path: str,
) -> str | None:
    payload = read_recipe_json_artifact(request, row.artifact_id)
    source = next(
        (node.value for node in walk_json(payload) if node.pointer == path),
        None,
    )
    if not isinstance(source, str):
        return None
    selected = str(row.value or "").strip()
    if source.strip("'\"").casefold() == selected.casefold():
        return "casefold" if selected == selected.casefold() else None
    if field == "color":
        query = parse_qs(urlsplit(source).query)
        name = next(
            (
                key
                for key, values in query.items()
                if values
                and _comparable_value(request, field, values[0])
                == _comparable_value(request, field, row.value)
            ),
            None,
        )
        if name:
            return f"query_param:{name}"
    from app.extraction.recipe_compiler_dom import _derived_text_transform

    return _derived_text_transform(source, _comparable_value(request, field, row.value))


def _field_from_fact(fact_type: str) -> str:
    return fact_type.rsplit(".", 1)[-1]


def _query_value(value: str, name: str) -> str:
    values = parse_qs(urlsplit(value).query).get(name, ())
    return " ".join(str(values[0]).split()).casefold() if values else ""


def _attribute(field: str) -> str:
    return "src" if field == "image_url" else "href"


def _required_fields(surface: Surface) -> tuple[str, ...]:
    return ("title", "url") if surface is not Surface.JOB_DETAIL else ("title",)


def _pointer_pattern(paths: list[str], *, field_leaf: bool = False) -> str:
    parts = [path.strip("/").split("/") for path in paths]
    width = min(map(len, parts)) - (1 if field_leaf else 0)
    result = [
        values[0] if len(set(values)) == 1 else "*"
        for values in zip(*(row[:width] for row in parts), strict=True)
    ]
    return "/" + "/".join(result)


def _relative_pointer(root: str, absolute: str) -> str:
    root_parts = [part for part in root.strip("/").split("/") if part]
    parts = [part for part in absolute.strip("/").split("/") if part]
    if any(
        root_part != "*" and root_part != part
        for root_part, part in zip(root_parts, parts, strict=False)
    ):
        return ""
    return "/" + "/".join(parts[len(root_parts) :])


def _all_bindings(recipe: ExtractionRecipe) -> tuple[RecipeBinding, ...]:
    return (recipe.record_root, *recipe.identity, *sum(recipe.fields.values(), ()))


def _failure(code, detail: str, diagnostics=()) -> DiscoveryResult:
    return DiscoveryResult(
        failure_code=code,
        detail=detail,
        collector_diagnostics=tuple(diagnostics),
    )


def _recipe(
    request: ExtractionRequest,
    root: RecipeBinding,
    identity: tuple[RecipeBinding, ...],
    fields: dict[str, tuple[RecipeBinding, ...]],
    required: tuple[str, ...],
    *,
    entities: dict[str, RecipeEntity] | None = None,
) -> ExtractionRecipe:
    page_url = request.capture.final_url or request.capture.requested_url
    return ExtractionRecipe(
        recipe_id=stable_id(
            "recipe-v2",
            normalize_domain(page_url),
            request.surface.value,
            normalize_route(page_url, request.surface.value),
        ),
        scope=RecipeScope(
            domain=normalize_domain(page_url),
            surface=request.surface.value,
            route_pattern=normalize_route(page_url, request.surface.value),
        ),
        capture_requirements=tuple(
            requirement
            for requirement, artifact_type in (
                ("rendered_dom", "rendered_html"),
                ("network_json", "network_json"),
            )
            if any(
                row.artifact_type == artifact_type for row in request.capture.artifacts
            )
            and any(
                binding.source.startswith("dom_")
                if requirement == "rendered_dom"
                else binding.source == "network_json_pointer"
                for binding in (root, *identity, *sum(fields.values(), ()))
            )
        ),
        record_root=root,
        identity=identity,
        entities=entities or {},
        fields=fields,
        required=("record.identity", *required),
    )
