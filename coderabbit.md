Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/knowledge_graph/contract_runtime.py around lines 123 - 133, The contract hit detection in contract_runtime should not rely only on the first entry in decision.accepted_evidence_ids. Update the logic around the selected/applied check to inspect all accepted evidence IDs and resolve evidence through evidence_by_id until a matching _source_descriptor(selected) is found, so a later preferred source still reports as applied for CONTRACT_PREFERRED_SOURCE.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/knowledge_graph/contract_runtime.py around lines 34 - 35, The route selection in contract_runtime’s match handling is returning the first entry from route_matches, which can skip later route-only templates that may contain higher-priority operator contracts. Update the selection logic around the route_matches return path so all route-only template matches are merged or evaluated before choosing a contract, and make the final selection in the relevant matching function prioritize the best operator contract rather than the first route match.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/contracts.py around lines 251 - 278, The PublicationEntry invariant is too permissive because the default disposition is "publish" but _source_is_unambiguous() only enforces lineage when value is present, allowing publish entries with no value or source. Update the model_validator on PublicationEntry to reject any publish disposition unless value is set and exactly one of selected_fact_id or derived_fact_id is provided, while preserving the existing multiple-source check. Use the PublicationEntry class and its _source_is_unambiguous method to locate the fix.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/engine.py around lines 43 - 48, Short-circuit blocked captures before any harvesting work in extract(). Move the request.capture.blocked check to happen before adapter_for() and adapter.harvest(), so blocked requests return via _blocked_result() without reading artifacts; keep the existing extract(), _blocked_result(), and harvest flow otherwise unchanged.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/jobs.py around lines 63 - 70, The subject-merging logic in the jobs extraction flow is still using the full DOM-derived subject identity, so duplicate JobPosting blocks can remain split when only script/path differ. Update the subject ID construction used by the extraction job flow (around the structured/dom merge in jobs.py and the shared subject identity logic it relies on) to prefer the canonical JSON-LD identity fields first, and only fall back to script_index/path when no canonical identity is available. This should let identical JobPosting entities resolve to the same subject so the merge in the structured_subjects/subject_id block can combine DOM evidence correctly, and apply the same identity precedence in the other referenced merge path as well.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/pipeline.py around lines 145 - 150, The HarvestResult construction in the extraction pipeline is using the evidence row count as admitted_source_objects, which inflates metrics. Update the logic around the return in the pipeline function so admitted_source_objects reflects the actual number of source objects admitted by the collector outcomes or upstream pipeline data, not len(rows). If the current contract only tracks evidence, thread the real source-object count through the function and keep the evidence tuple separate from the admitted source-object metric.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/pipeline.py around lines 105 - 112, The JsStateCollector handling in pipeline.py is using the harvest outcome before filtering, so it can report produced evidence even when no JsState rows survive the FACT_TYPES filter. In the collector branch of the pipeline logic, keep the existing budget-related outcomes from harvest.outcomes, but replace the copied produced_evidence/no_match result with a fresh outcome computed from len(collector_rows). Use the JsStateCollector.harvest flow and the outcomes list in this block to locate and adjust the logic.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/resolution.py around lines 652 - 658, Avoid emitting derived parent facts when the parent already has a directly resolved fact. Update the availability and uniform multi-variant aggregation paths in resolution.py, especially _aggregate_variant_availability and the related variant-field logic around the affected blocks, so they check the parent entity’s resolved fact set before appending offer.price, offer.currency, or offer.availability. Preserve existing direct parent evidence and only derive aggregates for fields that are still unresolved.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/resolution.py around lines 1660 - 1666, The fallback in `_rejected_reason` is comparing full `_rank(ev)` values, but `_rank()` includes `evidence_id`, so tied candidates never match and get mislabeled as `lower_confidence`. Update `_rejected_reason` to compare ranks without the `evidence_id` tiebreaker, using the ranking components from `_rank`/`winner` that represent all fields except `evidence_id`, so true ties return `stable_tiebreak` while only genuinely worse candidates return `lower_confidence`.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/result_building.py around lines 327 - 349, Carry disposition reason codes through the evidence-only path in `result_building.py` so `FieldEvidenceState` does not drop resolver explanations when there is matching evidence but no projection entry. In the `fact_by_field`/`candidates` branch, extend the `state` selection logic to account for non-unowned terminal dispositions (for example rejected or diagnostic-only) using `disposition_by_id`, and populate `reason_codes` from the matching evidence dispositions instead of leaving them empty. Keep the fix localized around the `FieldEvidenceState` assembly and the existing `disposition_by_id`, `candidates`, and `reason_codes` handling.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/targeting.py around lines 69 - 71, The tuple branch in scoped_graph is too broad because it assumes every tuple is a tuple[str, ...] and filters by root_entity_ids, which can silently drop non-ID payloads. Narrow the condition to only handle tuples that are actually collections of entity ID strings, or add a type/shape check before filtering, and otherwise leave tuple payloads unchanged; use the scoped_graph function and target.root_entity_ids to locate the logic.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/observability/run_report.py around lines 28 - 29, Exclude `not_requested` from run-level root cause aggregation by updating `_root_causes()` in `run_report.py` so intentionally unrequested fields are treated like the existing clean states and do not produce `field:<name>:not_requested` entries. Use the existing `_CLEAN_FIELD_STATES` handling and the root-cause assembly logic to locate the change, and ensure only true problem states are counted in the run report.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/persistence/url_result_artifacts.py around lines 212 - 244, Update `_shrink_diagnose_payload()` so the `truncated` metadata reflects every pruning pass, not just `artifact_size`: when `shrink_steps` further reduces `evidence_dispositions.examples`, `findings`, `fields`, or `variants.dropped`, record those caps in the `truncated` object before returning. Make sure the fallback payload returned by `_shrink_diagnose_payload()` preserves the same `truncated` details, so `diagnose.json` always matches the final size-capped contents.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_diagnostics_api.py at line 73, The diagnostics API test fixture is only updating schema_version to diagnose.v2, but it is missing the new top-level v2 roots that the real artifact now includes. Update the diagnosis payload in the diagnostics test fixture(s) to keep them schema-complete by seeding findings and evidence_dispositions as empty arrays, alongside the existing fields, so the tests still validate the actual diagnose.v2 shape. Use the diagnosis fixture in the component diagnostics test as the reference point and apply the same change to the other matching fixture mentioned in the review.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 381 - 393, The persistence ratchet test is using raw substring matching on persistence.py, which can miss inline repair logic or renamed helpers. Update test_persistence_performs_no_extraction_repair to inspect the AST for imports and calls in the persistence boundary instead of scanning text, and keep the existing forbidden symbols as the identifiers to assert against. Use the persistence.py module and the test_extraction_architecture.py test function as the main anchors when implementing the AST-based check.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 365 - 378, The current ratchet only checks annotated parameters on serialize_* functions in publication.py, so raw Evidence/EntitySet can still slip through other publish paths. Update test_extraction_architecture.py to inspect the real publish boundary by tracing the call chain from the actual publish entrypoints, including adapters._publish and any helper/async functions involved, and assert that no publish-facing function accepts raw Evidence or EntitySet even when parameters are untyped or annotations are missing. Use the existing publication module parsing and the _parse_module helper to locate the relevant symbols and broaden the scan beyond serializer signatures.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_pipeline.py around lines 1459 - 1461, The assertions around the `offer.price` evidence should check for the absence of the `explicit_minor_unit_price` marker rather than requiring `item.flags` to be empty, since unrelated diagnostics may still be present. Update the relevant `result.evidence` checks in `test_extraction_pipeline.py` so they match on `fact_type == "offer.price"` and `raw_value == 13875` (and the other affected cases) while explicitly verifying that the repair marker is not included in `item.flags`.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_pipeline.py around lines 1619 - 1623, The corroborated-price test assertions are too broad because they match any raw offer.price evidence row instead of verifying the lineage contract. Update the affected tests around _price_repair_facts and result.evidence to assert against fact.input_evidence_ids, following the same pattern already used later in this file, so the derived fact is bound to the specific source evidence rather than just any matching raw value.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/lib/api/types.ts around lines 698 - 715, The ResultDiagnosis type’s truncated map is too narrow and no longer matches the diagnose.v2 backend payload. Update the truncated property in types.ts so it can represent truncated.artifact_size with original_bytes and limit_bytes, either by modeling artifact_size explicitly in the map value type or by widening the value shape used by ResultDiagnosis. Make the change near the ResultDiagnosis definition and keep the rest of the DiagnoseField/DiagnoseEvidenceDisposition-related types unchanged.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/extraction_semantic_surface.toml around lines 2 - 10, The semantic-surface manifest is missing the new contract runtime module, so the ratchet can miss violations in that area. Update the paths list in the semantic-surface config to include the contract runtime symbol under app/core/knowledge_graph, specifically the contract_runtime module, alongside the existing extraction and rules entries. Keep the manifest aligned with the ownership move so future architecture checks cover contract runtime changes.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/divergence.py around lines 65 - 90, With detect_extras enabled, structural top-level data can slip through when lineage is missing because the scalar extra check skips variants, image_url, and additional_images, and _compare_variants/_compare_assets only validate lineage-backed rows. Update divergence detection in divergence.py so _compare_variants() and _compare_assets() also flag any present structural variant/image entries that cannot be matched to an authorized projection entity, even when lineage IDs are absent. Use the existing helpers and call sites around detect_extras, _compare_variants, and _compare_assets to keep the new checks consistent with current divergence findings.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/adapters.py around lines 340 - 350, The comparison in adapters.py is treating an intentionally withheld detail record as a divergence because compare_public_record_to_projection() is still run with an empty candidate when record.url is not publish-authorized. Update the logic around has_url, serialize_commerce_detail_projection(), and compare_public_record_to_projection() so that withheld records are not compared at all, and only authorized serialized projections are checked for PUBLIC_RESOLUTION_DIVERGENCE.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/publication.py around lines 246 - 267, Keep asset IDs aligned with emitted asset URL entries by only adding assets to asset_entity_ids and primary_asset_entity_id when public_asset_delivery_url(asset.url) produces a URL and the corresponding PublicationEntry is emitted. Update the asset collection logic in publication.py so _compare_assets() only receives assets that can actually be serialized, preventing self-divergence; use the existing asset.url, public_asset_delivery_url, and PublicationEntry flow to gate both the URL entry and the ID tracking together.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_resolution_contracts.py around lines 88 - 93, The EvidenceDisposition validation test is too broad because it only asserts any ValidationError and omits required fields, so it would still pass if the status enum changes. Update the test in test_resolution_contracts.py to construct EvidenceDisposition with all required fields and use the status-specific validation path, then assert the exact enum-related failure from the EvidenceDisposition model so the contract stays locked to invalid status values.

