# Implementation Plan: listing-product-grid-integrity

## Overview

Incremental build-out of the four architectural controls described in `design.md`:

1. Add all new config first (Runtime_Settings thresholds and Extraction_Rules_Config tokens / export).
2. Introduce the two reusable primitives: the fragment `Structural_Signature` helper and the locale-aware sibling-category extension in `Detail_Identity`.
3. Layer the cohort-aware ranking onto `listing_candidate_ranking` and land the new `Listing_Integrity_Gate` module.
4. Wire the gate into `listing_extractor.py`, propagate the decision through `extraction_runtime.extract_records`, add the new `listing_escalation_decision.py` pure-decision module, then wire the at-most-one retry into `extraction_loop.py`.
5. Cover every universal property from the design with a Hypothesis property test placed in the exact file the design names, plus a regression fixture pair and an architectural-lint test.

Order guarantees no orphaned code: each owner-level task lands after its dependencies, each property test follows the implementation it validates, and the pipeline wiring is last so nothing is integrated until both the gate and the escalator exist.

Property-test tagging convention (per AGENTS.md project note):
```
# Feature: listing-product-grid-integrity, Property {number}: {property_text}
```
Every Hypothesis property test runs a minimum of 100 iterations.

Verify command (from `AGENTS.md`):
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Tasks

- [x] 1. Add config scaffolding for listing integrity controls
  - [x] 1.1 Add numeric thresholds to Runtime_Settings
    - File: `backend/app/services/config/runtime_settings.py`
    - Add `listing_cohort_homogeneity_min_ratio: float = 0.6`
    - Add `listing_integrity_min_records: int = 2`
    - Add `listing_integrity_escalation_enabled: bool = True`
    - Add `listing_integrity_escalation_retry_max_per_run: int = 1`
    - Defaults tuned so the Arcteryx promo cluster is rejected without tripping real low-volume grids
    - Do not introduce any host, domain, brand, or site identifier
    - _Requirements: 5.2, 5.3_

  - [x] 1.2 Add tokens and support-field vocabulary to Extraction_Rules_Config
    - Files: `backend/app/services/config/extraction_rules.py`, `backend/app/services/config/extraction_rules.exports.json`
    - Add `LISTING_LOCALE_PATH_SEGMENT_PATTERN` (regex shape `^[a-z]{2}(?:[_-][a-z]{2})?$`)
    - Add `LISTING_INTEGRITY_SUPPORT_FIELDS` keyed by surface:
      - `ecommerce_listing` → `{image_url, price, rating, review_count, brand}`
      - `job_listing` → `{company, location, salary, job_type}`
    - Confirm `LISTING_CATEGORY_PATH_PREFIXES` covers the `/{locale}/c/` shape via the locale pattern above (no new site-specific token)
    - Export every new constant through `extraction_rules.exports.json` preserving existing naming
    - _Requirements: 2.4, 5.1, 5.3, 5.4, 5.6, 9.2, 9.3_

- [x] 2. Structural_Signature helper in Listing_Card_Fragmenter
  - [x] 2.1 Implement `listing_fragment_structural_signature`
    - File: `backend/app/services/extract/listing_card_fragments.py`
    - Pure function `(node, *, url: str) -> str`; lives next to `listing_node_signature` and reuses it
    - Inputs: tag (lowercased), normalized class/id/role tokens filtered through `LISTING_STRUCTURE_POSITIVE_HINTS` / `LISTING_STRUCTURE_NEGATIVE_HINTS`, descendant shape 4-tuple `(anchor_count_bucket, img_count_bucket, price_signal, title_node_tag)`, URL shape `(category_prefix_bucket, has_detail_marker)`
    - Count buckets `{0, 1, 2_5, 6_plus}`
    - Output format: `"{tag}|{positive_class_bucket}|{anchor_count_bucket}|{img_count_bucket}|{price_signal}|{title_tag}|{url_prefix_bucket}|{has_detail_marker}"`
    - No host, domain, brand, CDN, or site tokens; no I/O
    - _Requirements: 1.1, 5.3, 5.4_

  - [ ]* 2.2 Property test: Structural_Signature determinism and shape-sensitivity
    - File: `backend/tests/services/extract/test_listing_card_fragments_signature.py`
    - **Property 1: Structural signature is deterministic and shape-sensitive**
    - **Validates: Requirements 1.1**
    - Tag with `# Feature: listing-product-grid-integrity, Property 1: Structural signature is deterministic and shape-sensitive`
    - Hypothesis strategies generate shape-tuples; assert equal-input → equal-output and that changing any contributing dimension changes the output
    - Minimum 100 iterations

