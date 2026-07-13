"""Frozen, storage-free contracts for executable extraction recipes."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

RecipeSurface = Literal[
    "ecommerce_detail",
    "ecommerce_listing",
    "job_detail",
    "job_listing",
]
RecipeSource = Literal[
    "dom_text",
    "dom_attribute",
    "json_pointer",
    "network_json_pointer",
    "script_path",
    "url_component",
    "artifact_text",
]
RecipeCardinality = Literal["zero_or_one", "one", "many"]
RecipeFailureCode = Literal[
    "recipe_capture_requirement_missing",
    "recipe_template_mismatch",
    "recipe_root_not_found",
    "recipe_identity_mismatch",
    "recipe_binding_not_found",
    "recipe_join_failed",
    "recipe_cardinality_changed",
    "recipe_value_validation_failed",
    "recipe_required_field_missing",
]


class FrozenRecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecipeScope(FrozenRecipeModel):
    domain: str = Field(min_length=1)
    surface: RecipeSurface
    route_pattern: str = Field(min_length=1)
    template_signature: str | None = None


class RecipeBinding(FrozenRecipeModel):
    binding_id: str = Field(min_length=1)
    source: RecipeSource
    path: str = Field(min_length=1)
    scope: str = "record.root"
    artifact: str | None = None
    collector_id: str | None = None
    attribute: str | None = None
    field: str | None = None
    transform: str | None = None
    sense: str | None = None
    rule_id: str | None = None
    unit: str | None = None
    cardinality: RecipeCardinality = "zero_or_one"
    required: bool = False
    compare_to: str | None = None

    @model_validator(mode="after")
    def attribute_source_requires_attribute(self) -> RecipeBinding:
        if self.source == "dom_attribute" and not self.attribute:
            raise ValueError("dom_attribute binding requires attribute")
        if self.source == "network_json_pointer" and not self.artifact:
            raise ValueError("network binding requires named artifact")
        return self


class RecipeJoin(FrozenRecipeModel):
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)
    required: bool = True


class RecipeEntity(FrozenRecipeModel):
    root: RecipeBinding
    identity: tuple[RecipeBinding, ...] = ()
    fields: dict[str, tuple[RecipeBinding, ...]] = Field(default_factory=dict)
    joins: tuple[RecipeJoin, ...] = ()


class ExtractionRecipe(FrozenRecipeModel):
    schema_version: Literal["extraction_recipe.v2"] = "extraction_recipe.v2"
    recipe_id: str = Field(min_length=1)
    scope: RecipeScope
    capture_requirements: tuple[str, ...] = ()
    record_root: RecipeBinding
    identity: tuple[RecipeBinding, ...]
    entities: dict[str, RecipeEntity] = Field(default_factory=dict)
    fields: dict[str, tuple[RecipeBinding, ...]]
    exclusions: tuple[RecipeBinding, ...] = ()
    required: tuple[str, ...] = ("record.identity",)

    @model_validator(mode="after")
    def requires_identity_and_fields(self) -> ExtractionRecipe:
        if not self.identity:
            raise ValueError("recipe requires identity bindings")
        if not self.fields:
            raise ValueError("recipe requires field bindings")
        return self


class RecipeCandidate(FrozenRecipeModel):
    candidate_id: str = Field(min_length=1)
    recipe: ExtractionRecipe
    origin: Literal["deterministic", "model_assisted"]
    sample_urls: tuple[str, ...] = ()
    grounded_paths: tuple[str, ...] = ()


class RecipeBindingProposal(FrozenRecipeModel):
    proposal_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    source: RecipeSource
    path: str = Field(min_length=1)
    attribute: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    grounding_match_type: Literal["exact", "normalized"]


class BindingOutcome(FrozenRecipeModel):
    binding_id: str
    status: Literal["resolved", "missing", "rejected", "join_failed"]
    source_path: str | None = None
    value: Any = None
    detail: str | None = None


class RecipeExecutionResult(FrozenRecipeModel):
    recipe_id: str
    records: tuple[dict[str, Any], ...] = ()
    outcomes: tuple[BindingOutcome, ...] = ()
    failure_code: RecipeFailureCode | None = None
    detail: str | None = None


class DiscoveryResult(FrozenRecipeModel):
    candidate: RecipeCandidate | None = None
    failure_code: RecipeFailureCode | None = None
    detail: str | None = None
    collector_diagnostics: tuple[dict[str, Any], ...] = ()
    finding_diagnostics: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def candidate_or_failure(self) -> DiscoveryResult:
        if (self.candidate is None) == (self.failure_code is None):
            raise ValueError("discovery returns exactly one candidate or failure")
        return self


class DiscoveryCompiler(Protocol):
    def compile(self, capture_request: object) -> DiscoveryResult: ...
