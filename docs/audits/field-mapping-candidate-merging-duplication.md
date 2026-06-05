# Field Mapping & Candidate Merging Duplication Audit
## Scope: adapter · structured source · embedded JSON · JS state · DOM extraction paths
**Type:** Audit only. No code changes.  
**Goal:** Reduce LOC and complexity without changing extraction order.

---

## 1. Canonical field coercion dispatched independently by every tier

`services/shared/field_coerce.py:coerce_field_value` is the single gate every caller must pass through, yet each extraction tier owns its own "which raw key maps to which canonical field" decision:

| Tier | Where mapping happens |
|---|---|
| Adapter | `services/adapters/*.py` — per-adapter manual extraction, per-field `coerce_field_value` calls |
| Structured / embedded JSON | `services/extract/field_candidates/structured_payloads.py:collect_structured_candidates` — dict traversal with `alias_lookup` |
| Network payload mapper | `services/network_payload_mapper.py:_map_body_with_spec` — JMESPath spec paths to field names, then `finalize_candidate_value` |
| JS state | `services/js_state/state_normalizer/_product_mapping.py`, `_variant_mapping.py`, `_variant_rows.py` — glom spec + per-field manual coercion |
| DOM | `services/dom/selector_engine.py` — per-field `coerce_field_value` from node text/attrs |

**Why it matters:** The alias → canonical dispatch and the field-category dispatch (`STRUCTURED_*_FIELDS`, `LONG_TEXT_FIELDS`) are the same decision, implemented independently in all five tiers. A change to `FIELD_ALIASES`, a category membership, or a coercion rule must be replicated manually across all five paths.

---

## 2. Structured candidate collection traversed independently in 6 places

`collect_structured_candidates(payload, alias_lookup, page_url, candidates)` is the canonical traversal, but it is independently replayed or shadowed by inline traversal in:

- `services/extract/structured_listing_handler.py:39`
- `services/network_payload_mapper.py:433` and `:554`
- `services/extract/network_listing_mapper.py:266`
- `services/extract/detail/assembly/candidate_collection.py:233`
- `services/pipeline/raw_json.py:396`

Each call site builds its own `candidates: dict[str, list[object]]`, then walks the same `dict`/`list` payload applying the same `@type` / `itemListElement` / `additionalProperty` / breadcrumb / `fieldName` / product-shape rules. The traversal logic in `structured_payloads.py:169` is the canonical implementation, yet callers do not consistently route through it — some build partial inline traversals for gating checks (e.g. `_has_detail_anchor` in `network_payload_mapper.py:543`).

**Risk:** Traversal rules drift between the canonical function and inline variants, causing inconsistent candidate discovery across surfaces.

---

## 3. `_deep_merge_structured_dict` shadowed by ad-hoc dict overlay in 4 places

`services/extract/field_candidates/finalization.py:100` defines the authoritative merge with `option_values` awareness (skip if both sides have dict; skip incoming keys that appear inside incoming `option_values`). The same "fill non-empty from secondary" pattern is re-implemented ad-hoc in:

| Site | Semantic gap |
|---|---|
| `services/pipeline/record_extraction_stage.py:_best_adapter_result` (L192–197) | Shallow overlay; no `option_values` guard |
| `services/js_state/state_normalizer/_identity.py:_merge_same_product_record` (L16–32) | Same guard; plus explicit `variants`/`variant_count` skip |
| `services/adapters/belk.py` | Manual dict merge of the same shape |
| `services/network_payload_mapper.py:_map_body_with_spec` (L313–322) | Key-wise fill via `_first_non_empty_path` — shallow |

Merging an adapter record over a structured record without `option_values` awareness can silently overwrite or duplicate nested variant data.

---

## 4. Variant-row merge invoked from 5 call sites; row construction also duplicated

`merge_variant_rows` (`extract/variant_identity_merge.py:426`) and `merge_variant_pair` (`:409`) are invoked from:

1. `extract/field_candidates/finalization.py:41` — structured-candidate finalization
2. `js_state/state_normalizer/_identity.py:34,49` — same-product JS state merge (plus explicit scalar-variant fallback)
3. `js_state/marketplace_choice_mapper.py:41` — marketplace choice merge
4. `extract/detail/variants/dom_extraction.py:1038` — DOM pair overlay (uses `merge_variant_pair` directly)
5. `extract/variant_normalization/deduplication.py:153,169` — separate dedupe pass with same identity/semantic logic

