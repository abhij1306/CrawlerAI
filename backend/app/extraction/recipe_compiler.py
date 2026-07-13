"""Compile grounded discovery decisions into recipes without publishing records."""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlsplit

from app.core.config.extraction_price_rules import (
    CURRENCY_DECIMAL_PLACES,
    DEFAULT_DECIMAL_PLACES,
)
from app.core.extraction_memory.recipe_contracts import (
    DiscoveryResult,
    ExtractionRecipe,
    RecipeBinding,
    RecipeBindingProposal,
    RecipeCandidate,
)
from app.core.shared.ids import stable_id
from app.extraction.adapters import adapter_for
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    HarvestResult,
    PublicationEntry,
    ResolutionEnvelope,
)
from app.extraction.surfaces import Surface

from app.extraction.recipe_compiler_dom import _dom_path_to_css
from app.extraction.recipe_compiler_grounding import (
    _all_bindings,
    _binding,
    _detail_root,
    _entry_evidence,
    _failure,
    _field,
    _recipe,
    _required_fields,
)
from app.extraction.recipe_compiler_listing import _listing_recipe
from app.extraction.recipe_compiler_variants import _detail_variant_recipe


class DiscoverySource(Protocol):
    def harvest(self, request: ExtractionRequest) -> HarvestResult: ...

    def resolve(
        self, request: ExtractionRequest, harvest: HarvestResult
    ) -> ResolutionEnvelope: ...


class _AdapterDiscoverySource:
    def harvest(self, request: ExtractionRequest) -> HarvestResult:
        return adapter_for(request.surface).harvest(request)

    def resolve(
        self, request: ExtractionRequest, harvest: HarvestResult
    ) -> ResolutionEnvelope:
        return adapter_for(request.surface).resolve(request, harvest)


def compile_recipe_candidate(
    request: ExtractionRequest, source: DiscoverySource | None = None
) -> DiscoveryResult:
    """Run bounded discovery and return only an executable candidate or abstention."""

    discovery = source or _AdapterDiscoverySource()
    harvest = discovery.harvest(request)
    diagnostics = tuple(
        row.model_dump(mode="json") for row in harvest.collector_outcomes
    )
    resolution = discovery.resolve(request, harvest)
    if resolution.target.status == "ambiguous":
        return _failure(
            "recipe_identity_mismatch", "ambiguous discovery target", diagnostics
        )
    if resolution.target.status == "wrong_surface":
        return _failure(
            "recipe_identity_mismatch", "wrong surface discovery target", diagnostics
        )
    if any(finding.blocking for finding in resolution.findings):
        return _failure(
            "recipe_value_validation_failed",
            "blocking discovery finding",
            diagnostics,
        )
    projection = resolution.publication
    entries = tuple(
        row
        for row in projection.entries
        if row.disposition == "publish" and row.evidence_ids
    )
    if not entries:
        return _failure(
            "recipe_binding_not_found", "no grounded projection entries", diagnostics
        )
    evidence = {row.evidence_id: row for row in harvest.evidence}
    recipe = (
        _listing_recipe(request, entries, evidence)
        if request.surface in {Surface.ECOMMERCE_LISTING, Surface.JOB_LISTING}
        else _detail_recipe(request, entries, evidence)
    )
    if recipe is None:
        return _failure(
            "recipe_identity_mismatch", "grounded identity unavailable", diagnostics
        )
    paths = tuple(
        dict.fromkeys(
            binding.path
            for binding in _all_bindings(recipe)
            if binding.path not in {"", "."}
        )
    )
    page_url = request.capture.final_url or request.capture.requested_url
    return DiscoveryResult(
        candidate=RecipeCandidate(
            candidate_id=stable_id(
                "recipe-candidate", request.capture.bundle_id, request.surface.value
            ),
            recipe=recipe,
            origin="deterministic",
            sample_urls=(page_url,),
            grounded_paths=paths,
        ),
        collector_diagnostics=diagnostics,
        finding_diagnostics=tuple(
            row.model_dump(mode="json") for row in resolution.findings
        ),
    )


