# CrawlerAI — Site & Product Knowledge Graph

**Status:** Design knowledge document (authoritative)
**Scope:** Extraction architecture, diagnostics/observability, cross-crawl knowledge graph, and crawl setup-cost reduction.
**Companion:** `docs/plans/site-knowledge-graph-master-plan.md` holds the execution slices. This document holds the *what* and the *why*; the plan holds the *order*. When they disagree, this document wins and the plan is corrected.

---

## 1. Why this feature exists

Three problems, in priority order.

### 1.1 Debugging is broken

When extraction produces a wrong or incomplete record, the only way to find root cause today is:

1. The operator copies the output JSON into a coding agent by hand.
2. The agent reads the whole record JSON, the whole page HTML, and several JSON files scattered across an artifacts directory.
3. The agent still cannot tell which source was canonical, which candidate was rejected, or why — so the bug is never resolved.

The cause is not too little data. It is that **the data needed to explain a field is computed and then thrown away**, while the data that *is* written is split across two competing directory layouts, duplicated, and partly references files that are never written. The agent cannot cheaply locate root cause, so it falls back to reading raw HTML and source code — which is slower and still inconclusive.

**The governing principle for all observability work in this feature:**

> A diagnostic artifact must cost less to read than the code it explains. If reading the artifact is more expensive than reading the source, the agent will read the source and the artifact is dead weight.

This forces a single, self-contained, bounded diagnosis file. See §6.

### 1.2 Extraction quality is opaque and partly path-dependent

Extraction is a deterministic pipeline (collect → normalize → build entities → resolve → materialize → firewall). It is mostly site-agnostic, but residual site-shaped behavior and a large amount of dead/duplicated observability code make it hard to reason about *why* a field is present, missing, or wrong. Output efficiency and field coverage — the two qualities that matter most — are not measurable today because the per-field provenance is discarded.

### 1.3 Every new site starts from zero

The first crawl of a new site is the most expensive. There is no durable, cross-crawl memory of *how to extract* a given site template — which source provides each field, which selector is canonical, which candidates are noise. Each new site triggers the broken debugging loop in §1.1. We want the **one-time setup cost of a site to be paid once** and then reused, so that all future crawls of that site are accurate by default.

---

## 2. The two memories: Domain Memory vs Knowledge Graph

CrawlerAI has **two** durable learning stores. They are owned by different subsystems, solve different problems, and must never migrate into each other.

| | **Domain Memory** | **Knowledge Graph (new)** |
|---|---|---|
| Owned by | Acquisition | Extraction |
| Answers | *How do I fetch this site?* | *How do I extract this site, and what have I learned about its products?* |
| Scope key | domain, surface | domain → page template → surface → canonical field |
| Holds | saved selectors, learned acquisition contract (browser engine, cookies, proxy, `prefer_browser`), stored cookies/`storage_state`, operator field feedback, host block/protection state | extraction contracts (per-field source decisions), page templates, canonical product/offer/brand entities, claims, provenance |
| Backing tables | `domain_memory`, `domain_run_profiles`, `domain_cookie_memory`, `domain_field_feedback`, `host_protection_memory` | `kg_site_versions`, `kg_entities`, `kg_relationships`, `kg_claims`, `kg_assertion_evidence`, `kg_extraction_contracts` |
| Reset behavior | wiped by Domain Memory reset | preserved across Domain Memory reset and workspace reset; purged only by explicit graph purge |

**Why separate.** Acquisition memory is about *getting bytes past a host's defenses*. Knowledge memory is about *understanding the bytes once you have them*. They fail independently, are reset independently, and have different security and ownership models. Collapsing them couples a browser-fingerprint change to a product-fact change, which is exactly the kind of hidden coupling this rebuild removes.

> Today the `domain_memory` table already stores per-`(domain, surface)` CSS selectors. That is the seed of an extraction contract living in the wrong store. The Knowledge Graph is where executable extraction contracts belong; Domain Memory keeps only acquisition concerns.

---

## 3. End-to-end data flow