**Row construction** is itself independently duplicated across three namespaces:

| Namespace | File | Shape built |
|---|---|---|
| JS state | `js_state/state_normalizer/_variant_rows.py` | 7+ fallback shapes (`variants`, `plp_pdp_bridge`, `coreProducts`, `variantMatrix`, `sizes`, option groups, nested choices) |
| Structured | `extract/field_candidates/structured_payloads.py` + `variant_rows.py` | from JSON-LD `hasVariant`, `offers`, product payload |
| DOM | `extract/detail/variants/dom_extraction.py` | scraped from DOM variant selectors |

All three paths end up calling `resolve_variants(axes, rows)` or `merge_variant_rows`, but each builds `axes` and `option_values` independently. This is the dominant LOC cluster in the extraction subsystem.

---

## 5. `finalize_record` invoked at every tier boundary — often redundantly

`services/shared/field_coerce.py:983` defines the canonical finalizer (`clean_record → strip_tracking → normalize_fields`). It is called 20+ times:

| Call site | Context |
|---|---|
| Adapters (`myntra.py`, `belk.py`, `nike.py`) | After local mapping |
| `structured_listing_handler.py:73` | After structured listing extraction |
| `network_payload_mapper.py` | Via `_finalize_detail_result` |
| `extract/detail/assembly/candidate_collection.py:516` | Last step of detail assembly |
| `pipeline/extract_records.py:128, 380` | Postprocessing for JSON and detail records |
| `listing_extractor.py:392` | After listing DOM extraction |
| `network_listing_mapper.py:149` | After network listing mapping |
| `public_record_firewall.py:161` | Public record shaping |
| `pipeline/raw_json.py:417,424` | After raw JSON extraction |
| `pipeline/direct_record_fallback.py:138,212` | Fallback shaping |
| `pipeline/sitemap.py:51` | Sitemap records |
| `extract/detail/assembly/record_assembly.py:140` | Detail assembly |

A record flowing through structured → adapter → detail assembly can be finalized 3–4 times. The operation is idempotent but duplicated work; any change to the sequence must be replicated at every call site.

---

## 6. Field-category classification (`STRUCTURED_*_FIELDS`, `LONG_TEXT_FIELDS`) repeated by name in 7 modules

The four category sets are imported from `shared/field_coerce.py` in:

- `extract/field_candidates/finalization.py`
- `extract/field_candidates/structured_payloads.py`
- `network_payload_mapper.py`
- `extract/detail/assembly/candidate_collection.py`
- `pipeline/direct_record_fallback.py`
- `dom/selector_engine.py`
- `dom/section_extraction.py`

Each module then branches on category membership for coercion, candidate bucketing, merge semantics, or deduplication. The category sets themselves are the single source of truth, but the branching logic is independently implemented in 3–4 places (notably the `STRUCTURED_MULTI_FIELDS` dedupe-and-split pattern).

---

## 7. Two competing listing-merge policies on the same `extract_records` path

In `services/pipeline/extract_records.py:134–250`, the listing path runs two merge steps with different semantics:

1. **`_backfill_listing_rows_from_adapter`** (L215) — fills empty listing fields from adapter rows, keyed by URL then identity. Low fidelity.
2. **`best_listing_candidate_set`** (L230) — full admission, scoring, dedupe, cohort-merge across adapter + generic listing + network candidates.

A field populated by step 1 can be rewritten by step 2 (or vice-versa depending on source priority inside `best_listing_candidate_set`). The two policies are not coordinated and have subtly different dedupe/overlay guards.

---

## 8. `network_payload_mapper` re-traverses payload for a simple gating check

`services/network_payload_mapper.py:_has_detail_anchor` (L543) independently builds an `alias_lookup`, collects candidates for `title`/`url`/`price`/`sku`/`brand`, and calls `finalize_candidate_value` per field — a ~30-line mini-replay of `collect_structured_candidates` — just to return a boolean. The full canonical traversal is called again later by the same function for the actual mapping. This gating traversal is a structural duplicate and should be a predicate over cached candidates.