- [x] 3. Detail_Identity sibling-category extension
  - [x] 3.1 Extend `listing_url_is_structural` with locale-aware sibling match and carve-out
    - File: `backend/app/services/extract/detail_identity.py`
    - Source `LISTING_LOCALE_PATH_SEGMENT_PATTERN`, `LISTING_CATEGORY_PATH_PREFIXES`, and `LISTING_CATEGORY_PATH_SEGMENTS` from `Extraction_Rules_Config` (no literal regex in service code)
    - When leading segment of both URLs matches the locale pattern AND the remaining path shares a `Category_Path_Prefix`, classify the candidate as `Sibling_Category_URL`
    - Preserve existing behavior for shared `Category_Path_Prefix` and `LISTING_CATEGORY_PATH_SEGMENTS` matches
    - Exempt any candidate carrying a `Detail_Identity_Marker` (per `listing_detail_like_path` / `LISTING_PRODUCT_DETAIL_ID_RE`)
    - Carve-out: locale-only shared leading segment (no shared prefix afterwards) must NOT be classified as sibling
    - Inherit existing `urlsplit` exception handling; no host/domain literals
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 5.3, 5.4_

  - [ ]* 3.2 Property tests: sibling-category rejection rules
    - File: `backend/tests/services/extract/test_detail_identity_sibling_category.py`
    - **Property 4: Sibling-category rejection by shared prefix or segment** — Validates Requirements 2.1, 2.2, 2.6
    - **Property 5: Detail_Identity_Marker exempts candidate from prefix-only rejection** — Validates Requirements 2.3
    - **Property 6: Locale-only shared leading segment is not a sibling signal** — Validates Requirements 2.7
    - Tag each test with `# Feature: listing-product-grid-integrity, Property N: <property text>`
    - Minimum 100 iterations per property

- [x] 4. Listing_Candidate_Ranker cohort scoring
  - [x] 4.1 Add cohort-homogeneity ratio and cohort penalty
    - File: `backend/app/services/extract/listing_candidate_ranking.py`
    - Add `_set_cohort_homogeneity(records, *, page_url) -> float` (empty set → 1.0)
    - Add `_set_cohort_penalty(homogeneity, *, threshold) -> int` producing a delta large enough to drop the penalized tuple strictly below the zero-record baseline
    - Extend `_listing_record_quality_metrics` with the ratio (set-level)
    - Extend `_listing_record_set_score` with a top-level `cohort_pass` gate so below-threshold sets score strictly less than the empty set
    - Add optional `diagnostics_sink: list[dict] | None = None` kwarg to `best_listing_candidate_set`; when the penalty applies, append `cohort_penalty_applied` with `{set_name, record_count, dominant_signature_count, cohort_homogeneity_ratio}`
    - Preserve existing utility-record rejection, editorial-URL rejection, and detail-like-merchandise logic (extend, do not duplicate)
    - Read the threshold only from `Runtime_Settings.listing_cohort_homogeneity_min_ratio`; no host/domain literals; no site-specific tokens
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 5.3, 5.4, 7.3, 8.1_

  - [ ]* 4.2 Property tests: cohort ratio, cohort penalty, and diagnostic retention
    - File: `backend/tests/services/extract/test_listing_candidate_ranking_cohort.py`
    - **Property 2: Cohort-homogeneity ratio equals dominant-signature fraction** — Validates Requirements 1.2
    - **Property 3: Heterogeneous below-threshold set never outranks zero-record set** — Validates Requirements 1.3, 1.4
    - **Property 13: Diagnostic retention preserves set-level and gate-level decisions independently** — Validates Requirements 8.1, 8.2, 8.4, 8.5
    - Tag each test with `# Feature: listing-product-grid-integrity, Property N: <property text>`
    - Minimum 100 iterations per property

