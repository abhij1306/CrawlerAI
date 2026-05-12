# Requirements Document

## Introduction

The listing extractor currently admits heterogeneous promo/hero sibling-category tiles as if they were product-grid rows. On Arcteryx category pages the extractor returns three marketing tiles that link to sibling categories under `/ca/en/c/...` while the actual product grid is ignored. This produces a fake listing success instead of `listing_detection_failed`, violates INVARIANTS Rule 7, and silently misses every real product link on the page.

This feature adds four architectural controls that together prevent that class of failure without site-specific branches:

1. A grid-cohort (cluster-homogeneity) signal in listing candidate ranking, so a heterogeneous promo cluster cannot outrank either a real product grid or the empty set.
2. A generalized same-path-prefix sibling-category rejection in listing URL structural classification, driven entirely by config knobs.
3. A listing-integrity gate that decides, for each accepted candidate set, whether the set represents a product grid or a promo-only cluster, and emits `listing_detection_failed` with a `promo_only_cluster` diagnostic when appropriate.
4. A listing-side acquisition escalation hook that, mirroring the existing detail field-aware retry contract, triggers at most one logged stronger-tier retry when the integrity gate flags `promo_only_cluster` and a stronger acquisition tier is available.

All changes are generic-first across `ecommerce_listing` and `job_listing`, preserve existing user-control ownership, and keep every new token/threshold/selector under `app/services/config/`.

## Glossary

- **Listing_Extractor**: Listing record owner at `backend/app/services/listing_extractor.py`. Produces the candidate sets consumed by the ranker and the integrity gate, including `_listing_record_from_card` and `extract_listing_records`.
- **Listing_Candidate_Ranker**: Candidate-set scorer at `backend/app/services/extract/listing_candidate_ranking.py`. Owns `best_listing_candidate_set`, `_listing_record_set_score`, and `_listing_record_quality_metrics`.
- **Listing_Card_Fragmenter**: Listing-fragment discovery at `backend/app/services/extract/listing_card_fragments.py`. Owns `base_listing_fragment_score` and the fallback container scan driven by `LISTING_FALLBACK_CONTAINER_SELECTOR` and `LISTING_STRUCTURE_POSITIVE_HINTS`.
- **Detail_Identity**: Detail/listing URL identity classifier at `backend/app/services/extract/detail_identity.py`. Owns `listing_url_is_structural` and `listing_detail_like_path`.
- **Listing_Integrity_Gate**: New owner placed under `backend/app/services/extract/`. Consumes the ranked listing candidate set plus page context and returns either `product_grid` or `promo_only_cluster` with a structured diagnostic. No other module may inline this decision.
- **Acquisition_Escalator**: Acquisition-side owner (final file placement to be confirmed at design; candidate is `backend/app/services/crawl_fetch_runtime.py` or `backend/app/services/pipeline/extraction_retry_decision.py`) of the listing-quality retry contract. Triggers at most one stronger-tier listing acquisition when the gate flags `promo_only_cluster` and a stronger tier is available under existing policy.
- **Extraction_Rules_Config**: Config owner at `backend/app/services/config/extraction_rules.py` and `extraction_rules.exports.json`. Owns `LISTING_CATEGORY_PATH_SEGMENTS`, `LISTING_CATEGORY_PATH_PREFIXES`, `LISTING_STRUCTURE_POSITIVE_HINTS`, `LISTING_FALLBACK_CONTAINER_SELECTOR`, and all new tokens/thresholds introduced by this feature.
- **Runtime_Settings**: Runtime tunables at `backend/app/services/config/runtime_settings.py`. Owns numeric thresholds including `listing_candidate_strong_score_threshold` and any new thresholds introduced for cohort scoring and integrity gating.
- **Detail_Identity_Marker**: Evidence that a URL identifies a product-detail/job-posting page, as already defined by `listing_detail_like_path` and `LISTING_PRODUCT_DETAIL_ID_RE` under `Extraction_Rules_Config`. No host or site-specific marker is introduced.
- **Category_Path_Prefix**: A config-owned URL path prefix under `Extraction_Rules_Config.LISTING_CATEGORY_PATH_PREFIXES` (for example `/c/`, `/category/`, `/collections/`) that identifies a category-style listing path shape.
- **Sibling_Category_URL**: A URL that shares the same `Category_Path_Prefix` as the page URL, points at a different category path under that prefix, and carries no `Detail_Identity_Marker`.
- **Structural_Signature**: A deterministic fingerprint derived by `Listing_Card_Fragmenter` from a listing fragment's tag, class/id/role tokens, descendant-shape summary, and URL shape. Used to compare fragments inside a candidate set.
- **Grid_Cohort**: A candidate set whose records share a dominant `Structural_Signature`. Quantified by the cohort-homogeneity ratio (records sharing the dominant signature divided by total records).
- **Promo_Only_Cluster**: A candidate set that is rejected by `Listing_Integrity_Gate` because it fails grid-cohort and/or sibling-category checks and therefore does not represent a product grid.
- **Listing_Surface**: One of the generic listing surfaces `ecommerce_listing` or `job_listing`. All requirements below apply generically to both unless explicitly scoped.
- **listing_detection_failed**: The existing verdict defined in `backend/app/services/publish/verdict.py` that is produced when a listing run yields zero supported records. This feature extends the conditions under which that verdict is emitted.
- **Stronger_Acquisition_Tier**: An acquisition tier that provides more rendered evidence than the current fetch, as already defined by acquisition policy (for example rendered browser after static HTTP, or real Chrome after Patchright), without bypassing block/challenge/session policy.

