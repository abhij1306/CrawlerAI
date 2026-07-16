"""Convert LEARN-ONCE recipe-execution values into normal ``Evidence``.

CRITICAL 3: recipe replay may only *locate* evidence on the page — it must never
mint public records or derived identifiers on its own. This module turns the
values produced by the pure ``execute_recipe`` interpreter into ordinary
``Evidence`` (real ``SourceLocator`` + provenance + subject ids), so recipe
replay flows through the SAME adapter ``resolve`` -> ``publish`` authority as
deterministic evidence. Inadmissible or arbitrary values therefore cannot
publish: they are subject to the identical resolver/publication gates.
"""

from __future__ import annotations

from typing import Literal

from app.core.config.field_mappings import (
    ASSET_IMAGE_URL_FACT_TYPE,
    OFFER_AVAILABILITY_FACT_TYPE,
    OFFER_CURRENCY_FACT_TYPE,
    OFFER_ORIGINAL_PRICE_FACT_TYPE,
    OFFER_PRICE_FACT_TYPE,
    PRODUCT_BRAND_FACT_TYPE,
    PRODUCT_DESCRIPTION_FACT_TYPE,
    PRODUCT_GTIN_FACT_TYPE,
    PRODUCT_MPN_FACT_TYPE,
    PRODUCT_SKU_FACT_TYPE,
    PRODUCT_TITLE_FACT_TYPE,
    PRODUCT_URL_FACT_TYPE,
)
from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeBinding,
    RecipeExecutionResult,
)
from app.core.shared.ids import stable_id
from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    EntityHint,
    Evidence,
    ExtractionRequest,
    SourceLocator,
)

_ENTITY_BY_PREFIX: dict[str, Literal["product", "offer", "asset", "job"]] = {
    "offer.": "offer",
    "asset.": "asset",
    "job.": "job",
    "product.": "product",
}

# LEARN-ONCE recipe replay: map a recipe record field name to the normal
# evidence fact_type per surface. Recipe execution values are converted to
# ordinary Evidence carrying these fact_types and then flow through the SAME
# adapter Resolve -> Publish authority as deterministic evidence (CRITICAL 3).
RECIPE_FIELD_FACT_TYPES_BY_SURFACE: dict[str, dict[str, str]] = {
    "ecommerce_detail": {
        "title": PRODUCT_TITLE_FACT_TYPE,
        "url": PRODUCT_URL_FACT_TYPE,
        "brand": PRODUCT_BRAND_FACT_TYPE,
        "category": "product.category",
        "description": PRODUCT_DESCRIPTION_FACT_TYPE,
        "sku": PRODUCT_SKU_FACT_TYPE,
        "mpn": PRODUCT_MPN_FACT_TYPE,
        "gtin": PRODUCT_GTIN_FACT_TYPE,
        "price": OFFER_PRICE_FACT_TYPE,
        "currency": OFFER_CURRENCY_FACT_TYPE,
        "original_price": OFFER_ORIGINAL_PRICE_FACT_TYPE,
        "availability": OFFER_AVAILABILITY_FACT_TYPE,
        "image_url": ASSET_IMAGE_URL_FACT_TYPE,
    },
    "ecommerce_listing": {
        "title": PRODUCT_TITLE_FACT_TYPE,
        "url": PRODUCT_URL_FACT_TYPE,
        "price": OFFER_PRICE_FACT_TYPE,
        "image_url": ASSET_IMAGE_URL_FACT_TYPE,
    },
    "job_listing": {
        "title": "job.title",
        "url": "job.url",
        "apply_url": "job.apply_url",
        "company": "job.company",
        "location": "job.location",
    },
    "job_detail": {
        "title": "job.title",
        "url": "job.url",
        "apply_url": "job.apply_url",
        "company": "job.company",
        "location": "job.location",
        "job_type": "job.type",
        "posted_date": "job.posted_date",
        "description": "job.description",
    },
}

# recipe binding source -> evidence locator kind.
_LOCATOR_KIND: dict[str, str] = {
    "dom_text": "css_selector",
    "dom_attribute": "css_selector",
    "json_pointer": "json_pointer",
    "network_json_pointer": "network_json_pointer",
    "script_path": "script_path",
    "url_component": "url_component",
    "artifact_text": "adapter_path",
}


