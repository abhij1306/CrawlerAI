Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/variant_policy.py around lines 454 - 460, The image-dimension artifact check in variant_row_is_image_dimension_artifact only accepts integer strings, so float-like widths such as 800.0 can slip through and still appear sellable via variant_id. Update this helper, and the related transport-only row logic mentioned in the same area, to recognize numeric float-like width values by normalizing/parsing width before the minimum-pixel check, while still rejecting non-numeric and mixed-field rows.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/js_state_scope.py around lines 269 - 285, The root_admits_path helper is fail-open for the unresolved selection state, which lets every path through when no product root is identified. Update root_admits_path so unresolved is handled conservatively like ambiguous, and only admit paths that are explicitly validated by selection-based checks; use the existing root_admits_path, path_is_within_selected_root, and RootSelection status branches to keep the behavior consistent with the documented fail-closed contract.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/js_state_scope.py around lines 256 - 266, The containment check in path_is_within_selected_root only recognizes “/” descendants, so roots like foo.bar or foo[0] are incorrectly rejected even though _path_is_descendant accepts “.”, “[”, and “/”. Update path_is_within_selected_root to use the same descendant rules as _path_is_descendant, preserving the fail-closed behavior while allowing legitimate children of selected roots emitted by the collectors. Keep the fix localized to path_is_within_selected_root and ensure it normalizes and compares roots consistently across all supported separator forms.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/shared/currency_hints.py around lines 44 - 64, The eurozone mapping in currency_hints.py is missing Croatia, so generic currency inference fails for hr storefronts. Update the shared locale-to-currency mapping in the eurozone block to include the hr locale with EUR, keeping the existing pattern used by the other country codes in that dictionary.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/shared/url_utils.py around lines 188 - 192, The doubled-query check in the URL validation logic is happening after percent-decoding, so encoded question marks inside query values can be misread as extra delimiters. Update the guard in the shared URL utility function that builds/validates `candidate` to run on the raw input before `unquote()`, or switch to validating parsed URL components instead of counting literal question marks. Keep the existing rejection behavior for truly malformed doubled-query URLs, but ensure valid URLs with encoded `?` in values are accepted.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/collectors/dom.py around lines 206 - 212, The fallback in dom.py’s candidate filtering is counting raw DOM matches, so a responsive <picture> hero can appear as multiple unscoped candidates and get rejected by the len(candidates) gate. Update the logic around the candidate collection/fail-closed check in the relevant collector function so candidates are collapsed by enclosing <picture> or resolved asset identity before deciding whether to return the fallback. Keep the existing fail-closed behavior for true multi-image galleries, but ensure a single hero image is still accepted even when it is represented by both source[srcset] and img[src].

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/collectors/jsonld.py around lines 44 - 48, The JSON-LD collector is letting standalone variants bypass root scoping in the main loop of collect_product_roots/selection handling. Update the logic around root_admits_path() and _is_standalone_variant so a variant is only emitted when either the variant itself or its isVariantOf target matches the selected root or page URL; otherwise skip it when no page product root was identified. Use the existing symbols select_product_roots, root_admits_path, and _is_standalone_variant to keep the fix localized.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_projection.py around lines 942 - 951, The projection test currently only counts asset.image_url claims, which does not verify they are attached to the product entity. Update the assertion in test_projection.py where asset_claims are loaded with KGClaim and select(KGClaim) so the test also checks each returned KGClaim belongs to prod-1, using the existing asset_claims collection to validate the entity_id or equivalent ownership field instead of just len(asset_claims).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_projection.py around lines 798 - 856, The test in test_projection.py only exercises a single project_extraction_result() call, so it cannot verify that a later re-projection preserves a non-generic selection_origin. Update the test to exercise the real re-projection path by running project_extraction_result() again for the same run_id and url, or by seeding an existing contract row first, then assert the stored contract still keeps the original origin in the projected result.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_diagnose_builder.py around lines 247 - 252, The test for build_diagnosis() only validates a few fields in contract_outcomes, so it can miss regressions in the serialized contract shape. Update the assertions in test_diagnose_builder to verify the full outcome object produced by build_diagnosis(), including selection_origin, selected_source, and the truncation metadata added by this change, using the existing diagnosis["contract_outcomes"] structure and the outcome fields to locate the relevant record.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/selectors/domain-memory/knowledge-graph-tab.tsx around lines 421 - 425, The fallback in knowledge-graph-tab.tsx is incorrectly treating every diagnosis fetch failure as a missing diagnose.json artifact. Update the branch around the diagnosis check in the knowledge graph drill-down so it only shows the “No diagnose artifact persisted” message when the request succeeded but returned no data, and separately surface or pass through real API errors from diagnosis.error (auth/server/network) using the existing diagnosis query/result handling in this component.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/persistence/diagnostics_artifacts.py around lines 45 - 49, The fallback in the artifact readers is too broad and should only treat true missing-artifact cases as a miss. Update the try/except in the diagnose/report JSON loading path in diagnostics_artifacts.py around the artifact read helpers (the read_json calls in the functions that load diagnose.json and report.json) so they catch the storage layer’s exact not-found sentinel from ArtifactRepository.read_json() instead of OSError/ValueError. Let malformed JSON, permission problems, and other read failures propagate, and keep returning None only when the artifact is genuinely absent.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_diagnostics_api.py around lines 24 - 31, The fixture in test_diagnostics_client currently wipes all FastAPI dependency overrides during teardown, which can interfere with other tests. Update the override setup around get_db and get_current_user to save any existing entries, apply only these two overrides, and restore just those keys in a try/finally after the AsyncClient context instead of calling app.dependency_overrides.clear().

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_diagnostics_api.py around lines 210 - 226, The current diagnostics 404 test only covers a missing run ID and does not exercise the access-control-hidden 404 path. Update test_diagnostics_endpoints_404_for_inaccessible_run to create a real crawl owned by a different user, then call the same report.json and diagnose.json endpoints through diagnostics_api_client and assert both still return 404. Use the existing diagnostics_api_client fixture and the crawl/run creation helpers in the test module to target the unauthorized-vs-unauthorized behavior explicitly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/selectors/domain-memory/use-knowledge-graph.ts around lines 35 - 53, The knowledge graph query is swallowing all failures from api.listKnowledgeSites in useKnowledgeGraph, which can leave site metadata null or stale and let mutations proceed with the wrong version context. Update the Promise.all flow so listKnowledgeSites failures are not broadly caught; either let the query fail or only handle a clearly non-fatal “no site” case when resolving site, while keeping the graph and contract fetching logic in useKnowledgeGraph unchanged.