---

## 9. JS state and structured variant-row builders independently extract the same axes

Both namespaces recurse into product payloads to build rows with `option_values {size, color, ...}`:

- `_canonical_variant_axis_value`, `_variant_axis_raw_value` in `js_state/state_normalizer/_variant_mapping.py`
- `_structured_variant_rows`, `_structured_offer_variant_rows`, `_structured_variants_from_product_payload` in `extract/field_candidates/variant_rows.py`
- Axis-key detection, color short-code rejection, size alias collapse, and `image_url` extraction each appear in both namespaces with slightly different guards and fallback chains.

---

## 10. Record overlay merge (non-variant) has no shared owner

The "primary wins; secondary fills empty" dict-overlay pattern appears in four places, each with its own guard and field exclusions:

| Site | Notable guard difference |
|---|---|
| `pipeline/record_extraction_stage.py:_best_adapter_result` | URL-keyed merge; unsourced fingerprint dedupe |
| `js_state/state_normalizer/_identity.py:_merge_same_product_record` | Skips `variants`/`variant_count`; special-cases availability/stock/price |
| `services/adapters/belk.py` | Manual merge, no special cases |
| `pipeline/extract_records.py:_backfill_listing_rows_from_adapter` | URL-keyed then identity-keyed; no nested merge |

None of these call a shared helper, so guard semantics diverge.

---

## Consolidated duplication map

| Concern | Center of gravity | Duplicated in (independent implementations) |
|---|---|---|
| Canonical alias + coercion dispatch | `shared/field_coerce.py:coerce_field_value` + `field_policy.py` | Adapter, structured, network mapper, JS state, DOM — 5 independent "raw key → canonical" mappings |
| Structured candidate collection | `extract/field_candidates/structured_payloads.py:collect_structured_candidates` | `network_payload_mapper`, `network_listing_mapper`, `structured_listing_handler`, `raw_json`, `candidate_collection` — same payload walk replayed 5× |
| Structured-dict merge | `extract/field_candidates/finalization.py:_deep_merge_structured_dict` | `_best_adapter_result`, `_merge_same_product_record`, `belk.py`, `network_payload_mapper` — shallow overlay without `option_values` semantics |
| Variant merge | `extract/variant_identity_merge.py` | `finalization.py`, `_identity.py`, `marketplace_choice_mapper.py`, `dom_extraction.py`, `deduplication.py` — 5 call sites |
| Variant row construction | No single owner | `_variant_rows.py` (JS state), `variant_rows.py` (structured), `dom_extraction.py` (DOM) — 3 independent row builders → same merge |
| Finalization | `shared/field_coerce.py:finalize_record` | 20+ call sites; records finalized 3–4 times mid-pipeline |
| Field-category branching | `STRUCTURED_*_FIELDS` sets in `field_coerce.py` | Branch logic independently in finalization, candidate_collection, network_payload_mapper, direct_record_fallback, selector_engine, section_extraction |
| Record overlay (non-variant) | No single owner | `_best_adapter_result`, `_merge_same_product_record`, `belk.py`, `_backfill_listing_rows_from_adapter` |
| Listing merge policy | `best_listing_candidate_set` + `_backfill_listing_rows_from_adapter` | Two uncoordinated merge steps on the same listing path in `extract_records.py` |

---

## Suggested consolidation order (highest LOC / complexity reduction first)

1. **Variant row construction + merge** — unify the three row builders into a single shape, then all call sites use one `resolve_variants` / `merge_variant_rows` path.
2. **Structured candidate collection** — make `collect_structured_candidates` the only traversal entry point; replace `_has_detail_anchor` inline traversal with a predicate over cached candidates.
3. **Record overlay helper** — a single `overlay_record(primary, secondary, skip=...)` used by `_best_adapter_result`, `_merge_same_product_record`, `_backfill_listing_rows_from_adapter`, and adapter-level merges.
4. **Finalization scheduling** — collapse redundant mid-tier finalizations so each record is finalized once at the pipeline boundary rather than at every tier exit.
5. **Field-category dispatch helper** — a single `categorize_field(field_name)` used by all branches instead of repeated `if field_name in X` checks.