[{
	"resource": "/c:/Projects/CrawlerAI/backend/app/crawl/pipeline/persistence.py",
	"owner": "sonarlint",
	"code": "python:S1172",
	"severity": 4,
	"message": "Remove the unused function parameter \"run\".",
	"source": "sonarqube",
	"startLineNumber": 375,
	"startColumn": 5,
	"endLineNumber": 375,
	"endColumn": 18,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/crawl/pipeline/persistence.py",
	"owner": "sonarlint",
	"code": "python:S1172",
	"severity": 4,
	"message": "Remove the unused function parameter \"acquisition_result\".",
	"source": "sonarqube",
	"startLineNumber": 376,
	"startColumn": 5,
	"endLineNumber": 376,
	"endColumn": 23,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/crawl/pipeline/persistence.py",
	"owner": "sonarlint",
	"code": "python:S1172",
	"severity": 4,
	"message": "Remove the unused function parameter \"preliminary_source_url\".",
	"source": "sonarqube",
	"startLineNumber": 377,
	"startColumn": 5,
	"endLineNumber": 377,
	"endColumn": 32,
	"modelVersionId": 1,
	"origin": "extHost1"
}]
[{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S2208",
	"severity": 4,
	"message": "Import only needed names or import the module and then use its members.",
	"source": "sonarqube",
	"startLineNumber": 5,
	"startColumn": 1,
	"endLineNumber": 5,
	"endColumn": 23,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S2208",
	"severity": 4,
	"message": "Import only needed names or import the module and then use its members.",
	"source": "sonarqube",
	"startLineNumber": 6,
	"startColumn": 1,
	"endLineNumber": 6,
	"endColumn": 23,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S2208",
	"severity": 4,
	"message": "Import only needed names or import the module and then use its members.",
	"source": "sonarqube",
	"startLineNumber": 7,
	"startColumn": 1,
	"endLineNumber": 7,
	"endColumn": 23,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S2208",
	"severity": 4,
	"message": "Import only needed names or import the module and then use its members.",
	"source": "sonarqube",
	"startLineNumber": 8,
	"startColumn": 1,
	"endLineNumber": 8,
	"endColumn": 32,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S2208",
	"severity": 4,
	"message": "Import only needed names or import the module and then use its members.",
	"source": "sonarqube",
	"startLineNumber": 9,
	"startColumn": 1,
	"endLineNumber": 9,
	"endColumn": 25,
	"modelVersionId": 1,
	"origin": "extHost1"
},{
	"resource": "/c:/Projects/CrawlerAI/backend/app/core/config/extraction_rules/_listing_structured.py",
	"owner": "sonarlint",
	"code": "python:S1192",
	"severity": 4,
	"message": "Define a constant instead of duplicating this literal \"/category/\" 3 times. [+2 locations]",
	"source": "sonarqube",
	"startLineNumber": 272,
	"startColumn": 5,
	"endLineNumber": 272,
	"endColumn": 17,
	"modelVersionId": 1,
	"origin": "extHost1"
}]