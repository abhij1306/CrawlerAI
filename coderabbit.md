Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/engine.py around lines 762 - 766, Guard the document load in the shell-detection path around _is_semantic_detail_shell, matching _ground_detail_dom by catching KeyError and ValueError from request.artifact_reader.document_store.html. On failure, fall back without aborting classification or extraction, while preserving the existing classify_blocked_page behavior for successfully loaded documents.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/result_building.py around lines 521 - 547, Update _captured_variant_dom_cues to defensively retrieve the HTML document: handle document_store.html returning None or raising a lookup/retrieval exception, and return False in those cases. Preserve the existing artifact selection and DOM cue detection behavior when a valid document is available.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/result_building.py around lines 533 - 547, Update the select-detection logic around the enclosing any expression to avoid unbounded ancestor traversal: cache select.parent() in a local variable, then limit the parent content_text() examined (for example, to 200 characters) while preserving the existing token matching and option-count behavior.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/observability/diagnose.py at line 257, Update the discovery stage construction around the row-stage mapping so discovery_stages[].detail uses the existing _preview(...) helper on the row’s detail value instead of always returning None, matching execution.detail and binding_outcomes[].detail while preserving the existing stage and outcome fields.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_llm_repair_gating.py around lines 137 - 138, Extend the test around the recipe-v2 compilation call to query the persistence layer’s legacy correction/operator-label table and assert that no matching row exists. Keep the existing result["correction_id"] is None assertion as the API-level check, and use the test’s established database session and identifying values to scope the query.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_crawl_run_2_regressions.py around lines 434 - 435, Update the regression test around result.records[0] to preserve the documented EXPECTED_VARIANT_AXIS_MISSING coverage: assert the completeness finding is present and verify its axis metadata. If the behavior is intentionally changing, instead update the test contract and docstring to explicitly document that change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/alembic/versions/20260713_0004_compiled_recipe_compiler_version.py around lines 35 - 45, Update downgrade() to handle rows that would violate the restored unique (recipe_id, checksum) index, either by explicitly detecting and rejecting such data with a clear error before recreating the index or by applying the migration’s established cleanup policy. Ensure the downgrade does not reach op.create_index("uq_compiled_extraction_recipes_checksum", ...) while duplicate keys remain.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_recipe_executor.py around lines 322 - 331, Extract the duplicated import-collection logic from the test containing this AST parsing block and test_recipe_contracts.py into a shared test helper. Implement the helper with a clear plain loop handling Import and ImportFrom nodes, then update both callers to reuse it without changing the collected module names.

 FAILURES ==================================
__________ test_extraction_package_stays_within_architecture_limits __________
tests\unit\test_extraction_architecture.py:235: in test_extraction_package_stays_within_architecture_limits
    assert _physical_line_count(path) <= module_loc_budgets[relative_path], path