## Requirements

### Requirement 1: Grid-Cohort Homogeneity In Candidate Ranking

**User Story:** As a crawler operator running a listing crawl, I want heterogeneous promo/hero clusters to never outrank either a real product grid or the empty set, so that the extractor cannot declare a fake listing success built from marketing tiles.

#### Acceptance Criteria

1. THE Listing_Card_Fragmenter SHALL compute a Structural_Signature for every listing fragment it admits, using only fragment-local DOM features and URL shape defined in Extraction_Rules_Config.
2. THE Listing_Candidate_Ranker SHALL compute a cohort-homogeneity ratio for each candidate set as the fraction of records sharing the dominant Structural_Signature.
3. WHERE the cohort-homogeneity ratio is below the `listing_cohort_homogeneity_min_ratio` threshold owned by Runtime_Settings, THE Listing_Candidate_Ranker SHALL apply a cohort penalty to `_listing_record_set_score` such that the penalized set score is strictly less than the score of a zero-record set.
4. WHEN two candidate sets are compared by `best_listing_candidate_set`, THE Listing_Candidate_Ranker SHALL select the set with the higher penalized score, treating the zero-record set as a legitimate candidate.
5. THE Listing_Candidate_Ranker SHALL emit a structured diagnostic entry `cohort_penalty_applied` containing the set name, record count, dominant signature count, and cohort-homogeneity ratio whenever the cohort penalty is applied.
6. THE Listing_Candidate_Ranker SHALL NOT read any host, domain, or site-specific token when computing the cohort-homogeneity ratio or the cohort penalty.

### Requirement 2: Generalized Sibling-Category Rejection In Detail_Identity

**User Story:** As a crawler operator, I want same-path-prefix sibling-category links to be rejected as structural on any site shape, so that listing extraction stops admitting category-nav tiles as products without relying on hardcoded path shapes.

#### Acceptance Criteria

1. THE Detail_Identity SHALL treat a candidate URL as structural when the candidate URL and the page URL share any Category_Path_Prefix defined in Extraction_Rules_Config and the candidate URL carries no Detail_Identity_Marker.
2. THE Detail_Identity SHALL treat a candidate URL as structural when the candidate URL and the page URL share a path segment listed in Extraction_Rules_Config.LISTING_CATEGORY_PATH_SEGMENTS and the candidate URL carries no Detail_Identity_Marker.
3. WHERE a candidate URL carries a Detail_Identity_Marker, THE Detail_Identity SHALL NOT treat the candidate URL as structural solely on the basis of a shared Category_Path_Prefix.
4. THE Extraction_Rules_Config SHALL extend `LISTING_CATEGORY_PATH_PREFIXES` to cover path shapes of the form `/{locale}/c/` and `/c/` without introducing any host, domain, brand, or site-specific identifier.
5. THE Detail_Identity SHALL NOT read any host, domain, or site-specific token when evaluating sibling-category structural rejection.
6. WHEN `listing_url_is_structural(candidate, page_url)` evaluates a Sibling_Category_URL, THE Detail_Identity SHALL return True.
7. IF a candidate URL shares only a leading locale segment with the page URL and shares no Category_Path_Prefix, THEN THE Detail_Identity SHALL NOT treat that candidate URL as a Sibling_Category_URL solely on the locale segment.

### Requirement 3: Listing Integrity Gate Owns Product-Grid Vs Promo-Cluster Decision

**User Story:** As a crawler operator, I want a single, testable owner to decide whether a listing candidate set represents a real product grid or a promo-only cluster, so that fake successes are replaced by an honest `listing_detection_failed` verdict with a structured diagnostic.

#### Acceptance Criteria