- [x] 5. Listing_Integrity_Gate module
  - [x] 5.1 Implement `evaluate_listing_integrity` with `IntegrityDecision`
    - File (NEW): `backend/app/services/extract/listing_integrity_gate.py`
    - `@dataclass(frozen=True) class IntegrityDecision` with fields `outcome`, `reason`, `metrics: dict[str, int | float]`
    - Single entry point `evaluate_listing_integrity(records, *, page_url, surface) -> IntegrityDecision`; pure function, no I/O, no list/element mutation
    - Priority-ordered rules (first match wins; remaining still fill metrics):
      1. `len(records) < listing_integrity_min_records` → `promo_only_cluster` / `below_min_records`
      2. cohort-homogeneity ratio `< listing_cohort_homogeneity_min_ratio` → `cohort_heterogeneous`
      3. every record URL is a `Sibling_Category_URL` of `page_url` → `all_sibling_category_urls`
      4. zero `Detail_Identity_Marker` records AND zero support signals for the active surface → `no_support_signals`
      5. otherwise → `product_grid` / `supported_set`
    - `metrics` always populated: `record_count`, `cohort_homogeneity_ratio`, `dominant_signature_count`, `sibling_category_count`, `support_signal_count`, `detail_marker_count`
    - Support-signal vocabulary comes from `Extraction_Rules_Config.LISTING_INTEGRITY_SUPPORT_FIELDS` keyed by surface (shared with `listing_candidate_ranking._record_has_supporting_listing_signals`; no duplication)
    - No imports from `publish/`, `pipeline/persistence.py`, `pipeline/direct_record_fallback.py`, `detail_extractor.py`, adapters, or any export path
    - No host/domain/brand/CDN literals; no LLM imports
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 3.8, 3.9, 5.1, 5.3, 5.4, 6.5, 7.1, 9.1, 9.2, 9.3_

  - [ ]* 5.2 Property tests: gate truth table, non-mutation, cross-surface uniformity
    - File: `backend/tests/services/extract/test_listing_integrity_gate.py`
    - **Property 7: Gate decision truth table matches documented rules** — Validates Requirements 3.2, 3.3, 3.4, 3.5, 3.9
    - **Property 8: Gate is non-mutating** — Validates Requirements 3.7
    - **Property 15: Cross-surface uniformity on equivalent inputs** — Validates Requirements 9.1, 9.2, 9.3, 9.4, 9.5
    - Tag each test with `# Feature: listing-product-grid-integrity, Property N: <property text>`
    - Minimum 100 iterations per property

- [x] 6. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Wire gate into Listing_Extractor
  - [x] 7.1 Invoke `evaluate_listing_integrity` after `best_listing_candidate_set`
    - File: `backend/app/services/listing_extractor.py`
    - After ranking, call `evaluate_listing_integrity(best_records, page_url=page_url, surface=surface)`
    - Attach the `IntegrityDecision` to artifacts via a local `_attach_gate_decision_to_artifacts` helper (set under key `listing_integrity`)
    - When outcome is `promo_only_cluster`, return `[]` with the decision attached (Requirement 7.5: do NOT fall back to single-record detail behavior)
    - When outcome is `product_grid`, return `best_records` with the decision attached
    - Do not mutate records; do not modify user-controlled run settings
    - _Requirements: 3.6, 3.7, 6.1, 6.5, 7.4, 7.5, 8.4_

- [x] 8. Propagate gate decision through `extract_records`
  - [x] 8.1 Carry the decision on `acquisition_result.browser_diagnostics`
    - File: `backend/app/services/extraction_runtime.py`
    - Thread the `IntegrityDecision` attached by `listing_extractor` onto the existing `acquisition_result.browser_diagnostics` channel under key `listing_integrity`
    - Do NOT attach to individual records (INVARIANTS Rule 8)
    - On a retry that produces a new decision, move the prior decision to `listing_integrity.previous` and write the new one to `listing_integrity` so both are auditable across retries
    - _Requirements: 8.1, 8.2, 8.4, 8.5_

