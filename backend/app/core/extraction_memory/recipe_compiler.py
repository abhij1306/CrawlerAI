"""LEARN-ONCE recipe compiler: one model call over a page flat map.

Main-owned (the archive branch's compiler is rejected). This module turns a
single ``ExtractionRequest`` capture bundle into an executable
``ExtractionRecipe`` using exactly ONE model call over the scoped flat map. The
model proposes flat-map PATHS only — never field values — and the compiler
grounds every proposed binding against the real page before accepting it:

* Text fields must resolve to a flat-map path that actually exists on the page.
* Attribute fields (url / image_url) are located structurally inside the
  record root (an ``<a href>`` / ``<img src>``), never taken from the model.
* The whole candidate recipe is finally validated by running the pure
  ``execute_recipe`` interpreter; if the required title/url/record-root bindings
  do not re-ground to real values, NO recipe is returned (honest no-recipe).

Invariants (enforced by ``test_extraction_architecture`` + ``test_recipe_compiler``):
this module reads only the capture bundle / flat map and never imports the
publication/records output, persistence, or ORM models. It emits a frozen
``ExtractionRecipe``; a separate async persistence seam stores it.
"""

from __future__ import annotations

import json
import re
from string import Template
from typing import Any, Awaitable, Callable

from app.core.config.cascade import (
    CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS,
    CASCADE_RECIPE_COMPILER_MAX_FLAT_MAP_ENTRIES,
    CASCADE_RECIPE_COMPILER_SYSTEM_PROMPT,
    CASCADE_RECIPE_COMPILER_USER_TEMPLATE,
)
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    ExtractionRecipe,
    RecipeBinding,
    RecipeCandidate,
    RecipeScope,
)
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.core.extraction_memory.templates import normalize_route
from app.core.domain_utils import normalize_domain
from app.core.shared.ids import stable_id
from app.extraction.contracts import ExtractionRequest
from app.extraction.documents import HtmlDocument
from app.extraction.representation.flat_map import build_flat_map, build_scoped_flat_map
from app.extraction.surfaces import ListingSchema, Surface, SurfaceSpec

# An injectable async model client: given system + user prompts, returns the raw
# model text. Kept as a bare callable so tests can pass a deterministic stub and
# the seam can wire the real ``connectors.llm.provider_client`` adapter.
RecipeModelClient = Callable[[str, str], Awaitable[str]]

# Record field names whose value lives in a DOM attribute rather than node text.
_ATTRIBUTE_FIELDS: dict[str, str] = {
    "url": "href",
    "apply_url": "href",
    "image_url": "src",
}
_URL_FIELDS: tuple[str, ...] = ("url", "apply_url")
# Text fields that carry a dedicated transform so re-read values are canonical.
_FIELD_TRANSFORMS: dict[str, str] = {
    "price": "dom_price",
    "currency": "dom_currency",
}


async def compile_recipe(
    request: ExtractionRequest,
    *,
    surface_spec: SurfaceSpec,
    listing_schema: ListingSchema | None,
    model_client: RecipeModelClient,
) -> DiscoveryResult:
    """Learn one recipe from the capture bundle via a single model call.

    Returns a ``DiscoveryResult`` carrying either a grounded ``RecipeCandidate``
    or a typed failure code. The compiler never persists anything.
    """

    document = _primary_document(request)
    if document is None:
        return _failure("recipe_root_not_found", "no html artifact to learn from")
    fields = _requested_field_names(request, surface_spec, listing_schema)
    scoped = build_scoped_flat_map(document)
    flat_map = build_flat_map(document)
    prompt = _render_user_prompt(request.surface, fields, scoped.flat_map)
    raw = await model_client(CASCADE_RECIPE_COMPILER_SYSTEM_PROMPT, prompt)
    proposal = _parse_proposal(raw)
    if proposal is None:
        return _failure("recipe_binding_not_found", "model returned no usable JSON")
    record_root_path, field_paths = proposal
    is_listing = listing_schema is not None
    recipe = _build_recipe(
        request,
        record_root_path=record_root_path,
        field_paths=field_paths,
        flat_map_paths=tuple(flat_map.keys()),
        document=document,
        is_listing=is_listing,
    )
    if recipe is None:
        return _failure("recipe_required_field_missing", "required bindings ungrounded")
    # Ultimate grounding gate: re-read every binding from the page. Values are
    # never taken from the model; if the required fields do not re-ground, the
    # recipe is discarded (honest no-recipe).
    execution = execute_recipe(request, recipe)
    if execution.failure_code is not None or not execution.records:
        return _failure(
            execution.failure_code or "recipe_binding_not_found",
            execution.detail or "recipe did not re-ground on the page",
        )
    grounded_paths = tuple(
        dict.fromkeys(
            binding.path
            for binding in _all_bindings(recipe)
            if binding.path not in {"", "."}
        )
    )
    return DiscoveryResult(
        candidate=RecipeCandidate(
            candidate_id=stable_id(
                "learn-once-recipe",
                request.capture.bundle_id,
                request.surface.value,
            ),
            recipe=recipe,
            origin="model_assisted",
            sample_urls=(request.capture.final_url or request.capture.requested_url,),
            grounded_paths=grounded_paths,
        )
    )