1. THE Listing_Integrity_Gate SHALL expose a single entry point that accepts the ranked candidate set, the page URL, and the Listing_Surface and returns one of exactly two outcomes: `product_grid` or `promo_only_cluster`.
2. WHEN the candidate set has fewer records than the `listing_integrity_min_records` threshold owned by Runtime_Settings, THE Listing_Integrity_Gate SHALL return `promo_only_cluster`.
3. WHEN the cohort-homogeneity ratio computed in Requirement 1 is below `listing_cohort_homogeneity_min_ratio`, THE Listing_Integrity_Gate SHALL return `promo_only_cluster`.
4. WHEN every record URL in the candidate set is a Sibling_Category_URL of the page URL per Requirement 2, THE Listing_Integrity_Gate SHALL return `promo_only_cluster`.
5. WHEN the candidate set contains zero records carrying a Detail_Identity_Marker and zero records with price, rating, review_count, salary, or other listing support signals as defined by `listing_record_supported`, THE Listing_Integrity_Gate SHALL return `promo_only_cluster`.
6. WHEN the Listing_Integrity_Gate returns `promo_only_cluster`, THE Listing_Extractor SHALL emit the `listing_detection_failed` verdict with an empty record list and a diagnostic reason of `promo_only_cluster` that includes record count, cohort-homogeneity ratio, sibling-category count, and supported-signal count.
7. THE Listing_Integrity_Gate SHALL NOT modify, replace, or re-rank records in the candidate set.
8. THE Listing_Integrity_Gate SHALL NOT read any host, domain, or site-specific token.
9. THE Listing_Integrity_Gate SHALL apply identically to `ecommerce_listing` and `job_listing` surfaces, sourcing any surface-specific support-signal set from existing config under Extraction_Rules_Config.

### Requirement 4: Listing-Side Acquisition Escalation On Promo-Only Cluster

**User Story:** As a crawler operator, I want the listing path to retry once at a stronger acquisition tier when the integrity gate flags a promo-only cluster, so that JS-mounted product grids are recovered without allowing unbounded retries or site-specific branches.

#### Acceptance Criteria

1. WHEN the Listing_Integrity_Gate returns `promo_only_cluster` and a Stronger_Acquisition_Tier is available under existing acquisition policy, THE Acquisition_Escalator SHALL trigger exactly one listing-quality retry at the next stronger tier.
2. IF the current acquisition tier is already the strongest tier permitted for the run, THEN THE Acquisition_Escalator SHALL NOT trigger any listing-quality retry and SHALL emit a diagnostic `listing_escalation_skipped` with reason `no_stronger_tier`.
3. IF acquisition policy has blocked the host, flagged a challenge state, or disabled escalation for the current session, THEN THE Acquisition_Escalator SHALL NOT trigger any listing-quality retry and SHALL emit a diagnostic `listing_escalation_skipped` with a reason drawn from existing acquisition policy.
4. THE Acquisition_Escalator SHALL emit a diagnostic `listing_escalation_triggered` including the prior tier label, the next tier label, the gate diagnostic reason, and the candidate-set summary whenever a listing-quality retry is triggered.
5. THE Acquisition_Escalator SHALL NOT trigger more than one listing-quality retry per URL per run regardless of gate outcome on the retried fetch.
6. WHEN a listing-quality retry completes, THE Listing_Extractor SHALL re-run the Listing_Candidate_Ranker and Listing_Integrity_Gate on the new observation, and SHALL emit `listing_detection_failed` with reason `promo_only_cluster` if the gate still returns `promo_only_cluster`.
7. THE Acquisition_Escalator SHALL respect the existing user-controlled `surface`, `llm_enabled`, traversal intent, proxy, and diagnostics-capture settings without modifying any of them.
8. THE Acquisition_Escalator SHALL mirror the contract shape of the existing detail field-aware retry decision owner, reusing typed observation and diagnostic contracts rather than introducing a parallel retry mechanism.

### Requirement 5: Config Placement And Non-Site-Specific Shape

**User Story:** As a maintainer, I want every token, threshold, and selector added by this feature to live under `app/services/config/`, so that INVARIANTS Rule 1 and Rule 11 are preserved and no generic path gains a site-specific branch.

#### Acceptance Criteria

1. THE Extraction_Rules_Config SHALL own every new string token, URL pattern, path prefix, selector, and structural hint introduced by this feature.
2. THE Runtime_Settings SHALL own every new numeric threshold introduced by this feature, including `listing_cohort_homogeneity_min_ratio`, `listing_integrity_min_records`, and any escalation tunables.
3. THE Listing_Candidate_Ranker, Listing_Card_Fragmenter, Detail_Identity, Listing_Integrity_Gate, and Acquisition_Escalator SHALL source every token, threshold, selector, and prefix used by this feature from Extraction_Rules_Config or Runtime_Settings.
4. THE Listing_Candidate_Ranker, Listing_Card_Fragmenter, Detail_Identity, Listing_Integrity_Gate, and Acquisition_Escalator SHALL NOT contain any literal host name, domain name, brand name, CDN name, or site identifier.
5. IF a previously-hardcoded listing category token or prefix exists in any file outside `app/services/config/` after this feature lands, THEN the feature is non-compliant.
6. THE Extraction_Rules_Config SHALL export all new tokens through `extraction_rules.exports.json` alongside existing listing tokens, preserving existing naming conventions.