E   AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extraction/engine.py')
E   assert 786 <= 725
E    +  where 786 = _physical_line_count(WindowsPath('C:/Projects/CrawlerAI/backend/app/extraction/engine.py'))
____________ test_extraction_semantic_surface_manifest_is_current ____________
tests\unit\test_extraction_architecture.py:547: in test_extraction_semantic_surface_manifest_is_current
    assert ratchets["physical_loc_budget"] >= sum(
E   AssertionError: assert 19170 >= 19520
E    +  where 19520 = sum(dict_values([100, 500, 300, 1350, 1000, 850, 250, 200, 950, 300, 725, 1000, 450, 550, 150, 500, 360, 450, 550, 240, 800, 700, 450, 450, 425, 200, 100, 300, 400, 2000, 350, 250, 200, 750, 220, 350, 800]))
E    +    where dict_values([100, 500, 300, 1350, 1000, 850, 250, 200, 950, 300, 725, 1000, 450, 550, 150, 500, 360, 450, 550, 240, 800, 700, 450, 450, 425, 200, 100, 300, 400, 2000, 350, 250, 200, 750, 220, 350, 800]) = <built-in method values of dict object at 0x0000027E97140800>()
E    +      where <built-in method values of dict object at 0x0000027E97140800> = {'__init__.py': 100, 'adapters.py': 500, 'collectors/_helpers.py': 300, 'collectors/dom.py': 1350, ...}.values
_ test_page_identity_replaces_known_weak_or_partial_brand_shapes[https://ar.puma.com/pd/zapatillas-mostro/397328.html-Zapatillas Mostro Ecstasy unisex-PUMA Mostro heritage sneaker.-https://images.puma.com/397328.png-green-PUMA] _
tests\unit\test_extraction_contract_behavior.py:674: in test_page_identity_replaces_known_weak_or_partial_brand_shapes
    assert result.records[0]["brand"].casefold() == expected.casefold()
E   AssertionError: assert 'ar' == 'puma'
E     
E     - puma
E     + ar
_ test_page_identity_replaces_known_weak_or_partial_brand_shapes[https://www.lego.com/product/millennium-falcon-75192-Millennium Falcon-Travel the LEGO galaxy.-https://www.lego.com/images/75192.png-Millennium Falcon-Lego] _
tests\unit\test_extraction_contract_behavior.py:674: in test_page_identity_replaces_known_weak_or_partial_brand_shapes
    assert result.records[0]["brand"].casefold() == expected.casefold()
E   AssertionError: assert 'www' == 'lego'
E     
E     - lego
E     + www
___________ test_internal_brand_hierarchy_materializes_leaf_brand ____________
tests\unit\test_extraction_js_state_behavior.py:1112: in test_internal_brand_hierarchy_materializes_leaf_brand
    assert result.records[0]["brand"] == "Breville"
E   AssertionError: assert 'breville' == 'Breville'
E     
E     - Breville
E     ? ^
E     + breville
E     ? ^
________ test_zero_decimal_currency_explicit_minor_key_is_not_divided ________
tests\unit\test_extraction_runtime_behavior.py:848: in test_zero_decimal_currency_explicit_minor_key_is_not_divided
    assert result.records[0]["price"] == "13875.00"
E   AssertionError: assert '138.75' == '13875.00'
E     
E     - 13875.00
E     + 138.75
_____ test_same_offer_formatted_price_corroborates_raw_minor_unit_price ______
tests\unit\test_extraction_runtime_behavior.py:1137: in test_same_offer_formatted_price_corroborates_raw_minor_unit_price
    assert result.records[0]["price"] == "215.00"
E   AssertionError: assert '2.15' == '215.00'
E     
E     - 215.00
E     + 2.15
_____ test_parent_mixed_variant_prices_publish_explicit_range_semantics ______
tests\unit\test_extraction_surface_behavior.py:498: in test_parent_mixed_variant_prices_publish_explicit_range_semantics
    assert record["price_min"] == "20.00"
E   AssertionError: assert '25.00' == '20.00'
E     
E     - 20.00
E     ?  ^
E     + 25.00
E     ?  ^
_______ test_variant_price_range_materializes_lowest_price_and_bounds ________
tests\unit\test_extraction_validation_behavior.py:81: in test_variant_price_range_materializes_lowest_price_and_bounds
    assert record["price"] == "20.00"
E   AssertionError: assert '24.00' == '20.00'
E     
E     - 20.00
E     ?  ^
E     + 24.00
E     ?  ^
____________________ test_production_package_loc_budgets _____________________
tests\unit\test_final_architecture_ownership.py:166: in test_production_package_loc_budgets
    assert sum(_physical_line_count(path) for path in app_files) <= TOTAL_APP_LOC_BUDGET
E   assert 85737 <= 85369
E    +  where 85737 = sum(<generator object test_production_package_loc_budgets.<locals>.<genexpr> at 0x0000027EA217ADC0>)
_______________________ test_no_new_oversized_modules ________________________
tests\unit\test_final_architecture_ownership.py:183: in test_no_new_oversized_modules
    assert oversized.keys() == OVERSIZED_MODULE_DEBT.keys()
E   AssertionError: assert dict_keys(['a.../_detail.py']) == dict_keys(['a...n_memory.py'])
E     
E     Full diff:
E     - dict_keys(['acquisition/browser_capture.py', 'acquisition/browser_recovery.py', 'acquisition/browser_result_builder.py', 'core/config/extraction_rules/_detail.py', 'enrichment/service.py', 'extraction/collectors/js_state.py', 'extraction/collectors/jsonld.py', 'extraction/collectors/dom.py', 'extraction/contracts.py', 'extraction/engine.py', 'extraction/entities.py', 'extraction/pipeline.py', 'extraction/resolution/__init__.py', 'extraction/validation.py', 'persistence/extraction_memory.py'])
E     + dict_keys(['acquisition/...
E     
E     ...Full output truncated (1 line hidden), use '-vv' to show
_______________________ test_no_new_complex_functions ________________________
tests\unit\test_final_architecture_ownership.py:196: in test_no_new_complex_functions
    assert complex_functions.keys() == COMPLEX_FUNCTION_DEBT.keys()
E   AssertionError: assert dict_keys([('...lize_value')]) == dict_keys([('...rl_metrics')])
E     
E     Full diff:
E     - dict_keys([('acquisition/browser_block_detection.py', '_block_policy_matches'), ('acquisition/browser_capture.py', '_repair_truncated_json_prefix'), ('acquisition/browser_detail.py', '_candidate_is_admitted'), ('acquisition/browser_identity.py', 'build_playwright_context_spec'), ('acquisition/browser_listing_visual.py', 'listing_visual_elements_html'), ('acquisition/browser_page_helpers.py', '_select_primary_browser_html'), ('acquisition/browser_readiness.py', 'analyze_extractable_content'), ('acquisition/browser_readiness.py', 'probe_browser_readin...
E     
E     ...Full output truncated (2 lines hidden), use '-vv' to show
========================== short test summary info ===========================
SKIPPED [1] tests\unit\test_extraction_v3_representation.py:102: frozen run corpus is not present
SKIPPED [1] tests\unit\test_extraction_v3_representation.py:127: frozen run corpus is not present
FAILED tests/unit/test_extraction_architecture.py::test_extraction_package_stays_within_architecture_limits - AssertionError: WindowsPath('C:/Projects/CrawlerAI/backend/app/extraction/...
FAILED tests/unit/test_extraction_architecture.py::test_extraction_semantic_surface_manifest_is_current - AssertionError: assert 19170 >= 19520
FAILED tests/unit/test_extraction_contract_behavior.py::test_page_identity_replaces_known_weak_or_partial_brand_shapes[https://ar.puma.com/pd/zapatillas-mostro/397328.html-Zapatillas Mostro Ecstasy unisex-PUMA Mostro heritage sneaker.-https://images.puma.com/397328.png-green-PUMA] - AssertionError: assert 'ar' == 'puma'
FAILED tests/unit/test_extraction_contract_behavior.py::test_page_identity_replaces_known_weak_or_partial_brand_shapes[https://www.lego.com/product/millennium-falcon-75192-Millennium Falcon-Travel the LEGO galaxy.-https://www.lego.com/images/75192.png-Millennium Falcon-Lego] - AssertionError: assert 'www' == 'lego'
FAILED tests/unit/test_extraction_js_state_behavior.py::test_internal_brand_hierarchy_materializes_leaf_brand - AssertionError: assert 'breville' == 'Breville'
FAILED tests/unit/test_extraction_runtime_behavior.py::test_zero_decimal_currency_explicit_minor_key_is_not_divided - AssertionError: assert '138.75' == '13875.00'
FAILED tests/unit/test_extraction_runtime_behavior.py::test_same_offer_formatted_price_corroborates_raw_minor_unit_price - AssertionError: assert '2.15' == '215.00'
FAILED tests/unit/test_extraction_surface_behavior.py::test_parent_mixed_variant_prices_publish_explicit_range_semantics - AssertionError: assert '25.00' == '20.00'
FAILED tests/unit/test_extraction_validation_behavior.py::test_variant_price_range_materializes_lowest_price_and_bounds - AssertionError: assert '24.00' == '20.00'
FAILED tests/unit/test_final_architecture_ownership.py::test_production_package_loc_budgets - assert 85737 <= 85369
FAILED tests/unit/test_final_architecture_ownership.py::test_no_new_oversized_modules - AssertionError: assert dict_keys(['a.../_detail.py']) == dict_keys(['a...n...
FAILED tests/unit/test_final_architecture_ownership.py::test_no_new_complex_functions - AssertionError: assert dict_keys([('...lize_value')]) == dict_keys([('...r...
=========== 12 failed, 1682 passed, 2 skipped in 237.82s (0:03:57) ===========
PS C:\Projects\CrawlerAI\backend> 