def recipe_execution_evidence(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
) -> tuple[Evidence, ...]:
    """Build normal evidence from grounded recipe-execution record values.

    One subject per executed record. Field values become ``Evidence`` whose
    fact_type is the surface's recipe field map; offer/asset facts are linked to
    their parent product subject (mirroring the deterministic collectors).
    Fields that map to no known fact_type are dropped — recipe replay can only
    surface admissible facts, never arbitrary keys.
    """

    fact_types = RECIPE_FIELD_FACT_TYPES_BY_SURFACE.get(
        request.surface.value, {}
    )
    field_bindings = _field_bindings(recipe)
    rows: list[Evidence] = []
    for index, record in enumerate(execution.records[: request.max_records]):
        rows.extend(
            _record_evidence(
                request,
                record,
                index=index,
                fact_types=fact_types,
                field_bindings=field_bindings,
                recipe_id=execution.recipe_id,
            )
        )
    return tuple(rows)


def _field_bindings(recipe: ExtractionRecipe) -> dict[str, RecipeBinding]:
    bindings: dict[str, RecipeBinding] = {}
    for binding in recipe.identity:
        if binding.field:
            bindings.setdefault(binding.field, binding)
    for field, field_binding in recipe.fields.items():
        if field_binding:
            bindings.setdefault(field, field_binding[0])
    return bindings


def _record_evidence(
    request: ExtractionRequest,
    record: dict[str, object],
    *,
    index: int,
    fact_types: dict[str, str],
    field_bindings: dict[str, RecipeBinding],
    recipe_id: str,
) -> list[Evidence]:
    bundle = request.capture
    product_subject_id = stable_id(
        "recipe-subject", bundle.bundle_id, recipe_id, index, "product"
    )
    rows: list[Evidence] = []
    for field, value in record.items():
        if field.startswith("_") or value in (None, "", [], {}):
            continue
        fact_type = fact_types.get(field)
        binding = field_bindings.get(field)
        if fact_type is None or binding is None:
            continue
        subject_id, parent_subject_id, entity_type = _subject_for_fact(
            fact_type,
            bundle_id=bundle.bundle_id,
            recipe_id=recipe_id,
            index=index,
            value=value,
            product_subject_id=product_subject_id,
        )
        rows.append(
            _build_row(
                request,
                fact_type=fact_type,
                value=value,
                binding=binding,
                subject_id=subject_id,
                parent_subject_id=parent_subject_id,
                entity_type=entity_type,
            )
        )
    return rows


def _subject_for_fact(
    fact_type: str,
    *,
    bundle_id: str,
    recipe_id: str,
    index: int,
    value: object,
    product_subject_id: str,
) -> tuple[str, str | None, Literal["product", "offer", "asset", "job"]]:
    for prefix, entity_type in _ENTITY_BY_PREFIX.items():
        if not fact_type.startswith(prefix):
            continue
        if entity_type in {"product", "job"}:
            return product_subject_id, None, entity_type
        subject_id = stable_id(
            "recipe-subject", bundle_id, recipe_id, index, entity_type, str(value)
        )
        return subject_id, product_subject_id, entity_type
    return product_subject_id, None, "product"


def _build_row(
    request: ExtractionRequest,
    *,
    fact_type: str,
    value: object,
    binding: RecipeBinding,
    subject_id: str,
    parent_subject_id: str | None,
    entity_type: Literal["product", "offer", "asset", "job"],
) -> Evidence:
    bundle = request.capture
    artifact_id = binding.artifact or _default_artifact_id(bundle)
    locator = SourceLocator(
        kind=_LOCATOR_KIND.get(binding.source, "adapter_path"),  # type: ignore[arg-type]
        value=binding.attribute
        and f"{binding.path}@{binding.attribute}"
        or binding.path
        or binding.binding_id,
        preview=str(value)[:120],
    )
    hint = EntityHint(
        entity_type=entity_type,
        url=bundle.final_url if entity_type in {"offer", "asset", "job"} else None,
    )
    group_id = entity_type if entity_type != "job" else "job"
    row = evidence(
        bundle,
        artifact_id,
        "recipe_replay",
        fact_type,
        value,
        locator,
        hint=hint,
        group_id=group_id,
        confidence=0.86,
        directness="direct",
        subject_id=subject_id,
        parent_subject_id=parent_subject_id,
    )
    return row.model_copy(
        update={"surface": request.surface, "subject_id": subject_id}
    )


def _default_artifact_id(bundle) -> str:
    for artifact_type in ("rendered_html", "http_html"):
        ref = next(
            (row for row in bundle.artifacts if row.artifact_type == artifact_type),
            None,
        )
        if ref is not None:
            return ref.artifact_id
    return "html"
