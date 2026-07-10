"""Generalized exemplar-record listing tier + per-domain recipe cache.

The fall-through path for listing pages the Tier 0 structured floor could not
hold (no JSON-LD / microdata joining every record). It realises the plan's
acquire-once / replay-cheap contract for listings:

- **Acquire (one LLM call per newly-seen page).** ``listing_records`` already
  discovered the boundaries (site-independent structural repetition). We
  flat-map exactly **one** exemplar record (§163 — "the LLM sees 1 record, not
  900") and ask only *which relative path holds the title / price*. The model
  chooses bindings; it never supplies values.
- **Apply across all N deterministically.** Each binding is a record-root
  relative DOM path; for every record we read the **DOM text** at that path, so
  the value always traces to the page (grounding gate §167). The detail URL
  comes from discovery, already grounded.
- **Compile a recipe; replay with zero LLM.** Bindings compile to a per-
  ``(surface, domain, route)`` recipe replayed deterministically on later runs.
  Replay re-grounds every run; if the markup drifted so bindings no longer
  resolve, the recipe is abandoned and the page is re-acquired.

Returns a ``ModelFallbackResult`` — identical to ``run_model_fallback`` — so the
engine's metrics, evidence merge, and ML-tier handling are unchanged. Recipe
**persistence** is a follow-up: this ships the mechanism plus an in-process
store; the engine passes ``None`` today (acquires each run, no regression).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Protocol

from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    Evidence,
    EntityHint,
    ExtractionRequest,
    SourceLocator,
)
from app.extraction.documents import HtmlDocument
from app.extraction.listing_records import RecordBoundary, discover_listing_records
from app.extraction.model_runtime import (
    ModelFallbackResult,
    RuntimeCompactSource,
    RuntimeFlatMapEntry,
    RuntimeFlatMapPage,
    RuntimeModelAdapter,
    _approved_artifact,
    _html_source,
    _input_token_budget,
    _market_tags,
    _predict_with_timeout,
    _result_identity_error,
    _runtime_budget_ms,
    _runtime_cost_cap_usd,
    run_model_fallback,
)
from app.extraction.representation.flat_map import (
    FlatMap,
    build_flat_map,
    flat_map_token_count,
)
from app.extraction.surfaces import ListingSchema, listing_schema

_GENERALIZED_CONFIDENCE = 0.85
_PREVIEW_CHARS = 120


@dataclass(frozen=True)
class ListingBinding:
    """A field bound to a record-root-relative flat-map path (e.g. ``/a[1]``)."""

    fact_type: str
    relative_path: str


@dataclass(frozen=True)
class ListingRecipe:
    """Compiled per-route bindings replayed deterministically on later runs."""

    route_key: str
    adapter_id: str
    artifact_version: str
    bindings: tuple[ListingBinding, ...]


class ListingRecipeStore(Protocol):
    def get(self, route_key: str) -> ListingRecipe | None: ...

    def put(self, recipe: ListingRecipe) -> None: ...


class InMemoryListingRecipeStore:
    """Process-local recipe cache. Production persistence is a follow-up."""

    def __init__(self) -> None:
        self._recipes: dict[str, ListingRecipe] = {}

    def get(self, route_key: str) -> ListingRecipe | None:
        return self._recipes.get(route_key)

    def put(self, recipe: ListingRecipe) -> None:
        self._recipes[recipe.route_key] = recipe


class SnapshotListingRecipeStore:
    """Read-only recipe replay store materialized from a frozen release."""

    def __init__(self, recipes: Mapping[str, ListingRecipe]) -> None:
        self._recipes = dict(recipes)

    def get(self, route_key: str) -> ListingRecipe | None:
        return self._recipes.get(route_key)

    def put(self, recipe: ListingRecipe) -> None:
        # The pipeline persists an acquired candidate only after the result is
        # validated.  Keep this thread-local view usable for the current call.
        self._recipes[recipe.route_key] = recipe


def recipe_store_from_snapshot(request: ExtractionRequest) -> ListingRecipeStore:
    """Expose matching, immutable record bindings from the release snapshot."""
    page_url = request.capture.final_url or request.capture.requested_url
    route_key = _route_key(request, page_url)
    route = normalize_route(page_url, request.surface.value)
    recipes: dict[str, ListingRecipe] = {}
    for row in request.runtime_snapshot.get("templates", ()):
        if not isinstance(row, Mapping):
            continue
        if (
            row.get("surface") != request.surface.value
            or row.get("route_pattern") != route
        ):
            continue
        compiled = row.get("compiled_recipe")
        candidate = (
            compiled.get("record_bindings") if isinstance(compiled, Mapping) else None
        )
        recipe = _recipe_from_payload(route_key, candidate)
        if recipe is not None:
            recipes[route_key] = recipe
    return SnapshotListingRecipeStore(recipes)


def run_listing_generalized(
    request: ExtractionRequest,
    adapter: RuntimeModelAdapter | None,
    *,
    recipe_store: ListingRecipeStore | None = None,
) -> ModelFallbackResult:
    """Resolve a listing via replayed recipe, else a one-shot exemplar LLM pass."""
    artifact, disabled_reason = _approved_artifact(request)
    if artifact is None:
        return ModelFallbackResult(outcome="disabled", detail=disabled_reason)
    if adapter is None:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="model_service_failure",
            detail="approved model artifact has no runtime adapter",
        )
    if adapter.adapter_id != artifact.adapter_id:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="model_service_failure",
            detail="runtime adapter identity does not match approved artifact",
        )
    source = _html_source(request)
    if source is None:
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            failure_code="unsupported_representation",
            detail="no HTML artifact is available for the exemplar record",
        )
    artifact_id, html = source
    page_url = request.capture.final_url or request.capture.requested_url
    doc = HtmlDocument(artifact_id, html)
    schema = listing_schema(request.surface)
    if schema is None:
        return ModelFallbackResult(outcome="no_match", artifact=artifact)
    boundaries = discover_listing_records(doc, page_url=page_url)
    if not boundaries:
        # Structural discovery found no record spine (JS-rendered SPA, novel
        # markup, or a page whose only repeated links were category/nav tiles the
        # URL filter stripped). Do NOT give up — the exemplar tier needs a
        # boundary, but the whole-page generalized pass can still *find* records.
        # This is the decoupling: the LLM is no longer a slave to deterministic
        # discovery. Grounding still binds every published value to page DOM text.
        return run_model_fallback(request, adapter)
    route_key = _route_key(request, page_url)
    recipe = recipe_store.get(route_key) if recipe_store is not None else None
    if recipe is not None and _recipe_matches(recipe, artifact):
        replayed = _apply_bindings(
            doc, boundaries, recipe.bindings, artifact_id=artifact_id, schema=schema
        )
        if replayed:
            rows = _emit(request, artifact_id, replayed)
            return ModelFallbackResult(
                outcome="produced_evidence",
                evidence=rows,
                artifact=artifact,
                invoked=False,
            )
        # Markup drifted under the recipe — re-acquire with a fresh exemplar.

    return _acquire(
        request,
        adapter,
        artifact,
        doc=doc,
        boundaries=boundaries,
        schema=schema,
        artifact_id=artifact_id,
        html=html,
        page_url=page_url,
        route_key=route_key,
        recipe_store=recipe_store,
    )


def _acquire(
    request: ExtractionRequest,
    adapter: RuntimeModelAdapter,
    artifact,
    *,
    doc: HtmlDocument,
    boundaries: tuple[RecordBoundary, ...],
    schema: ListingSchema,
    artifact_id: str,
    html: str,
    page_url: str,
    route_key: str,
    recipe_store: ListingRecipeStore | None,
) -> ModelFallbackResult:
    exemplar = boundaries[0]
    exemplar_root = _flat_root(exemplar.node.dom_path())
    exemplar_map = build_flat_map(doc, root_path=exemplar.node.dom_path())
    if not exemplar_map:
        return ModelFallbackResult(
            outcome="no_match", artifact=artifact, representation_built=True
        )
    page = _exemplar_page(
        html=html,
        artifact_id=artifact_id,
        exemplar_map=exemplar_map,
        scope_path=exemplar_root,
        market_tags=_market_tags(request),
        surface=request.surface.value,
    )
    if page.token_count > _input_token_budget():
        return ModelFallbackResult(
            outcome="budget_limited",
            artifact=artifact,
            representation_built=True,
            failure_code="unsupported_representation",
            detail="exemplar flat map exceeded generalized input token budget",
        )

    started = perf_counter()
    try:
        result = _predict_with_timeout(adapter, page, artifact)
    except TimeoutError:
        return ModelFallbackResult(
            outcome="timed_out",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=(perf_counter() - started) * 1_000,
            failure_code="model_service_failure",
            detail="exemplar model invocation timed out",
        )
    except Exception as exc:  # degrade without breaking extraction
        return ModelFallbackResult(
            outcome="failed",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=(perf_counter() - started) * 1_000,
            failure_code="model_service_failure",
            detail=f"exemplar model invocation failed: {type(exc).__name__}",
        )
    elapsed_ms = (perf_counter() - started) * 1_000

    identity_error = _result_identity_error(result, artifact)
    over_budget = (
        elapsed_ms > _runtime_budget_ms(artifact)
        or result.memory_mb > artifact.max_memory_mb
        or result.cost_usd > _runtime_cost_cap_usd(artifact)
    )
    if identity_error or over_budget:
        return ModelFallbackResult(
            outcome="failed" if identity_error else "budget_limited",
            artifact=artifact,
            representation_built=True,
            invoked=True,
            latency_ms=elapsed_ms,
            memory_mb=result.memory_mb,
            cost_usd=result.cost_usd,
            prediction_count=len(result.predictions),
            failure_code="model_service_failure" if identity_error else None,
            detail=identity_error or "exemplar model runtime budget exceeded",
        )

    bindings = _bindings_from_predictions(
        result, exemplar_map, exemplar_root, artifact, schema=schema
    )
    grounded = (
        _apply_bindings(
            doc, boundaries, bindings, artifact_id=artifact_id, schema=schema
        )
        if bindings
        else []
    )
    if len(grounded) != len(boundaries):
        grounded = []
    if grounded and recipe_store is not None:
        recipe = ListingRecipe(
            route_key=route_key,
            adapter_id=artifact.adapter_id,
            artifact_version=artifact.artifact_version,
            bindings=bindings,
        )
        recipe_store.put(recipe)
    else:
        recipe = None
    rows = _emit(request, artifact_id, grounded)
    return ModelFallbackResult(
        outcome="produced_evidence" if rows else "no_match",
        evidence=rows,
        artifact=artifact,
        representation_built=True,
        invoked=True,
        latency_ms=elapsed_ms,
        memory_mb=result.memory_mb,
        cost_usd=result.cost_usd,
        prediction_count=len(result.predictions),
        ungrounded_rejection_count=max(0, len(boundaries) - len(grounded)),
        recipe_candidate=_recipe_payload(recipe) if recipe is not None else None,
    )


# --- binding acquisition + deterministic apply --------------------------------


@dataclass(frozen=True)
class _GroundedRecord:
    boundary: RecordBoundary
    values: dict[str, tuple[str, str]]


def _bindings_from_predictions(
    result,
    exemplar_map: FlatMap,
    exemplar_root: str,
    artifact,
    *,
    schema: ListingSchema,
) -> tuple[ListingBinding, ...]:
    """Keep the first groundable path per bound fact type as a relative binding.

    A prediction grounds only when its ``source_path`` is a real entry in the
    exemplar's flat map and lies inside the record root — the model chooses a
    location, never a value.
    """
    bindings: dict[str, ListingBinding] = {}
    for candidate in result.predictions:
        fact_type = candidate.fact_type
        if fact_type not in schema.bindable_facts or fact_type in bindings:
            continue
        if candidate.confidence < artifact.confidence_threshold:
            continue
        source_path = candidate.source_path
        if source_path not in exemplar_map:
            continue
        relative = _relative(source_path, exemplar_root)
        if relative is None:
            continue
        bindings[fact_type] = ListingBinding(
            fact_type=fact_type, relative_path=relative
        )
    return tuple(bindings[key] for key in schema.bindable_facts if key in bindings)


def _apply_bindings(
    doc: HtmlDocument,
    boundaries: tuple[RecordBoundary, ...],
    bindings: tuple[ListingBinding, ...],
    *,
    artifact_id: str,
    schema: ListingSchema,
) -> list[_GroundedRecord]:
    """Resolve each binding against every record's own flat map (grounding gate).

    A record is kept only when its title binding resolves to non-empty DOM text.
    The value is always read from the page — never from the model.
    """
    title_binding = _binding_for(schema.title_fact, bindings)
    if title_binding is None:
        return []
    grounded: list[_GroundedRecord] = []
    for boundary in boundaries:
        record_root = _flat_root(boundary.node.dom_path())
        record_map = build_flat_map(doc, root_path=boundary.node.dom_path())
        title, _ = _resolve_binding(title_binding, record_root, record_map)
        if not title:
            continue
        values = {
            binding.fact_type: _resolve_binding(binding, record_root, record_map)
            for binding in bindings
        }
        grounded.append(
            _GroundedRecord(
                boundary=boundary,
                values={
                    fact_type: value for fact_type, value in values.items() if value[0]
                },
            )
        )
    return grounded


def _resolve_binding(
    binding: ListingBinding | None, record_root: str, record_map: FlatMap
) -> tuple[str, str]:
    if binding is None:
        return "", ""
    path = record_root + binding.relative_path
    text = record_map.get(path, "")
    return (text, path) if text else ("", "")


def _binding_for(
    fact_type: str, bindings: tuple[ListingBinding, ...]
) -> ListingBinding | None:
    return next((b for b in bindings if b.fact_type == fact_type), None)


# --- evidence emission --------------------------------------------------------


def _emit(
    request: ExtractionRequest, artifact_id: str, grounded: list[_GroundedRecord]
) -> tuple[Evidence, ...]:
    schema = listing_schema(request.surface)
    if schema is None:
        return ()
    bundle = request.capture
    rows: list[Evidence] = []
    for record in grounded:
        subject_id = stable_id(
            "subject",
            bundle.bundle_id,
            artifact_id,
            schema.root_entity,
            record.boundary.index,
        )
        title, title_path = record.values[schema.title_fact]
        rows.append(
            _row(
                bundle.bundle_id,
                artifact_id,
                subject_id,
                schema.title_fact,
                title,
                title_path,
                schema.entity_type_for(schema.title_fact),
                surface=schema.surface,
                url=record.boundary.url,
                directness="inferred",
            )
        )
        rows.append(
            _row(
                bundle.bundle_id,
                artifact_id,
                subject_id,
                schema.url_fact,
                record.boundary.url,
                _flat_root(record.boundary.node.dom_path()),
                schema.entity_type_for(schema.url_fact),
                surface=schema.surface,
                url=record.boundary.url,
                directness="direct",
            )
        )
        for fact_type in schema.optional_text_facts:
            value = record.values.get(fact_type)
            if value is None:
                continue
            text, path = value
            rows.append(
                _row(
                    bundle.bundle_id,
                    artifact_id,
                    subject_id,
                    fact_type,
                    text,
                    path,
                    schema.entity_type_for(fact_type),
                    surface=schema.surface,
                    url=record.boundary.url,
                    directness="inferred",
                )
            )
    return tuple(rows)


def _row(
    bundle_id: str,
    artifact_id: str,
    subject_id: str,
    fact_type: str,
    value: str,
    path: str,
    entity_type: str,
    *,
    surface,
    url: str,
    directness: str,
) -> Evidence:
    return Evidence(
        evidence_id=stable_id(
            "ev", bundle_id, artifact_id, "listing_generalized", fact_type, subject_id
        ),
        bundle_id=bundle_id,
        artifact_id=artifact_id,
        collector_id="listing_generalized",
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(
            kind="dom_path", value=path, preview=str(value)[:_PREVIEW_CHARS]
        ),
        entity_hint=EntityHint(entity_type=entity_type, url=url),  # type: ignore[arg-type]
        group_id=subject_id,
        directness=directness,  # type: ignore[arg-type]
        confidence=_GENERALIZED_CONFIDENCE,
        flags=("model_prediction",),
        metadata={"extraction_method": "generalized"},
        surface=surface,
        subject_id=subject_id,
        subject_scope=entity_type,  # type: ignore[arg-type]
    )


# --- paths + recipe identity --------------------------------------------------


def _exemplar_page(
    *,
    html: str,
    artifact_id: str,
    exemplar_map: FlatMap,
    scope_path: str,
    market_tags: tuple[str, ...],
    surface: str,
) -> RuntimeFlatMapPage:
    return RuntimeFlatMapPage(
        source=RuntimeCompactSource(
            artifact_id=artifact_id,
            content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        ),
        entries=tuple(
            RuntimeFlatMapEntry(path=path, text=text)
            for path, text in exemplar_map.items()
        ),
        market_tags=market_tags,
        token_count=flat_map_token_count(exemplar_map),
        scope_path=scope_path,
        surface=surface,
    )


def _flat_root(dom_path: str) -> str:
    """``dom_path()`` → flat-map root: drop the ``/#document[1]`` pseudo-root."""
    segments = [
        segment
        for segment in dom_path.split("/")
        if segment and not segment.startswith("#document")
    ]
    return "/" + "/".join(segments)


