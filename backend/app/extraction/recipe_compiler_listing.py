"""Compile repeated listing records into executable recipes."""

from __future__ import annotations

from collections import defaultdict
import re

from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeBinding,
)
from app.core.extraction_memory.recipe_artifacts import read_recipe_json_artifact
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    PublicationEntry,
)
from app.extraction.json_walk import walk_json

from app.extraction.recipe_compiler_dom import _dom_pattern, _relative_css
from app.extraction.recipe_compiler_grounding import (
    _attribute,
    _comparable_value,
    _entry_evidence,
    _field,
    _grounded_json_path,
    _pointer_pattern,
    _recipe,
    _relative_pointer,
    _required_fields,
    _source,
)

_CARD_LOCATOR = re.compile(r"^(.*):nth-match\(\d+\)\s+(\w+)$")


def _listing_recipe(
    request: ExtractionRequest,
    entries: tuple[PublicationEntry, ...],
    evidence: dict[str, Evidence],
) -> ExtractionRecipe | None:
    required = _required_fields(request.surface)
    complete = _complete_listing_groups(entries, evidence, required)
    if not complete:
        return None
    url_rows = _listing_field_rows(complete, "url")
    root = _repeated_root(request, url_rows, title_rows=_listing_field_rows(complete, "title"))
    if root is None:
        return None
    fields = _listing_bindings(request, complete, root)
    if not all(field in fields for field in required):
        return None
    identity = (
        fields["url"][0].model_copy(
            update={"binding_id": "record.identity.url", "required": True}
        ),
    )
    return _recipe(request, root, identity, fields, required)


def _complete_listing_groups(entries, evidence, required):
    groups: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)
    for entry in entries:
        field = _field(entry.path)
        row = _entry_evidence(entry, evidence)
        if field and row is not None:
            groups[entry.entity_id].append((field, row))
    complete = {
        entity_id: rows
        for entity_id, rows in groups.items()
        if set(required) <= {field for field, _row in rows}
    }
    by_artifact = defaultdict(dict)
    for entity_id, rows in complete.items():
        artifact_ids = {row.artifact_id for _field_name, row in rows}
        if len(artifact_ids) == 1:
            by_artifact[next(iter(artifact_ids))][entity_id] = rows
    return max(by_artifact.values(), key=len, default={})


def _listing_field_rows(complete, field: str) -> list[Evidence]:
    rows = [next(row for name, row in rows if name == field) for rows in complete.values() if any(name == field for name, _row in rows)]
    return sorted(rows, key=_listing_row_order)


def _listing_row_order(row: Evidence) -> tuple[int, str]:
    match = _CARD_LOCATOR.fullmatch(row.locator.value)
    if match is not None:
        index = re.search(r":nth-match\((\d+)\)", row.locator.value)
        return (int(index.group(1)) if index else 0, row.locator.value)
    indexes = re.findall(r"/(\d+)(?:/|$)", row.locator.value)
    return (int(indexes[-1]) if indexes else 0, row.locator.value)


def _listing_bindings(request, complete, root):
    fields: dict[str, tuple[RecipeBinding, ...]] = {}
    names = sorted({name for rows in complete.values() for name, _row in rows})
    for field in names:
        rows = _listing_field_rows(complete, field)
        binding = _repeated_binding(rows, field=field, root=root, request=request)
        if binding is not None:
            fields[field] = (binding,)
    return fields


def _repeated_root(
    request: ExtractionRequest,
    rows: list[Evidence],
    *,
    title_rows: list[Evidence] | None = None,
) -> RecipeBinding | None:
    if not rows:
        return None
    first = rows[0]
    parts = _repeated_root_parts(request, rows, title_rows=title_rows)
    if parts is None:
        return None
    artifact, path, source = parts
    if not path or source is None:
        return None
    return RecipeBinding(
        binding_id="record.root",
        source=source,
        artifact=artifact,
        collector_id=first.collector_id,
        path=path,
        scope="document",
        cardinality="many",
        required=True,
    )