```
                       ┌─────────────────────────────────────────────┐
                       │  Acquisition  (Domain Memory owned)          │
                       │  fetch page → rendered HTML + network JSON   │
                       │  + browser diagnostics                       │
                       └───────────────────┬─────────────────────────┘
                                           │ PageAcquisitionResult
                                           ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  Extraction  (deterministic, LLM-free, Knowledge Graph owned)             │
   │                                                                            │
   │  collect ──▶ normalize ──▶ build_entities ──▶ select_target               │
   │     │           │              │                  │                        │
   │  Evidence    Evidence       EntitySet         primary product/offer        │
   │     │                                              │                        │
   │     └──────────────▶ validate ──▶ resolve ──▶ materialize ──▶ firewall     │
   │                         │            │            │             │           │
   │                      Finding      Decision    PublicRecord   public record  │
   │                                                                            │
   │  Emits: record + ExtractionResult(evidence, decisions, field_states,       │
   │         findings, metrics)                                                 │
   └───────────────────────────────────┬────────────────────────────────────────┘
                                        │  observations only — extraction never
                                        │  writes graph storage
                    ┌───────────────────┴───────────────────┐
                    ▼                                        ▼
   ┌────────────────────────────────┐      ┌──────────────────────────────────┐
   │  Diagnostics publisher          │      │  Knowledge Graph projector        │
   │  (sole artifact writer)         │      │  (run-complete, transactional)    │
   │                                 │      │                                   │
   │  page.html                      │      │  upsert entities / relationships  │
   │  record.json                    │      │  upsert claims + evidence         │
   │  diagnose.json  ◀── self-       │      │  project field-source contracts   │
   │                    contained    │      │  freeze site version              │
   └────────────────────────────────┘      └──────────────────────────────────┘
```

**The one-way rule.** Extraction emits observations. The projector — running at run completion, never inside the per-URL hot path — is the only writer of canonical graph storage. Extraction has no database access to graph tables. This keeps extraction a pure function of `(page, frozen contracts)` and makes its output reproducible and testable.

**The freeze rule.** At run creation, the run snapshots the current graph site-version and the matching extraction contracts into the run's runtime snapshot. The whole run extracts against that frozen view. Concurrent graph updates from other runs cannot change a run's behavior mid-flight.

---

## 4. The PostgreSQL graph model

### 4.1 Why PostgreSQL, not Neo4j

CrawlerAI already runs on PostgreSQL with SQLAlchemy 2 async, Alembic, and JSONB throughout. The commerce graph is shallow and predictable — `domain → page → product → variant → offer`, two to four hops — and the dominant workload is **transactional crawl coordination**, not arbitrary deep traversal. Recursive CTEs cover category ancestry, provenance chains, and bounded neighbourhoods.

Neo4j becomes justified only when several of these are *measured* (not assumed): primary queries routinely traverse five-plus unpredictable hops; interactive exploration over millions of nodes; graph algorithms (community detection, centrality, link prediction); Cypher is materially simpler than the equivalent SQL; or PostgreSQL traversal misses an agreed latency target. Until then, a second database only buys dual-write inconsistency, reconciliation jobs, and split backups.

**Decision:** PostgreSQL is authoritative and the only graph store. Design the model cleanly enough that it *could* be projected into Neo4j later as a rebuildable read model — but do not add the second database speculatively.

### 4.2 Tables

- **`kg_site_versions`** — per domain: current version, last projected run, projection status. The freeze anchor.
- **`kg_entities`** — globally typed UUID nodes: `entity_type`, `canonical_key`, `canonical_name`, JSONB `properties`, `status`, `first_seen_at`, `last_seen_at`. Unique on `(entity_type, canonical_key)`.
- **`kg_relationships`** — typed edges: `source_entity_id`, `target_entity_id`, `relationship_type`, JSONB `properties`, `confidence`, validity window, `status`. Indexed by source and by target.
- **`kg_claims`** — versioned facts: `entity_id`, `fact_type`, JSONB `value`, value hash, `confidence`, `status`, `selection_origin`. Preserves *what was observed*, not only the winning edge.
- **`kg_assertion_evidence`** — normalized, bounded provenance attached to exactly one claim or relationship. Uses `ON DELETE SET NULL` references so evidence survives a crawl reset.
- **`kg_extraction_contracts`** — one executable selection per `(template, surface, canonical_field)`: retained candidates, bounded latest values, success/rejection counts, resolver rule, selected source, and `selection_origin`.

### 4.3 Node and edge vocabulary

Node types: `site`, `technology`, `page_template`, `route_pattern`, `canonical_field`, `source_pattern`, `page`, `product`, `offer`, `brand`, `category`, `seller`, `asset`.

Edge types: `SITE_USES_TECHNOLOGY`, `SITE_HAS_TEMPLATE`, `TEMPLATE_MATCHES_ROUTE`, `TEMPLATE_EXPOSES_FIELD`, `SOURCE_PROVIDES_FIELD`, `PAGE_INSTANCE_OF_TEMPLATE`, `PAGE_MENTIONS_PRODUCT`, `PRODUCT_HAS_OFFER`, `PRODUCT_MADE_BY`, `PRODUCT_IN_CATEGORY`, `OFFER_SOLD_BY`, `PRODUCT_HAS_ASSET`, `PRODUCT_SAME_AS`.

