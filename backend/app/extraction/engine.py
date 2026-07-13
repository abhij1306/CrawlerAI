"""One extraction runtime: select/compile recipe, execute, validate, publish."""

from __future__ import annotations

from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeExecutionResult,
)
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.extraction.contracts import ExtractionRequest, ExtractionResult, StageOutcome
from app.extraction.model_runtime import (
    RuntimeModelAdapter,
    run_model_recipe_proposals,
)
from app.extraction.recipe_compiler import (
    compile_model_proposals,
    compile_recipe_candidate,
)
from app.extraction.result_building import (
    blocked_result as _blocked_result,
    execution_result,
    failed_result,
)
from app.observability.extraction_diagnostics import (
    discovery_stage,
    execution_stage,
    model_stage,
)


def extract(
    request: ExtractionRequest,
    *,
    model_adapter: RuntimeModelAdapter | None = None,
) -> ExtractionResult:
    if request.capture.blocked:
        return _blocked_result(request, (), ())

    stages = [StageOutcome(stage="recipe_select", outcome="no_match")]
    template = select_active_recipe(
        dict(request.runtime_snapshot),
        surface=request.surface.value,
        url=request.capture.final_url or request.capture.requested_url,
        template_signature=str(
            request.runtime_snapshot.get("_template_signature") or ""
        ),
    )
    active_failure: RecipeExecutionResult | None = None
    if template is not None:
        stages[0] = StageOutcome(stage="recipe_select", outcome="ran")
        active_request, recipe = _active_recipe_request(request, template)
        active_failure = execute_recipe(active_request, recipe)
        stages.append(execution_stage("recipe_execute", active_failure))
        if active_failure.records:
            return execution_result(
                active_request,
                recipe,
                active_failure,
                candidate=None,
                template=template,
                stages=tuple(stages),
                model=None,
            )

    discovery = compile_recipe_candidate(request)
    stages.append(discovery_stage("recipe_discovery", discovery))
    if discovery.candidate is not None:
        execution = execute_recipe(request, discovery.candidate.recipe)
        stages.append(execution_stage("candidate_recipe_execute", execution))
        if execution.records:
            return execution_result(
                request,
                discovery.candidate.recipe,
                execution,
                candidate=discovery.candidate,
                template=template,
                stages=tuple(stages),
                model=None,
                discovery=discovery,
            )
        active_failure = execution

    model = run_model_recipe_proposals(request, model_adapter)
    stages.append(model_stage(model))
    if model.proposals:
        model_discovery = compile_model_proposals(request, model.proposals)
        stages.append(discovery_stage("model_recipe_compile", model_discovery))
        if model_discovery.candidate is not None:
            execution = execute_recipe(request, model_discovery.candidate.recipe)
            stages.append(execution_stage("candidate_recipe_execute", execution))
            if execution.records:
                return execution_result(
                    request,
                    model_discovery.candidate.recipe,
                    execution,
                    candidate=model_discovery.candidate,
                    template=template,
                    stages=tuple(stages),
                    model=model,
                )
            active_failure = execution

    return failed_result(
        request,
        execution=active_failure,
        discovery=discovery,
        template=template,
        stages=tuple(stages),
        model=model,
    )


def _active_recipe_request(
    request: ExtractionRequest, template: dict[str, object]
) -> tuple[ExtractionRequest, ExtractionRecipe]:
    recipe = ExtractionRecipe.model_validate(template.get("compiled_recipe"))
    manifest = request.manifest_context.model_copy(
        update={
            "template_id": str(template.get("template_id") or "") or None,
            "compiled_recipe_id": str(template.get("compiled_recipe_id") or "") or None,
        }
    )
    return request.model_copy(update={"manifest_context": manifest}), recipe
