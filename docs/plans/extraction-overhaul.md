Extraction Accuracy Overhaul + Knowledge Graph Usefulness

  Context

  Slices 1–12 shipped a deterministic, LLM-free extraction pipeline and a PostgreSQL Knowledge Graph, but two things are broken in practice:

  1. Extraction accuracy has regressed. A current 90-URL ecommerce audit (artifacts are current ground truth) shows systemic failures: 16 URLs miss
  price/currency, 21 miss availability, 45 produce no variants, plus cross-product image contamination, phantom prices, and bad identity ("Target." as
  brand, "ILCE-9M3 IN5" as title, retailer name instead of Rolex). Two independent audits (docs/audits/crawlerai_extraction_pipeline_audit_2026-06-29.md,
  …_url_issue_matrix_2026-06-29.csv) trace these to architectural causes.
  2. The Knowledge Graph isn't useful. Its #1 spec purpose — root-cause a field from one diagnose.json — is invisible: neither diagnose.json nor report.json
  is exposed by any API or UI. contract_outcomes is hardcoded null, captured_but_rejected fields ship with no reason, the graph stores noise (every image
  URL as a node), and the KG tab is a flat 12-node echo of one page.

  Decisions made with the user:
  - Accuracy is the priority. Sequence: extraction first, then KG usefulness.
  - No stale-output classification. The on-disk artifacts are produced by current code; fix directly against them. (Drops the audits' entire
  "provenance/replay" Phase 0.)
  - Hybrid architecture with a grounded LLM fallback. Deterministic collectors harvest evidence; the deterministic resolver runs first; an LLM resolver is
  invoked only for missing/low-confidence fields and may only choose among collected evidence candidates (or enum/role classifications) — never invent a
  value. The firewall rejects any published value not traceable to a real collected candidate.
  - Stay generic. No site-specific adapters or retailer-domain branches (enforced by test_extraction_carries_no_retailer_domain_literals). An LLM is generic
  by construction; every deterministic rule must key on evidence shape, never on the audit sample.
  - Treat repo as greenfield (no commits; user runs CodeRabbit at the end).

  Intended outcome: correct records on the 8 failure categories, with every value explainable through diagnose.json lineage, and a KG that surfaces those
  explanations and lets an operator review/promote/override the LLM's proposed source choices.

  ---
  Architecture: where the LLM sits

  collect (deterministic, fail-closed)
    → normalize → build_entities → select_target → validate
    → resolve (deterministic _rank, value-quality aware)        [WS-A2]
    → apply_contracts (replays saved generic/operator/llm_proposed sources)  [exists]
    → LLM FALLBACK RESOLVER (only fields still missing/low-confidence/review) [WS-A3, NEW]
         • input: field + its collected candidate evidence (+ context)
         • output: pick a candidate evidence_id, OR classify (brand role / title quality / variant-real)
         • NEVER emits a value absent from candidates
         • produces a Decision (selection_origin tracked) + an llm_proposed contract observation
    → materialize (serialize-only)                              [WS-A2]
    → firewall (enforce keys/types/enums; reject non-lineage values) [WS-A2]

  The LLM's choice is persisted by the projector as an llm_proposed contract; contract_runtime.apply_contracts replays it on the next same-template page, so
  the LLM is not called again for that (template, field). The KG contracts UI is where an operator promotes llm_proposed → operator or overrides it.

  Reuse (do not rebuild): app/connectors/llm/ (provider_client, runtime, cache, budget, circuit_breaker, cost_logging, prompt_rendering);
  contract_runtime.py (apply_contracts, _selection_priority already ranks llm_proposed); existing DerivedFact/Decision/ContractOutcome types in
  extraction/contracts.py; selection_origin already supports "llm_proposed".

  ---
  Workstream A — Extraction (priority)

  A1. Fail-closed collection (AUD-02/03/04) — clean candidates for both resolvers

  - Structured root selection fails closed. core/records/js_state_scope.py selected_product_root_paths returns a typed RootSelection{status:
  selected|unresolved|ambiguous, roots}. Broaden candidate matching beyond exact canonical URL to relative-URL / @id / handle / product-ID / SKU-MPN /
  title-H1 agreement (all structural). Delete the fail-open branch in collectors/js_state.py path_is_within_selected_root (if not selected_roots: return
  True). On unresolved/ambiguous, admit nothing as product-owned; quarantine other objects as rejected evidence so diagnose.json shows why. Same consumption
  in collectors/jsonld.py.
  - Container-scoped DOM. collectors/dom.py collect: add _select_product_container(doc) keyed on structural agreement (smallest container holding H1 +
  purchase control + gallery + canonical form); scope h1/[data-price]/[data-currency]/[data-sku]/brand/_product_image_nodes to it. Remove the all-candidates
  0.5-confidence image fallback (_product_image_nodes ~205-206) that leaks galleries/recommendations.
  - Graph decides ownership, not collectors. Stop minting a page-URL product subject and stamping parent_subject_id on every offer/asset
  (collectors/js_state.py network_row; collectors/dom.py collect). Emit relation_type + identity candidates instead. Tighten entities.py
  _owner_product_id/_link_offers/_link_assets to require an explicit relation or ≥2 agreeing identity signals before assigning an owner.
  - Tests: unresolved root admits no offers; DOM collection is container-scoped (recommendations with [data-price] don't contribute); collectors assert no
  page-product parent. Negative corpus: recommendation cards, search results, cache objects, sibling products. (Fixes Back Market PlayStation image, Shoe
  Palace cross-product media, phantom prices.)

  A2. Resolution as the sole semantic owner (AUD-08 + resolver ranking)

  - Value-quality term in _rank. resolution.py _rank (~703-764): add generic _value_quality(ev) (lower=better) from evidence shape only — enum validity
  (availability enum, ISO-4217 currency), format plausibility (positive Decimal price, GTIN check digit, URL grammar), pollution flags (code_only_title,
  etc.). Reorder the generic tuple to (value_quality, reliability, directness, -confidence, evidence_id) so source reliability beats directness (kills
  phantom DOM [data-price] over JSON-LD offer). Fold the special-cased title/brand/currency/description tuples onto the shared value_quality prefix.
  - Derivation moves into resolution as DerivedFacts (extend existing _derived ~613-649): parent price min/max + aggregate, SKU coherence, availability
  aggregate — each with input_evidence_ids + rule_id. Move asset primary/dedup/conflict selection from output_safety.py (materialize_product_assets,
  sanitize_materialized_record) into resolution's AssetDecision path.
  - Materialize = serialize-only; firewall = enforce only. materialization.py materialize writes values+lineage, no
  aggregation/SKU-drop/range/asset-selection. public_record_firewall.py enforces keys/types/enums/URL canonicalization only.
  - Divergence guard. New app/extraction/divergence.py assert_public_matches_resolution(data, lineage, resolution): every public scalar must equal an
  accepted decision or a lineage-reachable DerivedFact; otherwise emit a Finding (visible in diagnose.json). Wire at persistence._public_data_for_record.
  - Tests: JSON-LD offer beats phantom DOM price; enum-invalid availability loses to enum-valid; public never diverges from resolution; materialization
  performs no aggregation.

  A3. Grounded LLM fallback resolver (NEW — the accuracy lever)

  - New module app/extraction/llm_resolver.py. Called from extraction/engine.py after deterministic resolve + apply_contracts, only for fields in
  unresolved_fact_types or whose decision is low-confidence/review (e.g. brand role ambiguity, code-only/slug title, no-variant, missing offer). Clean PDPs
  never call it.
  - Grounding contract (anti-hallucination): the prompt presents the field plus its collected candidate evidence (value, source descriptor, locator,
  confidence) and minimal context (resolved title/URL/other fields, product-container text snippet). The LLM must return one of: a candidate evidence_id to
  accept; an enum/role classification over existing candidates (e.g. which brand candidate is manufacturer vs retailer; title quality
  clean|partial|slug|code_only; which rows are real sellable variants); or abstain. Output is validated: an evidence_id must exist; an enum must be in the
  allowed set. Anything else is discarded and the field stays unresolved. The firewall + A2 divergence guard are the backstop.
  - Output wiring: produce a Decision whose accepted evidence is the LLM-chosen candidate, rule_id="llm_fallback", and record the model id + rationale; emit
  an llm_proposed contract observation (consumed by the projector, WS-B3) and a ContractOutcome so it appears in diagnose.json.
  - Cost/latency controls (reuse connectors/llm): cache keyed on (template_fingerprint, field, candidate-set hash); budget + circuit_breaker so LLM failure
  degrades to deterministic result, never blocks a crawl; batch fields per record into one call. Because apply_contracts replays the resulting llm_proposed
  source, repeat pages on a template skip the LLM entirely.
  - Tests: LLM never publishes a value absent from candidates; LLM-chosen source becomes an llm_proposed contract; second same-template page resolves via
  contract without an LLM call; circuit-open falls back deterministically.

  A4. Offer & availability coverage (AUD-06)

  - Generic container-scoped microdata/itemprop fallback for price/priceCurrency/availability (schema.org property names) at confidence below JSON-LD.
  - Ungate currency from price evidence (pipeline.py _currency_from_price_symbol): allow locale/microdata-derived currency independently; keep the atomic
  price+currency rule but move it to the firewall enum layer. Replace any host→currency entries with TLD/locale-segment inference (.co.in→INR, /en-gb/→GBP).
  - Availability enforced to enum + reason (pipeline.py _availability): no raw passthrough; non-enum → flagged evidence with reason, ranked below
  enum-valid, dropped by firewall with reason in diagnose.json.
  - Acquisition profiles + retry alignment (core/config/field_mappings.py, result_building.py): Core-identity / Sellable-offer / Variant profiles; when
  offer/variant profile is requested, add availability+currency+variants to capture/retry targets.

  A5. Typed variants + assets + identity (AUD-07/09/10)

  - Single variant publish gate (converge the three copies in materialization._publishable_variant_row, output_safety._variant_row_is_actionable,
  firewall._public_variant_row_is_sellable): publishable iff a real option configuration (≥1 OptionAxis value from the existing ProductOptionCatalog) or an
  explicit sellable-child relation (isVariantOf/parent @id). Per-variant offer/availability/SKU backfill from the option catalog with lineage (extend
  _inherit_variant_offer_decisions). Reuse existing OptionValue/OptionAxis/ProductOptionCatalog/OfferDecision; add PurchasableVariant only if needed.
  - Assets: url_utils.py public_asset_delivery_url rejects malformed delivery URLs (repeated ?); dedup by asset_url_identity (not delivery URL) before role
  assignment; unowned assets (A1) never reach AssetDecision.
  - Identity: field_coerce_text.py coerce_brand_text strips trailing punctuation + normalizes casing/spacing ("Target.", "Thenorthface", "jcrew"). Carry a
  brand_role (manufacturer/designer/seller/retailer/site) on evidence; only manufacturer-role evidence resolves public brand (role assigned by source
  relation, not a name denylist) — the LLM fallback (A3) classifies role when ambiguous. Code-only/slug titles resolve to partial/review, not clean (extend
  engine._assess_detail).
  - Genericness ratchet: add test_extraction_rules_have_no_matrix_tuned_constants asserting new rule tables contain only structural vocab (schema.org enums,
  ISO currencies, generic UI tokens), failing on any brand/retailer/product token.

  ---
  Workstream B — Knowledge Graph usefulness

  B1. Expose diagnostics through the API

  New read endpoints in api/knowledge.py (or a new api/diagnostics.py) serving per-URL diagnose.json and run report.json via the safe ArtifactRepository
  read_json/resolve_uri. Reuse observability/run_report.py build_run_report.

  B2. Fix diagnose.json self-containment

  - Populate contract_outcomes (currently hardcoded null) from the ContractOutcomes now produced by apply_contracts + the LLM fallback
  (observability/diagnose.py).
  - Carry RejectedEvidence.reason into the captured_but_rejected branch (result_building.py ~122-124) so sku/availability/price rejections show why.
  - Stop the lossy collapse of product.sku/variant.sku by trailing segment (_decisions_by_public_field).

  B3. Reduce graph node noise + ingest LLM-proposed contracts

  persistence/projection.py: stop creating an entity per asset URL (key assets as attributes of their owner, not nodes). Persist the LLM fallback's
  llm_proposed contract observations as kg_extraction_contracts rows (selection_origin llm_proposed) so apply_contracts replays them and the UI can
  show/override them.

  B4. KG tab refocus (make it actionable)

  knowledge-graph-tab.tsx: replace the single-page node echo and vanity tiles with (a) per-field source reliability across the crawl and (b) a diagnostics
  drill-down (root-cause from report.json → diagnose.json, B1). Contract panel surfaces real choices including llm_proposed selections with
  promote-to-operator / override actions (PUT /contracts/{id}/selection exists). Where this intersects state, migrate the affected datasets to TanStack
  Query per frontend audit B4 (don't take on the rest of the frontend perf audit here).

  ---
  Verification

  - Backend unit/component: cd backend && .venv\Scripts\python -m pytest for each new test named above; the genericness ratchets
  (test_extraction_carries_no_retailer_domain_literals, new …no_matrix_tuned_constants) must stay green.
  - End-to-end against the audit corpus: run the pipeline over the 90 audit URLs (artifacts under backend/artifacts/runs/), regenerate
  record.json/diagnose.json, and confirm: price/currency/availability present where evidence exists; no cross-product images; variants present with option
  configs; brand = manufacturer; slug/code titles flagged partial/review; every public value traces to lineage (A2 divergence guard emits no Findings).
  - LLM fallback: verify it fires only on missing/low-confidence fields, never publishes a non-candidate value, and that a second same-template page
  resolves via the persisted llm_proposed contract with no LLM call (cache/contract hit).
  - KG/UI: load the KG tab for a crawled domain; confirm diagnostics drill-down renders report.json→diagnose.json, contract_outcomes is populated,
  captured_but_rejected shows reasons, and an llm_proposed selection can be promoted/overridden and takes effect on re-crawl.