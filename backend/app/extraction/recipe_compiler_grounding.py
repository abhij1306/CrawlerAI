"""Grounding primitives for executable extraction recipes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.domain_utils import normalize_domain
from app.core.config.extraction_rules import DETAIL_IMAGE_SRCSET_ATTRS
from app.core.config.locale_format_rules import locale_hint_from_page_url, parse_money
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
from app.core.shared.field_coerce_price import extract_currency_code
from app.core.shared.text_coerce import clean_text, strip_html_tags
from app.core.shared.url_utils import largest_srcset_url, public_asset_delivery_url
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
    path = row.locator.value
    artifact_id = row.artifact_id
    transform = "canonical"
    binding_scope = scope if source.startswith("dom_") else "document"
    attribute = _attribute(field) if source == "dom_attribute" else None
    if row.locator.kind in {"dom_path", "css_selector"} and request:
        grounded_dom = _ground_detail_dom(request, row, field)
        if grounded_dom is None:
            return None
        path, attribute, artifact_id, transform = grounded_dom
        source = "dom_attribute" if attribute else "dom_text"
        binding_scope = "document"
    elif (
        row.locator.kind
        in {
            "json_pointer",
            "network_json_pointer",
            "script_path",
        }
        and request
    ):
        grounded_path = _grounded_json_path(request, row, field)
        if grounded_path is None:
            transformed = _grounded_json_transform(request, row, field)
            if transformed is None:
                return None
            grounded_path, transform = transformed
        else:
            transform = (
                _grounded_value_transform(request, row, field, grounded_path)
                or _selected_representation_transform(row)
                or transform
            )
        path = grounded_path
    elif source == "url_component" and path == "url":
        path = "final_url"
    if source == "url_component" and field == "title":
        transform = "semantic_url_title"
    if source == "url_component" and field == "sku" and request:
        selected = str(row.value or "")
        source_url = request.capture.final_url
        start = source_url.casefold().find(selected.casefold())
        if selected and start >= 0:
            transform = (
                f"selected_slice_upper:{start}:{len(selected)}"
                if selected.isupper()
                else f"selected_slice:{start}:{len(selected)}"
            )
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
    expected = " ".join(str(entry.value or "").split()).casefold()
    row = next(
        (
            candidate
            for candidate in rows
            if " ".join(str(candidate.value or "").split()).casefold() == expected
        ),
        rows[0] if rows else None,
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
    source_value = row.metadata.get("recipe_source_value", row.value)
    target = _comparable_value(request, field, source_value)
    candidates = [
        node.pointer
        for node in walk_json(payload)
        if not isinstance(node.value, (dict, list))
        and _comparable_value(request, field, node.value) == target
    ]
    if not candidates:
        if field in {"url", "apply_url"}:
            selected_url = str(row.value or "")
            candidates = [
                node.pointer
                for node in walk_json(payload)
                if not isinstance(node.value, (dict, list))
                and len(str(node.value or "")) >= 4
                and str(node.value) in selected_url
            ]
            if candidates:
                hint_parts = row.locator.value.casefold().strip("/").split("/")
                return max(
                    candidates,
                    key=lambda path: sum(
                        left == right
                        for left, right in zip(
                            hint_parts,
                            path.casefold().strip("/").split("/"),
                            strict=False,
                        )
                    ),
                )
        if field != "color":
            return None
        candidates = [
            node.pointer
            for node in walk_json(payload)
            if isinstance(node.value, str)
            and _query_value(node.value, "shade") == target
        ]
        if not candidates:
            return None
    hint_parts = row.locator.value.casefold().strip("/").split("/")
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
    if field == "location":
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
    for node in walk_json(payload):
        if not isinstance(node.value, str):
            continue
        if node.value.strip("'\"").casefold() == target:
            selected = str(row.value).strip()
            return node.pointer, (
                "casefold"
                if selected == selected.casefold()
                and node.value.strip("'\"") != selected
                else "strip_quotes"
            )
        transform = _derived_text_transform(node.value, target)
        if transform:
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


def _ground_detail_dom(
    request: ExtractionRequest, row: Evidence, field: str
) -> tuple[str, str | None, str, str] | None:
    artifact_id = row.artifact_id
    known_artifacts = {item.artifact_id for item in request.capture.artifacts}
    if artifact_id not in known_artifacts:
        artifact_id = ""
    try:
        if not artifact_id:
            raise KeyError(row.artifact_id)
        document = request.artifact_reader.document_store.html(artifact_id)
    except (KeyError, ValueError):
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
        document = request.artifact_reader.document_store.html(artifact_id)
    target = _comparable_value(request, field, row.value)
    located = (
        document.css_first(row.locator.value)
        if row.locator.kind == "css_selector"
        else next(
            (
                node
                for node in document.css("*")
                if node.dom_path() == row.locator.value
            ),
            None,
        )
    )
    if located is not None:
        text = located.content_text()
        if (
            field in {"price", "original_price"}
            and (
                parsed := parse_money(
                    text,
                    locale_hint=locale_hint_from_page_url(request.capture.final_url),
                )
            )
            is not None
            and _comparable_value(request, field, parsed) == target
        ):
            return _dom_path_to_css(located.dom_path()), None, artifact_id, "dom_price"
        if (
            field == "currency"
            and (currency := extract_currency_code(text))
            and _comparable_value(request, field, currency) == target
        ):
            return (
                _dom_path_to_css(located.dom_path()),
                None,
                artifact_id,
                "dom_currency",
            )
        if _comparable_value(request, field, text) == target:
            return _dom_path_to_css(located.dom_path()), None, artifact_id, "canonical"
    for item in document.css("*"):
        for attribute, raw_value in item.attributes().items():
            if field == "color" and attribute in {"href", "value", "data-url"}:
                query = parse_qs(
                    urlsplit(urljoin(request.capture.final_url, raw_value)).query
                )
                name = next(
                    (
                        key
                        for key, values in query.items()
                        if values
                        and _comparable_value(request, field, values[0]) == target
                    ),
                    None,
                )
                if name:
                    return (
                        _dom_path_to_css(item.dom_path()),
                        attribute,
                        artifact_id,
                        f"query_param:{name}",
                    )
            if field == "availability" and attribute == "data-json":
                try:
                    state = json.loads(raw_value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                selectable = (
                    state.get("selectable") if isinstance(state, dict) else None
                )
                normalized = (
                    "out_of_stock"
                    if selectable in {False, 0, "0", "false", "False"}
                    else "in_stock"
                    if selectable in {True, 1, "1", "true", "True"}
                    else None
                )
                if _comparable_value(request, field, normalized) == target:
                    return (
                        _dom_path_to_css(item.dom_path()),
                        attribute,
                        artifact_id,
                        "attribute_json_availability",
                    )
    for attribute in ("content", "title", "alt", "href", "src", "data-brand"):
        node = next(
            (
                item
                for item in document.css(f"[{attribute}]")
                if _comparable_value(request, field, item.attribute(attribute))
                == target
            ),
            None,
        )
        if node is not None:
            return (
                _dom_path_to_css(node.dom_path()),
                attribute,
                artifact_id,
                "canonical",
            )
        transformed_node = next(
            (
                (item, transform)
                for item in document.css(f"[{attribute}]")
                if (
                    transform := _derived_text_transform(
                        item.attribute(attribute) or "", target
                    )
                )
            ),
            None,
        )
        if transformed_node is not None:
            item, transform = transformed_node
            return _dom_path_to_css(item.dom_path()), attribute, artifact_id, transform
    for item in document.css("*"):
        for attribute, value in item.attributes().items():
            transform = "canonical"
            if attribute in DETAIL_IMAGE_SRCSET_ATTRS:
                value = largest_srcset_url(value)
                transform = "largest_srcset"
            if _comparable_value(request, field, value) == target:
                return (
                    _dom_path_to_css(item.dom_path()),
                    attribute,
                    artifact_id,
                    transform,
                )
    candidates = [
        node
        for node in document.css("body *")
        if _comparable_value(request, field, node.content_text()) == target
    ]
    if candidates:
        node = max(candidates, key=lambda item: item.dom_path().count("/"))
        return _dom_path_to_css(node.dom_path()), None, artifact_id, "canonical"
    for node in document.css("body *"):
        derived_transform = _derived_text_transform(node.content_text(), target)
        if derived_transform:
            return (
                _dom_path_to_css(node.dom_path()),
                None,
                artifact_id,
                derived_transform,
            )
    return None


def _derived_text_transform(value: str, target: str) -> str | None:
    text = " ".join(value.split())
    if ":" in text and text.partition(":")[2].strip().casefold() == target:
        return "after_colon"
    registered = re.match(r"^(.+?®)(?:\s|$)", text)
    if registered and registered.group(1).casefold() == target:
        return "registered_prefix"
    first = text.split(" ", 1)[0].strip("'\"") if text else ""
    if first.casefold() == target:
        return "first_token"
    stripped = re.sub(r"^[^A-Za-z0-9]+", "", text).strip()
    if stripped.casefold() == target:
        return "strip_leading_symbols"
    start = text.casefold().find(target)
    if target and start >= 0:
        return f"substring:{start}:{len(target)}"
    last = text.rsplit(" ", 1)[-1].strip("'\"") if text else ""
    if last.casefold() == target:
        return "last_token"
    target_words = target.split()
    source_words = text.casefold().split()
    if target_words and source_words[: len(target_words)] == target_words:
        return f"prefix_words:{len(target_words)}"
    if text.rsplit("/", 1)[-1].casefold() == target:
        return "path_leaf_title"
    return None


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


def _dom_pattern(paths: list[str]) -> str:
    parts = [
        [part for part in path.strip("/").split("/") if not part.startswith("#")]
        for path in paths
    ]
    if len({len(path) for path in parts}) != 1:
        return ""
    result: list[str] = []
    for values in zip(*parts, strict=True):
        tags = [value.split("[", 1)[0] for value in values]
        if len(set(tags)) != 1:
            return ""
        indexes = [value.removeprefix(tags[0]).strip("[]") for value in values]
        result.append(
            tags[0] if len(set(indexes)) > 1 else f"{tags[0]}:nth-of-type({indexes[0]})"
        )
    return " > ".join(result)


def _dom_path_to_css(path: str) -> str:
    return _dom_pattern([path])


def _relative_css(root: str, absolute: str) -> str:
    return absolute.removeprefix(root).removeprefix(" > ") or "."


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
