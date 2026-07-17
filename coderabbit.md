Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/browser_readiness.py around lines 540 - 568, Update the successful detail branch in the readiness evaluation flow to set readiness_terminal_state to the terminal value used for ready probes when _detail_readiness_verdict returns true, rather than leaving it as "observing". Apply the same correction to the corresponding detail success path near the additional referenced location, while preserving non-ready detail behavior.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/browser_result_builder.py around lines 706 - 707, Update the readiness fast-finalization branch in the browser result builder so a probe with readiness_terminal_state “ready_empty” returns True only when the page response has a successful HTTP status. Preserve the existing ready_empty behavior for successful responses, while allowing 404 and 5xx results to follow the normal error-handling path.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/cascade.py around lines 40 - 45, Update CASCADE_LISTING_SHELL_PATTERNS to remove the permanent search UI pattern matching “Search jobs”/“Find jobs” and similar search prompts. Retain only transient loading or app-hydration states so valid empty results can reach the ready_empty outcome.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/listing_cards.py around lines 94 - 128, Update ListingCardDiagnostics.from_mapping to safely coerce all persisted numeric fields, including card_count, admitted_count, rejected_count, and each rejection-reasons count. Guard int conversion against malformed or legacy values such as "unknown", falling back to zero, while preserving non-negative clamping and the existing limits and filtering.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/crawl/pipeline/retry/stage.py around lines 186 - 189, Update the profile update condition in the retry stage around browser escalation and the "network_payloads" artifact so the first browser rung also enables CAPTURE_NETWORK_ALL_SMALL_JSON for HTTP-first results. Preserve the existing behavior for subsequent browser attempts and only apply this change when network_payloads is required.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/extraction_semantic_surface.toml at line 29, Remove the duplicate TOML table declarations for the ratchet configuration, including module_physical_loc_budgets and the table at the additionally referenced location, while preserving one declaration of each table and all settings. Validate the file parses successfully with the repository’s configured Python and tomllib.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/persistence/extraction_memory.py around lines 524 - 533, The template-row FOR UPDATE acquisition in persist_learned_recipe must use the same bounded, fail-closed lock-wait strategy as claim_learn_once_template instead of awaiting indefinitely. Reuse the existing timeout mechanism and handle timeout/contention consistently, then add a regression test covering concurrent template or recipe writers and verifying the operation exits within the configured bound.