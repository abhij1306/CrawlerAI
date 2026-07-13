"""Compile grounded discovery decisions into recipes without publishing records."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import parse_qs, urlsplit

from app.core.extraction_memory.recipe_contracts import (
    RecipeBinding,
    RecipeEntity,
)
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    PublicationEntry,
)

from app.extraction.recipe_compiler_grounding import (
    _binding,
    _binding_unit,
    _comparable_value,
    _entry_evidence,
    _field,
    _field_from_fact,
    _grounded_json_path,
    _grounded_json_transform,
    _grounded_value_transform,
    _pointer_pattern,
    _relative_pointer,
    _source,
    _selected_representation_transform,
)


def _detail_variant_recipe(
    request: ExtractionRequest,
    entries: tuple[PublicationEntry, ...],
    evidence: dict[str, Evidence],
) -> tuple[dict[str, RecipeEntity], RecipeBinding | None]:
    groups = _variant_groups(entries, evidence)
    if _all_dom_variant_groups(groups):
        return _detail_dom_variant_recipe(request, groups)
    root_groups = _variant_root_groups(request, groups)
    root = _json_variant_root(root_groups)
    if root is None:
        return {}, None
    fields = _compiled_variant_fields(request, groups, evidence, root_groups)
    if "color" not in fields:
        color = _color_binding_from_url(groups, fields.get("url", ()))
        if color:
            fields["color"] = color
    fields.update(_inherited_variant_offer_fields(request, entries, evidence, fields))
    return _variant_recipe_output(root, fields)


def _all_dom_variant_groups(groups) -> bool:
    return bool(groups) and all(
        row.locator.kind in {"css_selector", "dom_path"}
        for rows in groups.values()
        for _field_name, row in rows
    )


def _json_variant_root(root_groups):
    roots = [row[1] for row in root_groups]
    root_rows = [row[2] for row in root_groups]
    if not roots or len({row.artifact_id for row in root_rows}) != 1:
        return None
    root_path = _pointer_pattern(roots)
    if "*" not in root_path and len(roots) > 1:
        return None
    return RecipeBinding(
        binding_id="entity.variant.root",
        source=_source(root_rows[0]) or "json_pointer",
        artifact=root_rows[0].artifact_id,
        path=root_path,
        scope="document",
        cardinality="many",
        required=False,
    )


def _compiled_variant_fields(request, groups, evidence, root_groups):
    names = sorted({field for rows in groups.values() for field, _row in rows})
    return {
        field: binding
        for field in names
        if (
            binding := _variant_field_binding(
                request, groups, evidence, field, root_groups
            )
        )
        is not None
    }


def _color_binding_from_url(groups, url_bindings):
    if not url_bindings:
        return ()
    sample_url = next(
        (
            str(row.value)
            for rows in groups.values()
            for name, row in rows
            if name == "url" and isinstance(row.value, str)
        ),
        "",
    )
    color_param = next(
        (
            name
            for name in parse_qs(urlsplit(sample_url).query)
            if name.casefold() == "color" or name.casefold().endswith("_color")
        ),
        None,
    )
    if not color_param:
        return ()
    return tuple(
        binding.model_copy(
            update={
                "binding_id": f"entity.variant.color.{index}",
                "field": "color",
                "transform": f"query_param:{color_param}",
            }
        )
        for index, binding in enumerate(url_bindings)
    )


def _variant_recipe_output(root, fields):
    if not fields:
        return {}, None
    identity = fields.get("sku", fields.get("variant_id", ()))
    entity = RecipeEntity(root=root, identity=identity, fields=fields)
    output = RecipeBinding(
        binding_id="field.variants",
        source="json_pointer",
        path="/",
        scope="entity.variant",
        field="variants",
        cardinality="many",
    )
    return {"variant": entity}, output


def _detail_dom_variant_recipe(request, groups):
    root = _dom_variant_root(request, groups)
    if root is None:
        return {}, None
    fields = _dom_variant_fields(request, groups)
    return _variant_recipe_output(root, fields)


def _dom_variant_root(request, groups):
    roots: list[RecipeBinding] = []
    rows: list[Evidence] = []
    for group in groups.values():
        selected = next(
            (row for field, row in group if field in {"sku", "variant_id"}),
            group[0][1],
        )
        binding = _binding(
            selected,
            field=_field_from_fact(selected.fact_type),
            scope="document",
            request=request,
        )
        if binding is None:
            return None
        roots.append(binding)
        rows.append(selected)
    selectors = {
        row.locator.value for row in rows if row.locator.kind == "css_selector"
    }
    path = (
        selectors.pop()
        if len(selectors) == 1
        else _repeated_css_pattern([binding.path for binding in roots])
    )
    if not path:
        return None
    return RecipeBinding(
        binding_id="entity.variant.root",
        source="dom_text",
        artifact=roots[0].artifact,
        path=path,
        scope="document",
        cardinality="many",
    )


def _dom_variant_fields(request, groups):
    names = sorted({field for rows in groups.values() for field, _row in rows})
    fields: dict[str, tuple[RecipeBinding, ...]] = {}
    for field in names:
        candidates = _dom_variant_field_candidates(request, groups, field)
        unique = {
            (
                binding.source,
                binding.attribute,
                binding.transform,
                binding.unit,
            ): binding
            for binding in candidates
        }
        if len(candidates) == len(groups) and unique:
            fields[field] = tuple(unique.values())
    return fields


def _dom_variant_field_candidates(request, groups, field):
    candidates: list[RecipeBinding] = []
    for rows in groups.values():
        selected = next((row for name, row in rows if name == field), None)
        if selected is None:
            continue
        binding = _binding(selected, field=field, scope="document", request=request)
        if binding is None:
            continue
        candidates.append(
            binding.model_copy(
                update={
                    "binding_id": f"entity.variant.{field}.{len(candidates)}",
                    "path": ".",
                    "scope": "entity.variant",
                }
            )
        )
    return candidates


def _repeated_css_pattern(paths: list[str]) -> str:
    parts = [path.split(" > ") for path in paths]
    if not parts or len({len(row) for row in parts}) != 1:
        return ""
    pattern: list[str] = []
    for values in zip(*parts, strict=True):
        if len(set(values)) == 1:
            pattern.append(values[0])
            continue
        tags = {value.split(":nth-of-type", 1)[0] for value in values}
        if len(tags) != 1:
            return ""
        pattern.append(tags.pop())
    return " > ".join(pattern)


def _inherited_variant_offer_fields(request, entries, evidence, existing):
    inherited = {}
    for entry in entries:
        field = _field(entry.path)
        if entry.path.startswith("variant[") or field not in {
            "price",
            "currency",
            "availability",
        }:
            continue
        row = _entry_evidence(entry, evidence)
        if row is None:
            continue
        binding = _binding(row, field=field, scope="document", request=request)
        if binding is not None:
            inherited[field] = (
                *existing.get(field, ()),
                binding.model_copy(
                    update={
                        "binding_id": f"entity.variant.{field}",
                        "scope": "document",
                        "rule_id": DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
                    }
                ),
            )
    return inherited


def _variant_groups(entries, evidence) -> dict[str, list[tuple[str, Evidence]]]:
    groups: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)
    for entry in entries:
        if not entry.path.startswith("variant["):
            continue
        field = _field(entry.path)
        row = _entry_evidence(entry, evidence)
        if (
            field
            and row is not None
            and row.locator.kind
            in {
                "json_pointer",
                "network_json_pointer",
                "script_path",
                "css_selector",
                "dom_path",
            }
        ):
            groups[entry.entity_id].append(
                (
                    field,
                    row.model_copy(
                        update={
                            "metadata": {
                                **row.metadata,
                                "recipe_rule_id": entry.rule_id,
                            }
                        }
                    ),
                )
            )
    return groups


def _variant_root_groups(request, groups):
    rows_by_root = []
    for entity_id, rows in groups.items():
        row = next(
            (
                candidate
                for _field_name, candidate in rows
                if candidate.fact_type.startswith("variant.")
            ),
            None,
        )
        if row is None:
            continue
        grounded = _grounded_json_path(request, row, _field_from_fact(row.fact_type))
        if not grounded:
            continue
        rows_by_root.append((entity_id, grounded.rsplit("/", 1)[0], row))
    return sorted(rows_by_root, key=lambda item: _pointer_sort_key(item[1]))


def _pointer_sort_key(path: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in path.strip("/").split("/")
    )


def _variant_field_binding(request, groups, evidence, field, root_groups):
    if _variant_currency_from_page(groups, field):
        return None
    grounded_rows = [
        grounded
        for entity_id, entity_root, root_row in root_groups
        if (
            grounded := _grounded_variant_field(
                request,
                groups,
                evidence,
                field,
                entity_id,
                entity_root,
                root_row,
            )
        )
        is not None
    ]
    return _variant_bindings(request, field, grounded_rows)


def _variant_currency_from_page(groups, field) -> bool:
    return field == "currency" and all(
        row.metadata.get("recipe_rule_id") == "currency_from_page_url_hint"
        for rows in groups.values()
        for name, row in rows
        if name == field
    )


def _grounded_variant_field(
    request, groups, evidence, field, entity_id, entity_root, root_row
):
    selected = next(
        (row for name, row in groups[entity_id] if name == field),
        None,
    )
    if selected is None:
        return None
    selected_value = _comparable_value(
        request,
        field,
        selected.metadata.get("recipe_source_value", selected.value),
    )
    matched = _exact_variant_evidence(
        request, evidence, selected, selected_value, field, entity_root, root_row
    )
    if matched is None:
        matched = _transformed_variant_evidence(
            request, evidence, selected, selected_value, field, entity_root, root_row
        )
    if matched is None:
        return None
    row, grounded, transform = matched
    row = row.model_copy(
        update={
            "value": selected.value,
            "metadata": {
                **row.metadata,
                "recipe_rule_id": selected.metadata.get("recipe_rule_id"),
                "recipe_source_value": row.value,
                "recipe_selected_value": selected.value,
                "recipe_grounded_transform": transform,
            },
        }
    )
    grounded = grounded or _grounded_json_path(request, row, field)
    return (row, entity_root, grounded) if grounded else None


def _exact_variant_evidence(
    request, evidence, selected, selected_value, field, entity_root, root_row
):
    row = next(
        (
            candidate
            for candidate in evidence.values()
            if candidate.fact_type == selected.fact_type
            and candidate.artifact_id == root_row.artifact_id
            and _comparable_value(request, field, candidate.value) == selected_value
            and (grounded := _grounded_json_path(request, candidate, field))
            and grounded.startswith(f"{entity_root}/")
        ),
        None,
    )
    if row is None:
        return None
    return row, _grounded_json_path(request, row, field), None


def _transformed_variant_evidence(
    request, evidence, selected, selected_value, field, entity_root, root_row
):
    for candidate in evidence.values():
        if candidate.fact_type != selected.fact_type:
            continue
        if candidate.artifact_id != root_row.artifact_id:
            continue
        if _comparable_value(request, field, candidate.value) != selected_value:
            continue
        transformed = _grounded_json_transform(request, candidate, field)
        if transformed and transformed[0].startswith(f"{entity_root}/"):
            return candidate, transformed[0], transformed[1]
    return None


def _variant_bindings(request, field, grounded_rows):
    if not grounded_rows:
        return None
    relatives = [
        (_relative_pointer(entity_root, grounded), row, grounded)
        for row, entity_root, grounded in grounded_rows
    ]
    if any(not relative or relative == "/" for relative, _row, _path in relatives):
        return None
    unique = list(dict.fromkeys(relative for relative, _row, _path in relatives))
    return tuple(
        _variant_binding(request, field, index, relative, relatives)
        for index, relative in enumerate(unique)
    )


def _variant_binding(request, field, index, relative, relatives):
    row, grounded = next(
        (row, grounded)
        for candidate, row, grounded in relatives
        if candidate == relative
    )
    return RecipeBinding(
        binding_id=f"entity.variant.{field}.{index}",
        source=_source(row) or "json_pointer",
        artifact=row.artifact_id,
        path=relative,
        scope="entity.variant",
        field=field,
        transform=_variant_transform(request, row, field, grounded, relative),
        unit=_binding_unit(row, field),
        collector_id=row.collector_id,
    )


def _variant_transform(request, row, field, grounded, relative):
    if (
        field == "availability"
        and row.metadata.get("recipe_rule_id") == "availability_from_stock_quantity"
    ):
        return "availability_from_stock_quantity"
    return (
        _grounded_value_transform(request, row, field, grounded)
        or (
            "query_param:shade"
            if field == "color" and relative.endswith("/url")
            else None
        )
        or row.metadata.get("recipe_grounded_transform")
        or _selected_representation_transform(row)
        or "canonical"
    )