### 4.4 Product identity (deterministic only)

Identity is resolved in strict order; the first available identifier wins:

1. GTIN
2. Manufacturer + MPN
3. Site-scoped product ID
4. Site-scoped SKU
5. Canonical product URL

Title similarity, vector similarity, and LLM opinion **may only seed non-authoritative candidate edges**. They can never, on their own, create a `PRODUCT_SAME_AS` edge. An authoritative `SAME_AS` requires a deterministic identifier match or explicit operator approval.

### 4.5 Variants are aggregate-only

Individual variant rows are **never** graph entities. The graph stores one canonical variant-set claim per product: axes, count, fingerprint, selected source, and lineage. This keeps the graph from exploding into millions of low-value nodes while preserving the fact that the product *has* a variant matrix.

### 4.6 Vector similarity posture

This plan does not add pgvector. But the prohibition is on **authoritative** use, not on the technique: when vector search is later added for cross-crawl product matching (the Product Intelligence subsystem already does deterministic + optional-LLM candidate matching), embeddings may **generate candidates only**. The pipeline is always: *vectors discover candidates → deterministic identity and evidence confirm → graph stores the confirmed relationship → evidence explains it*. A similarity score is never silently promoted to a `SAME_AS` edge.

---

## 5. Extraction contracts

An extraction contract is the durable, executable answer to *"for this page template and surface, where does each canonical field come from?"*

- **Scope.** A contract is keyed by `(page template, surface, canonical field)`. A template is fingerprinted from normalized route shape, surface, technology signals, stable DOM structure, and source inventory — explicitly excluding volatile content, product values, timestamps, IDs, and counts. Equivalent product detail pages share a template; listing and detail never share one.
- **Content.** Each contract retains all observed source candidates, bounded latest values, success/rejection counts, the resolver rule, the selected source, and the selection origin (`generic`, `operator`, or `llm_proposed`).
- **Operator selection is precedence, not a forced value.** When an operator picks a source for a field, that becomes the *preferred resolver precedence* for matching future templates. It does not overwrite historical records and does not force a value onto a page where that source is absent or invalid.
- **Deterministic fallback.** On every page, the preferred source is validated against the actual evidence. If it is missing or invalid, resolution falls back deterministically to generic collectors. Contract outcomes — hit, miss, fallback, stale-source, override-miss — are recorded in that URL's diagnosis.

This is how setup cost is paid once: the first crawl (optionally aided by the cold-start proposer in §7) establishes the contract; every later crawl of the same template reuses it and only falls back when the page genuinely changed.

---

## 6. Diagnostics & observability

This section is the corrective heart of the feature.

### 6.1 The debt being removed

Today, per URL, the system writes artifacts across **two competing directory layouts**:

```
runs/{id}/pages/<url-hash>.html            ┐  written by LocalArtifactStorage
runs/{id}/pages/<url-hash>.browser.json    │  + persist_run_trace
runs/{id}/pages/<url-hash>.browser.png     │  (the "pages" scheme)
runs/{id}/pages/<url-hash>.trace.json      ┘

runs/{id}/results/{url_result_id}/manifest.json   ┐  written by
runs/{id}/results/{url_result_id}/page.html       │  publish_url_result_artifacts
runs/{id}/results/{url_result_id}/summary.json    │  (the "results" scheme)
runs/{id}/results/{url_result_id}/records.json    │
runs/{id}/results/{url_result_id}/debug.json      │  (non-success only)
runs/{id}/results/{url_result_id}/screenshot.png  ┘

runs/{id}/audit/flags.json
runs/{id}/audit/llm_diagnosis.json
```

This is the debt, named explicitly:

1. **Duplicated content.** `page.html` is written twice per URL, in both schemes. The two schemes are linked only by URL-hash matching, which is fragile.
2. **Two writers, two readers.** No single component owns artifact output, so the layouts drift.
3. **Broken references.** Readers look up `acquisition.json` and `extraction.json` by name; **nothing writes them**. The lookups silently fall back and return `{}`.
4. **Dead provenance contract.** `crawl/review/evidence.py` reads `source_trace` keys (`winning_evidence_ids`, `rejected_candidate_count`, `conflict_count`, `resolver_rule`, `llm_used`) that the writer never sets. The review-evidence view is silently empty for canonical records.
5. **The explanatory data is thrown away.** `ExtractionResult.evidence` — the per-candidate provenance (collector, locator, raw value, normalized value, directness, confidence, rejection flags) — is computed and discarded. `records.json` keeps only winners; `summary.json` keeps decisions whose evidence IDs dereference into nothing; `debug.json` *explicitly strips* evidence, records, and graph, then truncates aggressively.