def _failure(code: str, detail: str) -> DiscoveryResult:
    return DiscoveryResult(failure_code=code, detail=detail)  # type: ignore[arg-type]


def _primary_document(request: ExtractionRequest) -> HtmlDocument | None:
    html_artifacts = sorted(
        (
            artifact
            for artifact in request.capture.artifacts
            if artifact.artifact_type in {"rendered_html", "http_html"}
        ),
        key=lambda artifact: artifact.artifact_type != "rendered_html",
    )
    for artifact in html_artifacts:
        if request.artifact_reader.exists(artifact.artifact_id):
            return request.artifact_reader.document_store.html(artifact.artifact_id)
    return None


def _requested_field_names(
    request: ExtractionRequest,
    surface_spec: SurfaceSpec,
    listing_schema: ListingSchema | None,
) -> tuple[str, ...]:
    descriptors = CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS.get(
        surface_spec.domain, {}
    )
    # Keep the prompted required identity consistent with _identity_field, which
    # keys on is_listing: a listing record is always identified by its own
    # ``url`` (apply_url is a normal field there). A detail surface may use
    # either, so prompt for both and let _identity_field pick post-grounding.
    is_listing = listing_schema is not None
    required = ["title", "url"]
    if not is_listing and "apply_url" in descriptors:
        required.append("apply_url")
    requested = [
        "image_url" if field == "image" else str(field)
        for field in request.requested_fields
    ]
    ordered: list[str] = []
    for field in (*required, *requested):
        if field in descriptors and field not in ordered:
            ordered.append(field)
    return tuple(ordered)


def _render_user_prompt(
    surface: Surface, fields: tuple[str, ...], flat_map
) -> str:
    domain = "jobs" if surface.value.startswith("job") else "commerce"
    descriptors = CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS.get(domain, {})
    field_lines = "\n".join(
        f"- {field}: {descriptors.get(field, field)}" for field in fields
    )
    entries = list(flat_map.items())[:CASCADE_RECIPE_COMPILER_MAX_FLAT_MAP_ENTRIES]
    flat_lines = "\n".join(f"{path} => {text}" for path, text in entries)
    return Template(CASCADE_RECIPE_COMPILER_USER_TEMPLATE).safe_substitute(
        surface=surface.value,
        fields=field_lines,
        flat_map=flat_lines,
    )


def _parse_proposal(
    raw: str,
) -> tuple[str, dict[str, str]] | None:
    payload = _load_json_object(raw)
    if payload is None:
        return None
    fields_obj = payload.get("fields")
    if not isinstance(fields_obj, dict):
        return None
    field_paths = {
        str(field): str(path)
        for field, path in fields_obj.items()
        if isinstance(path, str) and path.strip()
    }
    record_root = str(payload.get("record_root") or "").strip()
    return record_root, field_paths


