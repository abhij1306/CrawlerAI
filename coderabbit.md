These are comments left during a code review. Please review all issues and provide fixes.

1. incomplete implementation: Manifest metadata is partially discarded, causing downstream extraction context to lose required identifiers.
   Path: backend/app/extraction/replay.py
   Lines: 334-334

2. code quality: Duplicated snapshot mutation logic can drift and cause inconsistent behavior between equivalent execution paths.
   Path: backend/app/crawl/pipeline/record_extraction_stage.py
   Lines: 128-128

3. race condition: Concurrent activation requests can race and produce inconsistent active snapshot assignment.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 376-376

4. incomplete implementation: Missing compatibility checks allow assigning an unrelated release snapshot to a run.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 373-373

5. performance: Repeated full-set scans in rule merging introduce avoidable quadratic runtime overhead.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 131-131

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

These are comments left during a code review. Please review all issues and provide fixes.

1. api mismatch: A newly added required domain dimension is silently backfilled with a wrong default, causing legacy records to be misclassified.
   Path: backend/app/evaluation/schema.py
   Lines: 263-263

2. logic error: Model fallback errors are classified too early and can mask the real deterministic extraction failure category.
   Path: backend/app/extraction/engine.py
   Lines: 498-498

3. performance: Repeated filtering inside nested loops causes unnecessary quadratic processing for listing resolution.
   Path: backend/app/extraction/jobs.py
   Lines: 468-468

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/evaluation/schema.py around lines 282 - 295, The validation in the schema model repeats the same “invalid values then uniqueness” pattern for scenario_tags and required_metrics, which risks copy-paste drift. Refactor the checks in the relevant validation method on the schema class to use a small shared helper that handles both unsupported-membership and duplicate detection consistently, then call it for scenario_tags and required_metrics using the existing EVALUATION_SCENARIOS and UNIVERSAL_MODEL_REQUIRED_METRICS sets.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 374 - 400, The import check in test_runtime_model_fallback_cannot_resolve_publish_or_persist is too broad because it bans app.models in addition to the resolution/publication/persistence layers. Narrow the forbidden_prefixes tuple to only the exact packages that this architectural boundary is meant to isolate, and keep the offender scan logic unchanged so it still flags only those targeted imports.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 334 - 344, Replace the raw substring scan in test_phase4_evaluation_modules_are_offline_only with a semantic API check against the evaluation package itself; importing backend.app.evaluation and asserting the runtime_alias names are absent from the module object or from its __all__ will make the test resilient to comments/docstrings. Keep the same alias list, but verify the public exports via the package’s actual symbol table rather than reading evaluation/__init__.py as text.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 402 - 424, The architecture test currently only flags direct Name assignments in test_universal_model_config_does_not_live_in_extraction_service_code, so config can still slip through via attributes, tuples, dict entries, or other assignment forms. Update the AST check in this test to inspect all assignment targets recursively and catch forbidden names anywhere in an assignment shape, using the existing forbidden_assignment_names set and the test’s offenders collection as the anchor.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/model_runtime.py around lines 141 - 143, The runtime around adapter.predict in model_runtime should not rely only on passing timeout_ms through, because a blocking adapter can still hang past the budget. Enforce a hard timeout at the runtime boundary in the extraction flow (around the predict call in the model_runtime path), or explicitly verify that concrete adapters apply and honor client deadlines and raise TimeoutError; then treat that timeout as a normal extraction failure path. Use the adapter.predict call site, the elapsed-time budget check, and any adapter interface/implementation contract to locate the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/model_runtime.py around lines 251 - 260, The _approved_artifact helper in model_runtime.py dereferences request.runtime_snapshot without checking for None, which can crash zero-record requests. Update _approved_artifact to handle a missing runtime_snapshot before calling get(), returning the same disabled fallback tuple when request.runtime_snapshot is None, and keep the existing Mapping/ValidationError handling for the UniversalModelArtifact lookup.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/model_runtime.py around lines 406 - 409, The _normalize_source_value helper is dropping valid zero-like values because str(value or "") converts 0 and False to an empty string. Update _normalize_source_value in model_runtime.py to only treat None as empty, while preserving numeric zero during casefold/whitespace normalization for grounded values.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_evaluation_phase4.py around lines 114 - 141, Repeated ad-hoc fake adapter construction should be consolidated into one reusable helper/factory. Update the test helpers around _run_fixture_adapter and the existing FakeAdapter pattern so call sites stop using inline type("Adapter", ...) objects and instead build adapters through a single parametrized factory that accepts adapter_id and either a result or predict callable. Then replace the duplicated adapter setup at the referenced test sites with that shared helper to keep the adapter contract in one place.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_evaluation_phase4.py around lines 34 - 42, The helper names are inverted relative to the GroundingReference.kind they construct, which is confusing in the evaluation fixtures. Update the test helpers in test_evaluation_phase4 so the function names match the kinds they return: rename _node and _css_node (or swap their behavior) to align with kind="path" and kind="node" respectively, and update any call sites in the same test file to use the new, clearer names.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_evaluation_phase4.py around lines 212 - 230, The compact representation test is hardcoding the global node cap instead of asserting against the configured limit. Update test_compact_representation_resolves_css_node_labels_and_enforces_global_cap to import and use the compact-representation cap constant from app.core.config.evaluation (the same source used by build_compact_page_representation), so the assertion tracks the real contract if the limit changes. Keep the rest of the checks in place, especially the truncation and label resolution assertions.