def compile_model_proposals(
    request: ExtractionRequest,
    proposals: tuple[RecipeBindingProposal, ...],
) -> DiscoveryResult:
    """Compile grounded model paths; proposal values are intentionally unavailable."""

    by_field = {proposal.field: proposal for proposal in proposals}
    required = _required_fields(request.surface)
    if not all(field in by_field for field in required):
        return _failure("recipe_required_field_missing", "model paths incomplete")
    if "url" not in by_field and "apply_url" not in by_field:
        return _failure("recipe_identity_mismatch", "model identity path missing")
    root = _detail_root(request, proposals[0].artifact_id) if proposals else None
    if root is None:
        return _failure("recipe_root_not_found", "model root unavailable")
    fields: dict[str, tuple[RecipeBinding, ...]] = {
        field: (
            RecipeBinding(
                binding_id=f"field.{field}",
                source=proposal.source,
                artifact=proposal.artifact_id,
                path=(
                    _dom_path_to_css(proposal.path)
                    if proposal.path.startswith("/")
                    else proposal.path
                ),
                scope="document",
                field=field,
                attribute=proposal.attribute,
                required=field in required,
            ),
        )
        for field, proposal in by_field.items()
    }
    identity_field = "url" if "url" in fields else "apply_url"
    identity = (
        fields[identity_field][0].model_copy(
            update={
                "binding_id": "record.identity.url",
                "compare_to": "request.final_url" if identity_field == "url" else None,
                "required": True,
            }
        ),
    )
    recipe = _recipe(request, root, identity, fields, required)
    return DiscoveryResult(
        candidate=RecipeCandidate(
            candidate_id=stable_id(
                "model-recipe-candidate",
                request.capture.bundle_id,
                request.surface.value,
            ),
            recipe=recipe,
            origin="model_assisted",
            sample_urls=(request.capture.final_url,),
            grounded_paths=tuple(proposal.path for proposal in proposals),
        )
    )


def _detail_recipe(
    request: ExtractionRequest,
    entries: tuple[PublicationEntry, ...],
    evidence: dict[str, Evidence],
) -> ExtractionRecipe | None:
    fields: dict[str, tuple[RecipeBinding, ...]] = {}
    identity: tuple[RecipeBinding, ...] = ()
    artifact_id = ""
    currency = _selected_currency(entries)
    for entry in entries:
        compiled = _detail_entry_binding(request, entry, evidence, fields)
        if compiled is None:
            continue
        field, row, binding = compiled
        binding = _configured_detail_binding(binding, entry, field, currency, fields)
        artifact_id = artifact_id or row.artifact_id
        _store_detail_binding(fields, field, binding)
        if field in {"url", "apply_url"}:
            identity = (
                _detail_identity_binding(request, row, evidence.values(), field)
                or identity
            )
    required = _required_fields(request.surface)
    if not identity or not all(field in fields for field in required):
        return None
    root = _detail_root(request, artifact_id)
    if root is None:
        return None
    entities, variant_binding = _detail_variant_recipe(request, entries, evidence)
    if variant_binding is not None:
        fields["variants"] = (variant_binding,)
    return _recipe(
        request,
        root,
        identity,
        fields,
        required,
        entities=entities,
    )


def _selected_currency(entries: tuple[PublicationEntry, ...]) -> str:
    return next(
        (
            str(entry.value or "").strip().upper()
            for entry in entries
            if _field(entry.path) == "currency"
        ),
        "",
    )


def _detail_entry_binding(request, entry, evidence, fields):
    if entry.path.startswith("variant["):
        return None
    field = _detail_entry_field(entry)
    row = _entry_evidence(entry, evidence)
    if not field or row is None:
        return None
    binding = _special_detail_binding(request, entry, row, field)
    if binding is None:
        return None
    if (
        field == "brand"
        and str(entry.value).isupper()
        and binding.transform
        and binding.transform.startswith("slug_words:")
    ):
        binding = binding.model_copy(
            update={"transform": f"uppercase_{binding.transform}"}
        )
    return field, row, binding


def _detail_entry_field(entry: PublicationEntry) -> str:
    if entry.path.startswith("asset[") and entry.path.endswith(".url"):
        return (
            "additional_images"
            if entry.rule_id == "PRODUCT_ASSET_ADDITIONAL"
            else "image_url"
        )
    return _field(entry.path)


