Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/locale_format_rules.py around lines 194 - 202, Add unit coverage for the host-based currency hint logic in _currency_from_host_hint and the new currency_hint_from_page_url_with_scope branch. Create tests that verify exact-host and subdomain matching returns INR for firstcry.com and www.firstcry.com when scope is True, and add a negative case such as notfirstcry.com to confirm the endswith(f".{host}") guard does not produce false positives. Use the existing currency_hint_from_page_url_with_scope helper and _currency_from_host_hint symbol names so the tests clearly target this new path.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/contracts.py around lines 973 - 991, The verdict fields in SentinelObservation are using plain str, which bypasses the strict validation already used elsewhere. Update SentinelObservation to reuse the shared verdict Literal type from ExtractionResult for recipe_verdict and challenger_verdict, so invalid verdict values fail fast before drift/suspension decisions are made. Keep the change localized in the SentinelObservation model and align its annotations with the existing verdict type definition.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/persistence/extraction_memory.py around lines 428 - 465, The snapshot overlay is mutating the ORM-backed payload in place because `_overlay_suspended_templates` edits nested template dicts after only a shallow copy in the snapshot read path. Update the snapshot payload handling in the function that builds the return value and the `_overlay_suspended_templates` helper so the nested `templates` list and its dict items are deep-copied before any status fields are assigned. Add the needed deep-copy import near the top of `extraction_memory.py`, and keep the mutation confined to the local payload returned by the snapshot read logic.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_variant_offer_availability_semantics.py around lines 366 - 370, Add a test that exercises the new complex-number exclusion branch in normalize_availability_value, since current coverage only verifies Number-inclusive cases like Decimal and Fraction. Extend test_variant_offer_availability_semantics.py with a case against normalize_availability_value using a complex value and assert it falls through to the non-stock behavior, so the new not isinstance(value, complex) logic is explicitly covered.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/sentinel.py at line 17, `ChallengerKind` is duplicated in `sentinel.py` and `contracts.py`, which can drift if new challenger kinds are added. Define the type once in `contracts.py` (or another shared location) and reuse it for `SentinelObservation.challenger` and any imports in `sentinel.py`, so both places stay in sync with the same `ChallengerKind` symbol.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/sentinel.py around lines 97 - 133, _record comparison in _disagreement_classes is too positional and _identity is variable-arity, causing false critical_drift on reordered or partially populated records. Update _identity to return a fixed-shape tuple with placeholders for missing fields, then change _disagreement_classes to match recipe_records and challenger_records by identity first (using those tuples) instead of only by index. Preserve positional fallback only for records with no usable identity, and avoid treating length differences alone as record_count drift when they can be explained by unmatched or paginated records.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/sentinel.py around lines 136 - 149, In _state, the final fallback return "needs_review" is unreachable because the earlier conditionals already cover every classes/verdict combination. Remove the dead branch or simplify the branching so the remaining paths in _state are exhaustive and only return reachable SentinelDriftState values.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/sentinel.py around lines 190 - 206, The _normalized helper in sentinel.py is preserving numeric formatting instead of canonicalizing values, and it also leaves plain ints unnormalized. Update _normalized so numeric strings and floats are converted to a consistent numeric type/value form that compares equal across 19.90, 19.9, 3, and 3.0, rather than returning str(Decimal(...)); also add handling for int (and similar numeric scalars) so they normalize the same way as other numeric inputs. Keep the rest of the recursion for list and dict normalization unchanged, and verify the output still feeds _state() and CRITICAL_FIELDS comparisons correctly.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Single-separator money parsing can misinterpret numbers because locale-specific decimal rules were removed.
   Path: backend/app/core/config/locale_format_rules.py
   Lines: 217-217

2. logic error: Removing the currency fallback causes normalization to lose locale context for requests that only have currency metadata.
   Path: backend/app/extraction/adapters.py
   Lines: 151-151

3. incorrect condition logic: Treating sentinel suspension as full template suspension causes valid templates to be skipped during contract matching.
   Path: backend/app/core/extraction_memory/contract_runtime.py
   Lines: 24-24

4. logic error: A surface-wide suspension check incorrectly affects unrelated requests and can disable recipe extraction globally.
   Path: backend/app/extraction/engine.py
   Lines: 104-104

5. security: Unvalidated template identifiers allow sentinel drift reports to suspend templates outside the current extraction context.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 560-560

6. race condition: Concurrent suspension checks can race and apply duplicate or inconsistent suspension transitions.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 570-570

7. performance: Fetching all matching rows to count confirmations causes avoidable unbounded query and memory overhead.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 578-578

8. stale reference: Using a shallow payload copy allows in-place overlay mutations to leak into shared snapshot state.
   Path: backend/app/persistence/extraction_memory.py
   Lines: 430-430

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_extraction_architecture.py around lines 318 - 337, The forbidden-import scan in the AST-based test can miss relative imports because ImportFrom uses node.module without the package prefix. Update the logic in the module-walk inside the extraction architecture test to resolve relative ImportFrom entries to absolute module names before checking against forbidden_prefixes, using the existing _parse_module and _python_files flow so app.connectors.llm and app.evaluation.llm_repair are matched even when imported relatively.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/evaluation/llm_repair.py around lines 102 - 105, The GroundedRepairBatch model currently rejects empty proposal batches because proposals is defined with min_length=1, which conflicts with the system prompt allowing {"proposals": []}. Update the GroundedRepairBatch schema so proposals can be an empty tuple while keeping the existing immutability and extra-forbid settings, and ensure any validation or downstream handling in llm_repair.py still works for the “nothing to fix” case.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/evaluation/llm_repair.py around lines 117 - 129, The _label_payload helper is dropping required proposal metadata, so the GroundedRepairProposal fields custom_field and uncertainty_reason never get persisted. Update _label_payload in llm_repair.py to include these keys when building the payload, and verify the resulting shape is accepted by save_grounded_correction and GroundedLabel so the custom field policy details and rationale flow through end-to-end. If GroundedLabel does not currently allow these fields, adjust its schema/constructor to accept them before wiring the payload through.