- [x] 9. Acquisition_Escalator decision module
  - [x] 9.1 Implement `listing_integrity_escalation_decision`
    - File (NEW): `backend/app/services/pipeline/listing_escalation_decision.py`
    - Mirror the contract shape of `pipeline/extraction_retry_decision.low_quality_extraction_browser_retry_decision`: a pure decision function, no I/O, no mutation of inputs
    - Signature: `(acquisition_result, *, gate_decision, surface, retry_state, policy_snapshot) -> dict`
    - Return payload: `{should_retry, reason, prior_tier, next_tier, gate_reason, candidate_summary}` where `candidate_summary` is `{record_count, cohort_homogeneity_ratio, sibling_category_count, support_signal_count}`
    - Skip rules (in order): `not_listing_surface`, `gate_ok`, `already_retried`, `blocked`, `challenge_state`, `escalation_disabled`, `host_hard_block`, `no_stronger_tier`
    - Reuse `effective_blocked` from `pipeline.runtime_helpers`, `real_chrome_browser_available` from `acquisition.browser_runtime`, and the `AcquisitionPolicy` snapshot constructor
    - Tier escalation map:
      - `curl_cffi` / `httpx` → `browser:chromium`
      - `browser:patchright` (when real Chrome available) → `browser:real_chrome`
      - `browser:chromium` (when real Chrome available) → `browser:real_chrome`
      - otherwise → skip with `no_stronger_tier`
    - Source every threshold from `Runtime_Settings`; no host/domain/brand/CDN literals
    - Do not modify user-controlled `surface`, `llm_enabled`, traversal intent, proxy, or diagnostics-capture settings
    - No imports from `detail_extractor.py`, `publish/`, `pipeline/persistence.py`, `pipeline/direct_record_fallback.py`, or any LLM entry point
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7, 4.8, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 7.2, 8.3_

  - [ ]* 9.2 Property tests: escalator purity and diagnostic contract shape
    - File: `backend/tests/services/pipeline/test_listing_escalation_decision.py`
    - **Property 10: Escalator decision is a pure function of gate, tier, and policy** — Validates Requirements 4.1, 4.2, 4.3
    - **Property 14: Diagnostic payload shape for escalation events matches the acquisition diagnostics contract** — Validates Requirements 4.4, 8.3
    - Tag each test with `# Feature: listing-product-grid-integrity, Property N: <property text>`
    - Minimum 100 iterations per property

- [x] 10. Wire escalator and retry into `extraction_loop`
  - [x] 10.1 Add `_retry_listing_integrity_with_stronger_tier` between extraction and persistence
    - File: `backend/app/services/pipeline/extraction_loop.py`
    - Between `_retry_low_quality_extraction_with_browser` and persistence, invoke a new `_retry_listing_integrity_with_stronger_tier(context, fetched, records, selector_rules)` for listing surfaces only
    - That helper calls `listing_integrity_escalation_decision` with a `policy_snapshot` derived from `AcquisitionPolicy` and a `retry_state` read from `URLProcessingContext.listing_integrity_retry_count` (new int field, default 0)
    - On `should_retry=True`:
      - Reuse existing budget guard (`_remaining_url_budget_seconds` / `_browser_retry_min_remaining_seconds`); on budget-exhausted skip, emit `listing_escalation_skipped` with reason `budget_exhausted`
      - Call `_acquire_browser_retry_result(retry_reason="listing_integrity_promo_cluster", forced_browser_engine=<next_tier>)`
      - Increment `context.listing_integrity_retry_count` before the retry (enforces at-most-one per URL per run regardless of the retried gate outcome)
      - Re-run `_extract_records_for_acquisition` on the new observation so both the Ranker and Gate re-evaluate
    - On `should_retry=False`: emit `listing_escalation_skipped` with the returned reason and leave records unchanged
    - Log events through `_log_pipeline_event` using `listing_escalation_triggered` / `listing_escalation_skipped` with `prior_tier`, `next_tier`, `gate_reason`, `candidate_summary`
    - When final gate outcome is `promo_only_cluster` and records are empty, set `failure_reason="promo_only_cluster"` on the URL result and expose `url_metrics.listing_integrity = decision`
    - Do NOT modify `surface`, `llm_enabled`, traversal intent, proxy, or diagnostics-capture settings
    - Do NOT invoke any LLM entry point
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 6.1, 6.2, 6.3, 6.4, 6.5, 7.2, 8.3, 8.4_

  - [x]* 10.2 Integration property tests for gate + escalator pipeline wiring
    - File: `backend/tests/services/pipeline/test_listing_integrity_pipeline.py`
    - **Property 9: Zero-record listing verdict is consistent across all triggers** — Validates Requirements 3.6, 7.4, 7.5
    - **Property 11: At most one listing-quality retry per URL per run** — Validates Requirements 4.5, 4.6
    - **Property 12: Gate and Escalator do not mutate user controls and never call LLM when disabled** — Validates Requirements 4.7, 6.1, 6.2, 6.3, 6.4, 6.5
    - Use a stubbed `acquisition_result` and stubbed `_acquire_browser_retry_result`; drive state with Hypothesis strategies over gate outcomes and run settings
    - Tag each test with `# Feature: listing-product-grid-integrity, Property N: <property text>`
    - Minimum 100 iterations per property