def _load_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            return None
        try:
            value = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def _build_recipe(
    request: ExtractionRequest,
    *,
    record_root_path: str,
    field_paths: dict[str, str],
    flat_map_paths: tuple[str, ...],
    document: HtmlDocument,
    is_listing: bool,
) -> ExtractionRecipe | None:
    identity_field = _identity_field(field_paths, is_listing=is_listing)
    root_css, root_cardinality = _record_root_css(
        record_root_path, field_paths, is_listing=is_listing
    )
    if root_css is None:
        return None
    root_binding = RecipeBinding(
        binding_id="record.root",
        source="dom_text",
        path=root_css,
        cardinality=root_cardinality,
        required=True,
    )
    fields: dict[str, tuple[RecipeBinding, ...]] = {}
    for field, path in field_paths.items():
        binding = _field_binding(
            field,
            path,
            root_css=root_css,
            flat_map_paths=flat_map_paths,
            document=document,
        )
        if binding is not None:
            fields[field] = (binding,)
    # Attribute-only identity/image fields never appear in the flat map, so they
    # are located structurally inside the record root.
    for field in (identity_field, "image_url"):
        if field in fields or field not in _ATTRIBUTE_FIELDS:
            continue
        binding = _structural_attribute_binding(field, root_css, document)
        if binding is not None:
            fields[field] = (binding,)
    if "title" not in fields or identity_field not in fields:
        return None
    required = ("record.identity", "title", identity_field)
    return ExtractionRecipe(
        recipe_id=stable_id(
            "learn-once-recipe",
            request.capture.bundle_id,
            request.surface.value,
        ),
        scope=RecipeScope(
            domain=normalize_domain(
                request.capture.final_url or request.capture.requested_url
            ),
            surface=request.surface.value,  # type: ignore[arg-type]
            route_pattern=normalize_route(
                request.capture.final_url or request.capture.requested_url,
                request.surface.value,
            )
            or "/",
        ),
        capture_requirements=("rendered_dom",),
        record_root=root_binding,
        identity=(
            fields[identity_field][0].model_copy(
                update={
                    "binding_id": "record.identity.url",
                    "field": identity_field,
                    "required": True,
                }
            ),
        ),
        fields=fields,
        required=tuple(name for name in required if name),
    )


def _identity_field(field_paths: dict[str, str], *, is_listing: bool) -> str:
    # Listing records are identified by their own ``url`` (the card's canonical
    # link); ``apply_url`` there is a normal non-identity field. Only a detail
    # surface with no ``url`` may fall back to ``apply_url`` as its identity.
    if is_listing:
        return "url"
    if "url" not in field_paths and "apply_url" in field_paths:
        return "apply_url"
    return "url"


def _record_root_css(
    record_root_path: str,
    field_paths: dict[str, str],
    *,
    is_listing: bool,
) -> tuple[str | None, str]:
    if not is_listing:
        # Single-record surfaces bind fields to the document; the record root is
        # a stable structural anchor (``body``) resolving to exactly one node.
        return "body", "one"
    root = record_root_path.strip()
    if not root or "/" not in root:
        root = _common_ancestor(tuple(field_paths.values()))
    if not root:
        return None, "many"
    css = _repeated_root_css(root)
    return (css or None), "many"


def _repeated_root_css(path: str) -> str:
    segments = [seg for seg in path.strip("/").split("/") if seg]
    if not segments:
        return ""
    parts: list[str] = []
    for index, segment in enumerate(segments):
        tag, _, idx = segment.partition("[")
        idx = idx.rstrip("]")
        # Drop the positional index on the repeated (leaf) element so the root
        # selector matches every sibling card, not just the sample the model saw.
        if index == len(segments) - 1 or not idx:
            parts.append(tag)
        else:
            parts.append(f"{tag}:nth-of-type({idx})")
    return " > ".join(parts)


def _relative_css(root_path: str, absolute_path: str) -> str | None:
    root_segments = [seg for seg in root_path.strip("/").split("/") if seg]
    abs_segments = [seg for seg in absolute_path.strip("/").split("/") if seg]
    if len(abs_segments) <= len(root_segments):
        return None
    if abs_segments[: len(root_segments)] != root_segments:
        # Fall back to matching by tag chain when the sample index differs.
        pass
    tail = abs_segments[len(root_segments):]
    parts: list[str] = []
    for segment in tail:
        tag, _, idx = segment.partition("[")
        idx = idx.rstrip("]")
        parts.append(f"{tag}:nth-of-type({idx})" if idx else tag)
    return " > ".join(parts) if parts else None


def _common_ancestor(paths: tuple[str, ...]) -> str:
    split = [
        [seg for seg in path.strip("/").split("/") if seg]
        for path in paths
        if path.strip("/")
    ]
    if not split:
        return ""
    common: list[str] = []
    for column in zip(*split):
        if len(set(column)) == 1:
            common.append(column[0])
        else:
            break
    return "/" + "/".join(common) if common else ""


