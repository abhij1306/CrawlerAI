# Implementation Decisions & Coordination (authoritative)

Repo: `/code/abhij1306/CrawlerAI`. Base: `main`. Work branch: `vorflux/extraction-cascade-rearchitecture`.
User authorized implementation ("proceed with implementation", 2026-07-15). Decisions below are locked;
build subagents MUST follow them and MUST NOT re-open resolved forks.

## Recipe scope + operator editability (User Decision #1368)
- **Scope key = (domain, surface, route_pattern).** Maps to existing `ExtractionTemplate` unique key
  (`domain`, `surface`, `fingerprint`) + `route_pattern`. Finest granularity; handles multi-layout domains.
- **Auto-learn on first crawl** when `llm_enabled` and floors produced nothing for a NEW template.
- **Most-confident recipe replays until an operator changes it.** Persist a confidence/quality signal on the
  recipe; the highest-confidence `active` recipe for a template replays. Operators can edit/override via the
  existing `ExtractionOperatorLabel` mechanism (review promotion + grounded field feedback). Operator edits win
  over auto-learned recipes.
- **Self-heal + escalate on failure — mirror the acquisition-contract loop** in
  `crawl/profile/acquisition_contract.py` (`note_acquisition_contract_failure` → failure_count →
  `stale` threshold → recompile). Do NOT invent a new escalation mechanism. On replay grounding drift, increment
  failure count; once stale, fall through to floors and (if `llm_enabled` + new/changed template) recompile once.
- Reuse existing `extraction_memory` tables (`ExtractionTemplate`, `ExtractionRecipe`,
  `CompiledExtractionRecipe`, `ExtractionReleaseSnapshot`, `ExtractionManifest`, `ExtractionOperatorLabel`).
  Add fields only if a confidence signal is missing; prefer storing confidence in recipe `payload`/`version`
  ordering before adding a column.

## SurfaceSpec — ONE reconciled extension (single owner: Foundation task)
Merge BOTH subplans' field sets into one dataclass. Do not split across two build tasks.
Adopt the branch's `surfaces.py` fields verbatim PLUS the crosscut record-richness fields:
- From branch (typed listing lens): `structured_types: frozenset[str]`,
  `listing_optional_text_facts: tuple[str,...]`, `listing_structured_fact_kinds: tuple[tuple[str,str],...]`,
  `listing_network_fact_keys: tuple[tuple[str,tuple[str,...]],...]`, plus `ListingSchema` dataclass +
  `listing_schema()` + `structured_type_selectors()` + `entity_type_for`.
- From crosscut (record-richness, de-commerce discovery): `record_signal_facts: frozenset[str]`,
  `min_record_signals: int` (default 1), `off_host_records_allowed: bool` (jobs True, commerce False).
- Populate all 4 `SURFACE_SPECS` entries. commerce listing signals: `{offer.price, asset.url}`, same-site;
  job listing signals: `{job.location, job.apply_url, job.company}`, off-host allowed.
- `record_signal_facts ⊆ allowed_facts`, `required_facts ⊆ allowed_facts`, `min_record_signals ≥ 1`.

## Shared-file ownership (prevent parallel-build collisions)
These files are edited by exactly ONE task/owner in the sequence below; no two parallel subagents touch them:
- `extraction/surfaces.py` → Foundation task only.
- `extraction/contracts.py` (`CapabilityRequest` relax: `max_attempts` cap configurable, add `reason` values
  `listing_boundaries_missing`, `network_floor_missing`, add `network_payloads` to required-artifact vocab)
  → Foundation task only. Cap value lives in `core/config/cascade.py` (default 2).
- `crawl/pipeline/extraction_loop.py` (verdict Literal `listing_failed`→`listing_detection_failed`)
  → Foundation task only.
- `extraction/result_building.py::retry_request` (surface-agnostic `CapabilityRequest` for all 4 surfaces)
  → Job-detail/ladder slice owner (Slice 4), NOT parallel with foundation.
- `extraction/jobs.py` + `extraction/listing.py` gate unification → extraction-cascade job-listing slice (Slice 2).
- Card enumeration owner = NEW `backend/app/acquisition/listing_cards.py`; `core/config/selectors.py` stays
  data-only (repo INVARIANT). Acquisition-ladder slice owns this.

## Config placement (repo INVARIANT)
All strings/thresholds/selectors/field-names → `core/config/*` (new `core/config/cascade.py` for cascade knobs;
`surfaces.py` spec data is config-adjacent and allowed there). No literals in service code.

## Sequencing (independently shippable, per-surface gated; NO monolithic cutover)
Phase 0 Foundation (this branch, no behavior cutover):
  F1 SurfaceSpec reconciled extension + ListingSchema + core/config/cascade.py
  F2 representation/flat_map + document primitives (child_elements, content_text)
  F3 CapabilityRequest relax + verdict Literal fix (correctness, no behavior change to passing paths)
  F4 [parallel/isolated] AI-visibility verbatim port + migration chain reconcile + wiring
  F5 [parallel/isolated] eval harness backend/eval/ + scorer tests
  F6 [parallel/isolated] docs fix + ungated dead-code deletion (relocate live const first)
Then per-surface slices in order, each gated by eval ≥ baseline before deleting that surface's selectors:
  S1 commerce listing → S2 job listing → S3 commerce detail → S4 job detail
  LEARN-ONCE tier lands after S1+S3 floors exist (before detail hardening).
Never delete a surface's working selector/DOM-floor path before its cascade replacement beats baseline on eval.

## Reference (read-only)
Branch `origin/feature/extraction-v3-phase0-eval` proved primitives (dyson 14 / arcteryx 6 / ultipro 4, zero LLM).
Port its PRIMITIVES (`listing_records.py`, `listing_tier0.py`, `network_listing.py`, `representation/flat_map.py`,
recipe contracts/executor/transforms/artifacts) via `git show <branch>:<path>`. REJECT its architecture (two
competing pipelines; compiler that reverse-derived from published records). Do NOT port `20260713_0004` migration
(abandoned compiler). NEW main-owned compiler must read ONLY capture bundle + flat-map, never published records.