def _repeated_root_parts(request, rows, *, title_rows=None):
    first = rows[0]
    kinds = {row.locator.kind for row in rows}
    if kinds == {"json_pointer"}:
        normalized = [_grounded_structured_pointer(request, row, "url") for row in rows]
        artifacts = {artifact for artifact, _path in normalized}
        if len(artifacts) != 1:
            return None
        return (
            normalized[0][0],
            _pointer_pattern(
                [pointer for _artifact, pointer in normalized], field_leaf=True
            ),
            _source(first),
        )
    if kinds == {"dom_path"}:
        return (
            first.artifact_id,
            _dom_pattern([row.locator.value for row in rows]),
            "dom_text",
        )
    if kinds != {"css_selector"}:
        return None
    matches = [_CARD_LOCATOR.fullmatch(row.locator.value) for row in rows]
    selectors = {match.group(1) for match in matches if match is not None}
    selector = selectors.pop() if len(selectors) == 1 else ""
    path = (
        _grounded_listing_root(request, rows, selector, title_rows=title_rows)
        if selector
        else ""
    )
    return first.artifact_id, path or selector, "dom_text"


def _grounded_listing_root(
    request: ExtractionRequest,
    rows: list[Evidence],
    selector: str,
    *,
    title_rows: list[Evidence] | None = None,
) -> str:
    if not rows or not selector:
        return ""
    artifact = rows[0].artifact_id
    document = request.artifact_reader.document_store.html(artifact)
    candidate_ids = {node.identity() for node in document.css(selector)}
    paths: list[str] = []
    for index, row in enumerate(rows):
        target = _comparable_value(request, "url", row.value)
        anchor = next(
            (
                node
                for node in document.css("a[href]")
                if _comparable_value(request, "url", node.attribute("href")) == target
            ),
            None,
        )
        if anchor is None:
            raw_target = _comparable_value(
                request, "url", row.metadata.get("recipe_source_value", row.raw_value)
            )
            anchor = next(
                (
                    node
                    for node in document.css("a[href]")
                    if _comparable_value(request, "url", node.attribute("href"))
                    == raw_target
                ),
                None,
            )
        if anchor is None and title_rows and index < len(title_rows):
            title = _comparable_value(request, "title", title_rows[index].value)
            anchor = next(
                (
                    node
                    for node in document.css("a[href]")
                    if _comparable_value(request, "title", node.attribute("title"))
                    == title
                    or _comparable_value(request, "title", node.content_text()) == title
                ),
                None,
            )
        if anchor is None:
            return ""
        ancestors = []
        node = anchor
        while node is not None:
            if node.identity() in candidate_ids:
                ancestors.append(node)
            node = node.parent()
        if not ancestors:
            return ""
        paths.append(
            min(ancestors, key=lambda item: item.dom_path().count("/")).dom_path()
        )
    return _dom_pattern(paths)


def _repeated_binding(
    rows: list[Evidence],
    *,
    field: str,
    root: RecipeBinding,
    request: ExtractionRequest | None = None,
) -> RecipeBinding | None:
    if not rows or len({row.artifact_id for row in rows}) != 1:
        return None
    first = rows[0]
    grounded = (
        _grounded_repeated_dom_binding(request, rows, root, field)
        if first.locator.kind in {"css_selector", "dom_path"}
        and root.source == "dom_text"
        else None
    )
    path = (
        grounded[0]
        if grounded
        else _repeated_relative_path(rows, root, request=request, field=field)
    )
    if not path:
        return None
    attribute = grounded[1] if grounded else None
    return RecipeBinding(
        binding_id=f"field.{field}",
        source=("dom_attribute" if attribute else _repeated_source(first, root, field)),
        artifact=(
            _structured_pointer(first)[0]
            if first.locator.kind == "json_pointer"
            else first.artifact_id
        ),
        collector_id=first.collector_id,
        path=path,
        scope="record.root",
        field=field,
        attribute=attribute
        or (_attribute(field) if field in {"url", "image_url"} else None),
        transform=(
            _structured_url_template(request, rows)
            if field == "url" and first.locator.kind == "json_pointer"
            else "restore_market_locale"
            if field == "url"
            else "identity"
            if field == "price"
            else None
        ),
        sense="listing_title"
        if field == "title"
        else ("price_text" if field == "price" else None),
        required=field in {"url", "title"},
    )


def _structured_url_template(
    request: ExtractionRequest | None, rows: list[Evidence]
) -> str:
    if request is None:
        return "restore_market_locale"
    templates: set[str] = set()
    for row in rows:
        artifact, pointer = _grounded_structured_pointer(request, row, "url")
        payload = read_recipe_json_artifact(request, artifact)
        source = next(
            (node.value for node in walk_json(payload) if node.pointer == pointer), None
        )
        selected = str(row.value or "")
        token = str(source or "")
        if not token or token not in selected:
            return "restore_market_locale"
        templates.add(selected.replace(token, "{value}", 1))
    return (
        f"value_url_template:{templates.pop()}"
        if len(templates) == 1
        else "restore_market_locale"
    )