### Requirement 6: Preserve User Control Ownership

**User Story:** As a user, I want my explicit `surface`, `llm_enabled`, traversal intent, proxy, and diagnostics settings to remain authoritative, so that listing-integrity changes never silently rewrite a run configuration.

#### Acceptance Criteria

1. THE Listing_Integrity_Gate SHALL NOT modify the run's `surface`, `llm_enabled`, traversal intent, proxy, or diagnostics-capture settings.
2. THE Acquisition_Escalator SHALL NOT modify the run's `surface`, `llm_enabled`, traversal intent, proxy, or diagnostics-capture settings.
3. WHERE the run's acquisition policy disables browser escalation, THE Acquisition_Escalator SHALL NOT trigger a browser-tier listing retry.
4. WHERE the run's diagnostics settings disable screenshot capture, THE Acquisition_Escalator SHALL NOT capture screenshots during a listing-quality retry.
5. WHERE `llm_enabled=False`, THE Listing_Integrity_Gate and Acquisition_Escalator SHALL NOT call any LLM path.

### Requirement 7: Scope Fences And Non-Regression Of Existing Owners

**User Story:** As a maintainer, I want this feature to stay within the listing extraction and listing-side acquisition subsystems, so that downstream compensation and disallowed owner changes are prevented.

#### Acceptance Criteria

1. THE Listing_Integrity_Gate SHALL NOT read or write fields in `publish/`, `pipeline/persistence.py`, `pipeline/direct_record_fallback.py`, or any export path.
2. THE Acquisition_Escalator SHALL NOT modify candidate selection, tier ordering, or field extraction inside `detail_extractor.py`.
3. THE Listing_Candidate_Ranker SHALL preserve the existing utility-record rejection, editorial-URL rejection, and detail-like-merchandise logic, extending rather than duplicating those paths.
4. THE Listing_Extractor SHALL continue to emit `listing_detection_failed` for runs that yield zero supported records for any reason already covered before this feature, in addition to the new `promo_only_cluster` reason.
5. THE Listing_Extractor SHALL NOT fall back to single-record detail behavior on a listing run regardless of gate outcome, preserving INVARIANTS Rule 7.

### Requirement 8: Diagnostics And Observability

**User Story:** As a crawler operator, I want every cohort penalty, sibling-category rejection, gate decision, and escalation attempt to be visible in diagnostics, so that I can audit why a listing run ended with `listing_detection_failed` without reproducing the crawl.

#### Acceptance Criteria

1. THE Listing_Candidate_Ranker SHALL attach per-set diagnostics including the cohort-homogeneity ratio, dominant signature count, sibling-category count, supported-signal count, and any cohort penalty applied.
2. THE Listing_Integrity_Gate SHALL attach a single decision record per URL including the returned outcome, the triggering condition identifier, and the numeric metrics that drove the decision.
3. WHEN a listing-quality retry is triggered by the Acquisition_Escalator, THE Acquisition_Escalator SHALL log a structured event whose fields are sourced from the existing acquisition diagnostics contract.
4. THE Listing_Extractor SHALL include the Listing_Integrity_Gate decision record in the `listing_detection_failed` diagnostic when that verdict is emitted.
5. IF a cohort penalty is applied to a candidate set but the Listing_Integrity_Gate still returns `product_grid`, THEN THE Listing_Extractor SHALL retain both diagnostic records so that set-level and gate-level decisions can be audited independently.

### Requirement 9: Generic-First Coverage Across Listing Surfaces

**User Story:** As a crawler operator, I want the same integrity controls to apply to ecommerce listing and job listing crawls, so that sibling-category promo clusters are rejected uniformly across generic surfaces without per-site code.

#### Acceptance Criteria

1. THE Listing_Integrity_Gate SHALL apply the same cohort-homogeneity, sibling-category, and support-signal rules to `ecommerce_listing` and `job_listing` surfaces.
2. WHERE the active Listing_Surface is `job_listing`, THE Listing_Integrity_Gate SHALL treat job-listing support signals (`company`, `location`, `salary`, `job_type`) as satisfying the support-signal condition in Requirement 3.
3. WHERE the active Listing_Surface is `ecommerce_listing`, THE Listing_Integrity_Gate SHALL treat ecommerce listing support signals (`image_url`, `price`, `rating`, `review_count`, `brand`) as satisfying the support-signal condition in Requirement 3.
4. THE Acquisition_Escalator SHALL apply the same escalation contract to `ecommerce_listing` and `job_listing` surfaces.
5. THE Listing_Candidate_Ranker SHALL apply the cohort penalty identically regardless of Listing_Surface.