The net effect is exactly the user-reported failure: the one artifact that could answer *"why is price wrong"* does not exist, so the agent reads raw HTML.

### 6.2 The replacement: three files, one of them self-contained

Per URL result, exactly:

```
runs/{run_id}/results/{url_result_id}/
    page.html        the final rendered HTML
    record.json      the public output (unchanged shape)
    diagnose.json    the complete, self-contained diagnosis
```

**One writer.** A single URL-result publisher emits these three files and nothing else. The `pages/` scheme, `manifest.json`, `summary.json`, `records.json`, `debug.json`, `browser.json`, `trace.json`, screenshots, and the per-run audit duplicates are all deleted. The result-root path *is* the contract — there is no manifest indirection. `manifest_uri` is replaced by the fixed result-root convention.

**`diagnose.json` is self-contained and bounded.** It inlines everything needed to root-cause any field, as text, so the agent reads one file and stops. It never references another file. Specifically, per requested or notable field it carries:

- `status` — one of the existing `FieldEvidenceState` values: `captured_and_resolved`, `captured_but_rejected`, `captured_conflicting`, `source_unavailable`, `not_present_in_captured_sources`.
- the **winning** candidate: collector, locator (JSON pointer / CSS selector / network path), value, rule that selected it.
- the **rejected** candidates: collector, locator, a *truncated* value preview (≈120 chars, as `RunTrace` already does), and the rejection reason.
- any **firewall action** that removed or rewrote the field, using the firewall's own reason vocabulary (`availability_outside_public_enum`, `concatenated_url`, `unsafe_navigation_url`, `field_not_allowed_for_surface`, `invalid_field_shape`, …).
- for variants: every dropped variant row with its `(row, stage, rule, reason)`.
- **collector outcomes**: `ran` / `skipped` / `no_match` / `produced_evidence` / `failed` / `timed_out`.
- **stage outcomes** and, when contracts are in play, **contract outcomes** (hit / miss / fallback / stale-source / override-miss).

Boundedness keeps the file small: only requested fields plus fields that are missing, rejected, or conflicted get full candidate detail; cleanly-resolved single-source fields get one line. A complex variant product still produces a few KB — smaller than any single artifact file today, and it is the *only* file the agent opens.

**The reason taxonomy is shared, not reinvented.** `diagnose.json` reuses the `FieldEvidenceState` names and the two firewalls' existing reject reasons verbatim. No parallel vocabulary.

### 6.3 Run-level `report.json`

One `report.json` per run groups root causes across URLs and links directly to each URL's `diagnose.json`. It exists so a run can be triaged in seconds:

> "5 URLs hit `availability_outside_public_enum`, 2 hit `concatenated_url`, 1 hit `MISSING_CONTRACT_FIELD` → see results/{id}/diagnose.json."

It groups by root cause, not by URL, because the operator's question is "what broke and how many times," not "walk me through 200 URLs."

### 6.4 What we deliberately give up

Inlining bounded evidence delivers **root-cause diagnosis** without reading HTML or code. It does **not** preserve enough to **replay** extraction offline for fields sourced from network XHR payloads, because those payloads are not in `page.html` and are no longer persisted. This is an accepted trade: replay is a rare, separate capability and does not justify per-URL artifact sprawl. If replay is needed later, it is added as an explicit, opt-in capture mode — not as default artifacts everyone pays for and the agent ignores.

---

## 7. LLM posture

The codebase already contains a complete LLM stack — five providers (Anthropic, Groq, Mistral, Nvidia, OpenRouter), per-run budget, caching, circuit breaker, cost logging — plus three **dormant** tasks (`extract_records_directly`, `extract_missing_fields`, `review_field_candidates`) that are wired but never called, and an observe-only flagged-run diagnosis. **No LLM call participates in normal crawl extraction today.**

The decisions for this feature:

- **Runtime extraction stays LLM-free.** Nondeterministic, slow, expensive, and unnecessary — the deterministic pipeline already covers the common surfaces. No LLM in the per-URL hot path. No LLM-authoritative claims or `SAME_AS` edges, ever.
- **LLM is allowed in cold-start setup only.** The right niche for an LLM is the *one-time* discovery of a site's extraction contract — paid once per new `(domain, surface, template)`, then reused deterministically forever. A cold-start proposer can:
  - confirm surface and platform family,
  - enumerate likely sources per requested field (JSON-LD path, network endpoint, DOM anchor),
  - propose CSS selectors with sample matched values, verified against the captured page.

  Its output is **deterministic config**: a `kg_extraction_contract` row marked `selection_origin = llm_proposed`, **never auto-activated**. An operator promotes it through the contracts API. The runtime that consumes the contract never calls an LLM. This reuses the existing dormant `review_field_candidates` task and the existing budget/cache infrastructure, so cost is bounded and observable.

This makes "we don't use LLM" a precise statement — a deliberate **runtime** choice — rather than a blanket refusal that forfeits the one place an LLM genuinely lowers setup cost.

---

## 8. Invariants

- PostgreSQL is authoritative. No Neo4j, no Apache AGE, no synchronous dual writes.
- Knowledge Graph is greenfield. No Domain Memory or legacy-artifact migration or backfill.
- Workspace reset and Domain Memory reset preserve the Knowledge Graph. Graph purge is explicit and does not touch Domain Memory.
- Every run freezes graph version and matching contracts before processing.
- Extraction emits observations and never writes canonical graph storage.
- Site knowledge is scoped by page template plus surface.
- Every canonical field exposes accepted and rejected source candidates, the selection rule, and evidence.
- Operator source selection changes matching future runs without rewriting historical records.
- Product identity is deterministic. Title, vector, and LLM similarity cannot create authoritative `SAME_AS` edges.
- Individual variants are not graph entities; only the canonical variant-set claim persists.
- Every URL result contains exactly `page.html`, `record.json`, and `diagnose.json`. One writer.
- `diagnose.json` is self-contained: root cause is inlined and bounded, never by-reference.
- A run-level `report.json` groups root causes and links to URL diagnoses.
- Generic extraction contains no site-specific adapters or retailer-domain branches.
- LLM never runs in the extraction hot path and never produces authoritative claims.

## 9. Non-goals

- Replacing PostgreSQL, or adding a second database, before a measured traversal bottleneck.
- Migrating operational tables (crawl runs, records, Domain Memory) into the graph.
- Making extraction mutate canonical knowledge entities directly.
- Persisting per-result manifests, duplicate HTML, browser JSON, trace JSON, screenshots, summaries, or debug files.
- Offline replay of network-sourced fields as a default capability.
- LLM in the runtime extraction path.
- Storing individual variant rows as graph entities.

---

## 10. Glossary

- **Surface** — the entity shape a run targets: `ecommerce_detail`, `ecommerce_listing`, `job_detail`, `job_listing`. A frozen fact vocabulary that drives extraction policy, traversal eligibility, and persistence shape.
- **Evidence** — one observed candidate value for one fact: collector, locator, raw value, normalized value, directness, confidence, rejection flags, subject. The atom of provenance.
- **Decision** — the resolution outcome for one `(entity, fact)`: accepted evidence, rejected candidates with reasons, the rule applied, status (`resolved` / `unresolved` / `conflicted`).
- **EntitySet** — the per-page typed graph built from evidence: products, variants, offers, assets. Short-lived; exists only during extraction.
- **FieldEvidenceState** — the per-field classification of why a field is present or absent. The shared vocabulary used in `diagnose.json`.
- **Page template** — a content-stable fingerprint of a page class (route shape + surface + technology + stable DOM + source inventory), excluding volatile values. The scope key for extraction contracts.
- **Extraction contract** — the durable, executable per-`(template, surface, field)` source decision stored in the Knowledge Graph.
- **Domain Memory** — acquisition-owned learning store (selectors, acquisition contract, cookies, feedback, host protection).
- **Knowledge Graph** — extraction-owned, cross-crawl store of contracts, canonical entities, claims, and provenance.
- **Projector** — the run-complete, transactional component that turns extraction observations into graph storage. The only writer of canonical graph tables.
- **Selection origin** — how a contract's chosen source was decided: `generic`, `operator`, or `llm_proposed`.

---

## 11. Provenance of this document

This document supersedes the prior repository-root `knowledge-graph.md`, which was an advisory conversation recommending PostgreSQL over Neo4j. It now lives at `docs/feature specs/site-product-knowledge-graph.md` as the authoritative feature specification. That original recommendation is retained and formalized in §4. The companion execution plan is `docs/plans/site-knowledge-graph-master-plan.md`.