def _repeated_relative_path(
    rows: list[Evidence],
    root: RecipeBinding,
    *,
    request: ExtractionRequest | None,
    field: str,
) -> str:
    first = rows[0]
    if first.locator.kind == "json_pointer" and root.source in {
        "json_pointer",
        "network_json_pointer",
    }:
        absolute = _pointer_pattern(
            [
                _grounded_structured_pointer(request, row, field)[1]
                if request is not None
                else _structured_pointer(row)[1]
                for row in rows
            ]
        )
        path = _relative_pointer(root.path, absolute)
    elif first.locator.kind == "dom_path" and root.source == "dom_text":
        absolute = _dom_pattern([row.locator.value for row in rows])
        path = _relative_css(root.path, absolute)
    elif first.locator.kind == "css_selector" and root.source == "dom_text":
        matches = [_CARD_LOCATOR.fullmatch(row.locator.value) for row in rows]
        semantic_fields = {match.group(2) for match in matches if match is not None}
        if len(semantic_fields) != 1:
            return ""
        semantic_field = semantic_fields.pop()
        path = "a[href]" if semantic_field in {"title", "url"} else ""
    else:
        return ""
    return path


def _structured_pointer(row: Evidence) -> tuple[str, str]:
    parts = row.locator.value.strip("/").split("/")
    if parts and parts[0].startswith("jsonld:"):
        return parts[0], "/" + "/".join(parts[1:])
    return row.artifact_id, row.locator.value


def _grounded_structured_pointer(
    request: ExtractionRequest, row: Evidence, field: str
) -> tuple[str, str]:
    artifact, semantic_path = _structured_pointer(row)
    virtual_row = row.model_copy(
        update={
            "artifact_id": artifact,
            "locator": row.locator.model_copy(update={"value": semantic_path}),
        }
    )
    return artifact, _grounded_json_path(request, virtual_row, field) or semantic_path


def _grounded_repeated_dom_binding(
    request: ExtractionRequest | None,
    rows: list[Evidence],
    root: RecipeBinding,
    field: str,
) -> tuple[str, str | None] | None:
    if request is None or not root.artifact:
        return None
    document = request.artifact_reader.document_store.html(root.artifact)
    roots = document.css(root.path)
    if len(roots) != len(rows):
        return None
    relative_paths: list[str] = []
    attributes: list[str | None] = []
    for node, row in zip(roots, rows, strict=True):
        match = _matching_descendant(request, node, row, field)
        if match is None:
            return None
        matched_node, attribute = match
        root_path = node.dom_path().rstrip("/")
        path = matched_node.dom_path()
        if not path.startswith(root_path + "/"):
            return None
        relative_paths.append(path[len(root_path) :])
        attributes.append(attribute)
    if len(set(attributes)) != 1:
        return None
    path = _dom_pattern(relative_paths)
    return (path, attributes[0]) if path else None


def _matching_descendant(request, root, row: Evidence, field: str):
    target = _comparable_value(request, field, row.value)
    if field in {"url", "image_url"}:
        attribute = _attribute(field)
        selector = "a[href]" if field == "url" else "img[src]"
        node = next(
            (
                node
                for node in root.css(selector)
                if _comparable_value(request, field, node.attribute(attribute))
                == target
            ),
            None,
        )
        if node is None and field == "url":
            raw_target = _comparable_value(
                request,
                field,
                row.metadata.get("recipe_source_value", row.raw_value),
            )
            node = next(
                (
                    candidate
                    for candidate in root.css(selector)
                    if _comparable_value(request, field, candidate.attribute(attribute))
                    == raw_target
                ),
                None,
            )
        return (node, attribute) if node is not None else None
    candidates = [
        node
        for node in root.css("*")
        if _comparable_value(request, field, node.content_text()) == target
    ]
    if candidates:
        node = max(candidates, key=lambda item: item.dom_path().count("/"))
        return node, None
    for attribute in ("title", "alt", "aria-label", "data-price"):
        node = next(
            (
                item
                for item in root.css(f"[{attribute}]")
                if _comparable_value(request, field, item.attribute(attribute))
                == target
            ),
            None,
        )
        if node is not None:
            return node, attribute
    return None


def _repeated_source(first: Evidence, root: RecipeBinding, field: str):
    if root.source == "dom_text" and field in {"url", "image_url"}:
        return "dom_attribute"
    return _source(first) or "dom_text"