def _relative(source_path: str, record_root: str) -> str | None:
    """The record-root-relative suffix of an absolute flat-map path, or ``None``.

    ``/html[1]/body[1]/li[1]/a[1]`` under root ``/html[1]/body[1]/li[1]`` becomes
    ``/a[1]``. Paths outside the record root are not bindable.
    """
    if not source_path.startswith(record_root + "/"):
        return None
    return source_path[len(record_root) :]


def _route_key(request: ExtractionRequest, page_url: str) -> str:
    surface = request.surface.value
    return (
        f"{surface}|{normalize_domain(page_url)}|{normalize_route(page_url, surface)}"
    )


def _recipe_matches(recipe: ListingRecipe, artifact) -> bool:
    return (
        recipe.adapter_id == artifact.adapter_id
        and recipe.artifact_version == artifact.artifact_version
        and bool(recipe.bindings)
    )


def _recipe_payload(recipe: ListingRecipe) -> dict[str, object]:
    return {
        "schema_version": "record_bindings.v1",
        "adapter_id": recipe.adapter_id,
        "artifact_version": recipe.artifact_version,
        "bindings": [
            {"fact_type": binding.fact_type, "relative_path": binding.relative_path}
            for binding in recipe.bindings
        ],
    }


def _recipe_from_payload(route_key: str, value: object) -> ListingRecipe | None:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "record_bindings.v1"
    ):
        return None
    bindings = tuple(
        ListingBinding(
            fact_type=str(row.get("fact_type") or ""),
            relative_path=str(row.get("relative_path") or ""),
        )
        for row in value.get("bindings", ())
        if isinstance(row, Mapping)
        and str(row.get("fact_type") or "")
        and str(row.get("relative_path") or "")
    )
    adapter_id = str(value.get("adapter_id") or "")
    artifact_version = str(value.get("artifact_version") or "")
    if not bindings or not adapter_id or not artifact_version:
        return None
    return ListingRecipe(
        route_key=route_key,
        adapter_id=adapter_id,
        artifact_version=artifact_version,
        bindings=bindings,
    )