- [ ] 11. Regression fixtures and architectural lint
  - [ ]* 11.1 Regression fixtures: promo-only cluster and healthy product grid
    - File (NEW): `backend/tests/services/extract/test_listing_integrity_regressions.py`
    - Case A (Arcteryx-like): three sibling-category tiles under `/ca/en/c/...` → gate returns `promo_only_cluster` with `reason="all_sibling_category_urls"`; `listing_extractor` returns `[]`; pipeline emits `VERDICT_LISTING_FAILED` with `failure_reason="promo_only_cluster"`
    - Case B (healthy grid): ≥ 20 homogeneous product cards bearing `Detail_Identity_Marker` and price → gate returns `product_grid`; pre-existing verdict behavior unchanged
    - Together these protect against over- and under-rejection
    - _Requirements: 3.4, 3.6, 3.9, 7.3, 7.4, 7.5_

  - [ ]* 11.2 Architectural lint test for new modules and config placement
    - File (NEW): `backend/tests/services/test_listing_integrity_architecture.py`
    - Assert `listing_integrity_gate.py` and `listing_escalation_decision.py` contain NO literal host name, domain, brand, CDN, or site identifier (static scan for a curated deny-list plus generic patterns)
    - Assert neither module imports from `publish/`, `pipeline/persistence.py`, `pipeline/direct_record_fallback.py`, `detail_extractor.py`, adapter modules, or any export path
    - Assert neither module imports `llm_runtime` or any LLM entry point
    - Assert every new token added in task 1.2 appears in `extraction_rules.exports.json`
    - Assert every new numeric threshold lives on `Runtime_Settings` (no hardcoded threshold literal outside `app/services/config/`)
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 6.5, 7.1, 7.2_

- [x] 12. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never marked optional.
- Each task cites the exact files named in `design.md` and the granular requirements it implements.
- Property tests are placed in the files named under `design.md` §Testing Strategy → Test File Locations.
- Every Hypothesis property test carries the feature-tag comment required by the project convention and runs a minimum of 100 iterations.
- The regression fixture pair in task 11.1 anchors both the Arcteryx failure mode and a healthy-grid baseline so the gate cannot silently over-reject.
- Config lives exclusively under `app/services/config/*` (INVARIANTS Rule 1); task 11.2 enforces that statically.
- Tasks 1.1 and 1.2 are already complete; the dependency graph below covers only incomplete leaf tasks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "3.1"] },
    { "id": 1, "tasks": ["2.2", "3.2", "4.1", "5.1"] },
    { "id": 2, "tasks": ["4.2", "5.2", "7.1", "9.1"] },
    { "id": 3, "tasks": ["8.1", "9.2"] },
    { "id": 4, "tasks": ["10.1"] },
    { "id": 5, "tasks": ["10.2", "11.1", "11.2"] }
  ]
}
```