S C:\Projects\CrawlerAI\backend> mypy .
app\evaluation\benchmark.py:466: error: Argument 1 to "float" has incompatible type "Any | None"; expected "str | Buffer | SupportsFloat | SupportsIndex"  [arg-type]
app\evaluation\benchmark.py:473: error: Argument 1 to "float" has incompatible type "Any | None"; expected "str | Buffer | SupportsFloat | SupportsIndex"  [arg-type]
Found 2 errors in 1 file (checked 351 source files)
PS C:\Projects\CrawlerAI\backend> 

overage PASSED [100%]

================================ FAILURES =================================
_____ test_compact_page_representation_is_bounded_and_source_grounded _____
tests\unit\test_evaluation_phase4.py:165: in test_compact_page_representation_is_bounded_and_source_grounded
    assert any(node.repeated_block_key for node in page.nodes)
E   assert False
E    +  where False = any(<generator object test_compact_page_representation_is_bounded_and_source_grounded.<locals>.<genexpr> at 0x000001E80A67DBE0>)
_______ test_offline_model_harness_emits_evidence_only_predictions ________
tests\unit\test_evaluation_phase4.py:332: in test_offline_model_harness_emits_evidence_only_predictions
    result = run_offline_adapter(case_id="case-1", page=page, adapter=FakeAdapter())
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
______ test_benchmark_gate_compares_to_baseline_and_ungrounded_rate _______
tests\unit\test_evaluation_phase4.py:528: in test_benchmark_gate_compares_to_baseline_and_ungrounded_rate
    harness = run_offline_adapter(
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
_______ test_benchmark_gate_uses_unseen_partition_not_aggregate_f1 ________
tests\unit\test_evaluation_phase4.py:572: in test_benchmark_gate_uses_unseen_partition_not_aggregate_f1
    known_result = _run_fixture_adapter(
tests\unit\test_evaluation_phase4.py:135: in _run_fixture_adapter
    return run_offline_adapter(
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
___ test_benchmark_gate_fails_closed_when_baseline_signals_are_missing ____
tests\unit\test_evaluation_phase4.py:712: in test_benchmark_gate_fails_closed_when_baseline_signals_are_missing
    result = _run_fixture_adapter(
tests\unit\test_evaluation_phase4.py:135: in _run_fixture_adapter
    return run_offline_adapter(
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
_______ test_benchmark_gate_fails_closed_for_invalid_baseline_rates _______
tests\unit\test_evaluation_phase4.py:744: in test_benchmark_gate_fails_closed_for_invalid_baseline_rates
    result = _run_fixture_adapter(
tests\unit\test_evaluation_phase4.py:135: in _run_fixture_adapter
    return run_offline_adapter(
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
______________ test_benchmark_command_loads_candidate_inputs ______________
tests\unit\test_evaluation_phase4.py:830: in test_benchmark_command_loads_candidate_inputs
    result = _run_fixture_adapter(
tests\unit\test_evaluation_phase4.py:135: in _run_fixture_adapter
    return run_offline_adapter(
app\evaluation\model_harness.py:130: in run_offline_adapter
    _validate_prediction_grounding(page, result.predictions)
app\evaluation\model_harness.py:172: in _validate_prediction_grounding
    raise ValueError(
E   ValueError: Prediction grounding must resolve to a retained compact node
_ test_new_extraction_imports_forbidden_parser_stack_only_in_document_store_
tests\unit\test_extraction_architecture.py:94: in test_new_extraction_imports_forbidden_parser_stack_only_in_document_store
    assert "selectolax" not in imports, path
E   AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extraction/model_runtime.py')
E   assert 'selectolax' not in {'__future__', 'app', 'dataclasses', 'hashlib', 'pydantic', 'selectolax', ...}
___ test_current_ecommerce_detail_path_uses_document_store_parser_only ____
tests\unit\test_extraction_architecture.py:109: in test_current_ecommerce_detail_path_uses_document_store_parser_only
    assert imports.isdisjoint(forbidden), path
E   AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extraction/model_runtime.py')
E   assert False
E    +  where False = <built-in method isdisjoint of set object at 0x000001E87851B060>({'bs4', 'extruct', 'glom', 'jmespath', 'lxml', 'selectolax'})
E    +    where <built-in method isdisjoint of set object at 0x000001E87851B060> = {'__future__', 'app', 'dataclasses', 'hashlib', 'pydantic', 'selectolax', ...}.isdisjoint
________ test_extraction_package_stays_within_architecture_limits _________
tests\unit\test_extraction_architecture.py:214: in test_extraction_package_stays_within_architecture_limits
    assert (
E   assert 12925 <= 12922
E    +  where 12925 = sum(<generator object test_extraction_package_stays_within_architecture_limits.<locals>.<genexpr> at 0x000001E8785BD0E0>)
______ test_known_template_recipe_fast_path_skips_generic_collectors ______
tests\unit\test_extraction_runtime_behavior.py:188: in test_known_template_recipe_fast_path_skips_generic_collectors
    assert {row.collector_id for row in result.evidence} == {"css_recipe", "url"}
E   AssertionError: assert {'css_recipe', 'dom', 'url'} == {'css_recipe', 'url'}
E     
E     Extra items in the left set:
E     'dom'
E     
E     Full diff:
E       {
E           'css_recipe',...
E     
E     ...Full output truncated (3 lines hidden), use '-vv' to show
___________________ test_production_package_loc_budgets ___________________
tests\unit\test_final_architecture_ownership.py:149: in test_production_package_loc_budgets
    assert sum(_physical_line_count(path) for path in app_files) <= TOTAL_APP_LOC_BUDGET
E   assert 73364 <= 73349
E    +  where 73364 = sum(<generator object test_production_package_loc_budgets.<locals>.<genexpr> at 0x000001E87A7ABAE0>)
______________________ test_no_new_oversized_modules ______________________
tests\unit\test_final_architecture_ownership.py:167: in test_no_new_oversized_modules
    assert all(
E   assert False
E    +  where False = all(<generator object test_no_new_oversized_modules.<locals>.<genexpr> at 0x000001E87A7C7920>)
========================= short test summary info =========================
FAILED tests/unit/test_evaluation_phase4.py::test_compact_page_representation_is_bounded_and_source_grounded - assert False
FAILED tests/unit/test_evaluation_phase4.py::test_offline_model_harness_emits_evidence_only_predictions - ValueError: Prediction grounding must resolveto a retained compact node
FAILED tests/unit/test_evaluation_phase4.py::test_benchmark_gate_compares_to_baseline_and_ungrounded_rate - ValueError: Prediction grounding must resolve to a retained compact node
FAILED tests/unit/test_evaluation_phase4.py::test_benchmark_gate_uses_unseen_partition_not_aggregate_f1 - ValueError: Prediction grounding must resolveto a retained compact node
FAILED tests/unit/test_evaluation_phase4.py::test_benchmark_gate_fails_closed_when_baseline_signals_are_missing - ValueError: Prediction grounding mustresolve to a retained compact node
FAILED tests/unit/test_evaluation_phase4.py::test_benchmark_gate_fails_closed_for_invalid_baseline_rates - ValueError: Prediction grounding must resolve to a retained compact node
FAILED tests/unit/test_evaluation_phase4.py::test_benchmark_command_loads_candidate_inputs - ValueError: Prediction grounding must resolve to a retained compact node
FAILED tests/unit/test_extraction_architecture.py::test_new_extraction_imports_forbidden_parser_stack_only_in_document_store - AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extracti...
FAILED tests/unit/test_extraction_architecture.py::test_current_ecommerce_detail_path_uses_document_store_parser_only - AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extracti...
FAILED tests/unit/test_extraction_architecture.py::test_extraction_package_stays_within_architecture_limits - assert 12925 <= 12922
FAILED tests/unit/test_extraction_runtime_behavior.py::test_known_template_recipe_fast_path_skips_generic_collectors - AssertionError: assert {'css_recipe', 'dom', 'url'} == {'css_recipe', '...
FAILED tests/unit/test_final_architecture_ownership.py::test_production_package_loc_budgets - assert 73364 <= 73349
FAILED tests/unit/test_final_architecture_ownership.py::test_no_new_oversized_modules - assert False
=============== 13 failed, 1431 passed in 426.08s (0:07:06) ===============
PS C:\Projects\CrawlerAI\backend> 