def _absolute_css(path: str) -> str:
    segments = [seg for seg in path.strip("/").split("/") if seg]
    parts: list[str] = []
    for segment in segments:
        tag, _, idx = segment.partition("[")
        idx = idx.rstrip("]")
        parts.append(f"{tag}:nth-of-type({idx})" if idx else tag)
    return " > ".join(parts)


def _field_binding(
    field: str,
    path: str,
    *,
    root_css: str,
    flat_map_paths: tuple[str, ...],
    document: HtmlDocument,
) -> RecipeBinding | None:
    if field in _ATTRIBUTE_FIELDS:
        # Attribute values are not in the flat-map text, but the model still
        # grounded the exact node (e.g. url -> li/a[1], apply_url -> li/a[2]).
        # Anchor to that node so sibling anchors/images do not collapse onto the
        # same field; fall back to a structural selector only when the grounded
        # path does not resolve.
        return _attribute_binding(field, path, root_css=root_css, document=document)
    if path not in flat_map_paths:
        return None
    listing = root_css != "body"
    css = _relative_css(_root_absolute(root_css), path) if listing else _absolute_css(path)
    if not css:
        return None
    if listing and not _resolves_under_root(document, root_css, css):
        return None
    if not listing and not document.safe_css(css):
        return None
    return RecipeBinding(
        binding_id=f"field.{field}",
        source="dom_text",
        path=css,
        scope="record.root" if listing else "document",
        field=field,
        transform=_FIELD_TRANSFORMS.get(field),
    )


def _attribute_binding(
    field: str, path: str, *, root_css: str, document: HtmlDocument
) -> RecipeBinding | None:
    attribute = _ATTRIBUTE_FIELDS[field]
    listing = root_css != "body"
    css = (
        _relative_css(_root_absolute(root_css), path)
        if listing
        else _absolute_css(path)
    )
    if css and _attribute_node_resolves(document, root_css, css, attribute, listing):
        return RecipeBinding(
            binding_id=f"field.{field}",
            source="dom_attribute",
            # Anchoring to the exact grounded node makes the value scalar: a
            # single node carries a single attribute, so a sibling <a>/<img> in
            # the same record can never fold into this field.
            path=css,
            scope="record.root" if listing else "document",
            attribute=attribute,
            cardinality="zero_or_one",
            field=field,
        )
    # The grounded path did not resolve to a node carrying the attribute; fall
    # back to the structural selector (best-effort, may be broad).
    return _structural_attribute_binding(field, root_css, document)


def _attribute_node_resolves(
    document: HtmlDocument,
    root_css: str,
    css: str,
    attribute: str,
    listing: bool,
) -> bool:
    if listing:
        nodes = [
            node
            for root in document.safe_css(root_css)
            for node in root.safe_css(css)
        ]
    else:
        nodes = list(document.safe_css(css))
    return any(node.attribute(attribute) is not None for node in nodes)


def _root_absolute(root_css: str) -> str:
    # Reconstruct an absolute-path prefix from the generalized root CSS so field
    # paths can be made relative. Uses index 1 for the un-indexed leaf.
    parts: list[str] = []
    for chunk in root_css.split(" > "):
        match = re.match(r"([a-z0-9]+)(?::nth-of-type\((\d+)\))?", chunk)
        if match is None:
            return ""
        tag, idx = match.group(1), match.group(2) or "1"
        parts.append(f"{tag}[{idx}]")
    return "/" + "/".join(parts)


def _resolves_under_root(document: HtmlDocument, root_css: str, css: str) -> bool:
    for root in document.safe_css(root_css):
        if root.safe_css(css):
            return True
    return False


def _structural_attribute_binding(
    field: str, root_css: str, document: HtmlDocument
) -> RecipeBinding | None:
    attribute = _ATTRIBUTE_FIELDS[field]
    tag = "img" if attribute == "src" else "a"
    selector = f"{tag}[{attribute}]"
    listing = root_css != "body"
    if listing:
        found = _resolves_under_root(document, root_css, selector)
    else:
        found = bool(document.safe_css(selector))
    if not found:
        return None
    return RecipeBinding(
        binding_id=f"field.{field}",
        source="dom_attribute",
        path=selector,
        scope="record.root" if listing else "document",
        attribute=attribute,
        field=field,
    )


def _all_bindings(recipe: ExtractionRecipe):
    yield recipe.record_root
    for binding in recipe.identity:
        yield binding
    for bindings in recipe.fields.values():
        for binding in bindings:
            yield binding