def _special_detail_binding(request, entry, row, field):
    if field == "currency" and entry.rule_id == "currency_from_page_url_hint":
        return RecipeBinding(
            binding_id="field.currency",
            source="url_component",
            path="final_url",
            scope="document",
            field="currency",
            transform="currency_from_page_url",
        )
    if field == "currency" and entry.rule_id == "currency_from_price_symbol":
        price = _binding(row, field="price", scope="record.root", request=request)
        return (
            price.model_copy(
                update={
                    "field": "currency",
                    "unit": None,
                    "transform": "currency_from_price_symbol",
                }
            )
            if price
            else None
        )
    if field == "brand" and entry.rule_id in {
        "page_identity",
        "brand_from_product_url",
        "brand_from_title_host",
    }:
        return _page_identity_binding(request, row, entry.value)
    return _binding(row, field=field, scope="record.root", request=request)


def _configured_detail_binding(binding, entry, field, currency, fields):
    unit = binding.unit
    if (
        unit == "minor"
        and CURRENCY_DECIMAL_PLACES.get(currency, DEFAULT_DECIMAL_PLACES) == 0
    ):
        unit = "major"
    elif field in {"price", "original_price"} and entry.rule_id in {
        "explicit_minor_unit_price",
        "corroborated_price_scale",
    }:
        unit = "minor"
    return binding.model_copy(
        update={
            "binding_id": (
                f"field.{field}.{len(fields.get(field, ()))}"
                if field == "additional_images"
                else f"field.{field}"
            ),
            "field": field,
            "rule_id": entry.rule_id,
            "unit": unit,
            "cardinality": (
                "many" if field == "additional_images" else binding.cardinality
            ),
        }
    )


def _store_detail_binding(fields, field, binding) -> None:
    if field == "additional_images":
        fields[field] = (*fields.get(field, ()), binding)
    else:
        fields.setdefault(field, (binding,))


def _detail_identity_binding(request, selected, rows, field):
    identity_row = _detail_identity_evidence(request, selected, rows)
    binding = _binding(
        identity_row,
        field=field,
        scope="record.root",
        request=request,
    )
    if binding is None:
        return ()
    return (
        binding.model_copy(
            update={
                "binding_id": "record.identity.url",
                "compare_to": "request.final_url" if field == "url" else None,
                "required": True,
            }
        ),
    )


def _detail_identity_evidence(
    request: ExtractionRequest,
    selected: Evidence,
    rows,
) -> Evidence:
    final_url = request.capture.final_url or request.capture.requested_url
    linked_subjects = {selected.subject_id, *selected.source_subject_ids}
    return next(
        (
            row
            for row in rows
            if row.fact_type == "product.url"
            and str(row.value) == final_url
            and bool(linked_subjects & {row.subject_id, *row.source_subject_ids})
        ),
        selected,
    )


def _page_identity_binding(
    request: ExtractionRequest, row: Evidence, expected: object
) -> RecipeBinding | None:
    target_words = re.findall(r"[a-z0-9]+", str(expected).casefold())
    source_words = re.findall(r"[a-z0-9]+", str(row.raw_value).casefold())
    if target_words and source_words[: len(target_words)] == target_words:
        source_row = row.model_copy(update={"value": row.raw_value})
        binding = _binding(
            source_row, field="brand", scope="record.root", request=request
        )
        if binding is not None:
            return binding.model_copy(
                update={"transform": f"prefix_words:{len(target_words)}"}
            )
    url = request.capture.final_url or request.capture.requested_url
    ignored_labels = {
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
    host_labels = [
        label
        for label in (urlsplit(url).hostname or "").casefold().split(".")
        if label not in ignored_labels
    ]
    suffixes = ("beauty", "cosmetics", "official", "online", "shop", "store")
    if host_labels and target_words:
        compact = re.sub(r"[^a-z0-9]", "", max(host_labels, key=len))
        for suffix in suffixes:
            if compact.endswith(suffix):
                compact = compact[: -len(suffix)]
                break
        if compact == "".join(target_words):
            lengths = ",".join(str(len(word)) for word in target_words)
            return RecipeBinding(
                binding_id="field.brand",
                source="url_component",
                path="host",
                scope="document",
                field="brand",
                transform=f"host_words:{lengths}",
            )
    slug_words = re.findall(r"[a-z0-9]+", urlsplit(url).path.casefold())
    for index in range(len(slug_words) - len(target_words) + 1):
        if slug_words[index : index + len(target_words)] == target_words:
            lengths = ",".join(str(len(word)) for word in target_words)
            return RecipeBinding(
                binding_id="field.brand",
                source="url_component",
                path="path",
                scope="document",
                field="brand",
                transform=f"slug_words:{index}:{lengths}",
            )
    return None
