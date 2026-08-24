# Engineering Strategy

## Purpose

Engineering constraints for CrawlerAI. Defines how code should be shaped and how to change it without reintroducing bloat.

`AGENTS.md` — session bootstrap and operator guide.
`INVARIANTS.md` — hard runtime contracts with violation signatures. Read it first.
`BUSINESS_LOGIC.md` — product decision points and owning files.
`CODEBASE_MAP.md` — file-to-bucket orientation map.

---

## Core Principles

**KISS** — Prefer explicit data flow. Prefer a few local conditionals over framework-like abstractions. Code must be traceable in one grep session.

**DRY** — Deduplicate only when the duplicated logic is genuinely the same rule. Do not create fake "shared" helpers that mix unrelated concerns.

**SOLID, practically** — One subsystem has one obvious owner. Facades stay small and stable. Downstream code depends on contracts, not upstream internals.

**YAGNI** — Do not add speculative plugin systems, ranking layers, policy engines, or adapter frameworks. Build only what the active product surface requires.

---

## Backend Ownership Model

| # | Bucket | Primary Files |
|---|--------|---------------|
| 1 | API + Bootstrap | `app/main.py`, `app/api/*`, `app/core/*` |
| 2 | Crawl Ingestion + Orchestration | `app/crawl/*`, `app/workers/*` |
| 3 | Acquisition + Browser Runtime | `app/acquisition/*`, `app/core/url_safety.py` |
| 4 | Extraction | `app/extraction/*`, `app/core/records/*` |
| 5 | Publish + Persistence | `app/persistence/*`, `app/crawl/pipeline/persistence.py` |
| 6 | Review + Selectors | `app/crawl/review/*`, `app/core/records/selectors_runtime.py`, `app/crawl/domain_memory_service.py` |
| 7 | LLM Admin + Runtime | `app/connectors/llm/*` |
| 8 | Data Enrichment | `app/api/data_enrichment.py`, `app/enrichment/*`, `app/models/data_enrichment.py` |
| 9 | Extraction Memory | `app/persistence/extraction_memory.py`, `app/api/knowledge.py`, `app/models/extraction_memory.py` |

Config tunables for all buckets → `app/core/config/*`

**If new code does not clearly belong to one bucket, stop and decide before writing.**

---

## Non-Negotiable Design Rules

1. **One obvious home per concern.** `config/field_mappings.py` is the single location for all field aliases. `field_policy.py` owns field eligibility. `crawl_fetch_runtime.py` owns fetch behavior. `crawl_engine.py` is the extraction facade.

2. **Generic code stays generic.** Platform-specific behavior goes in `app/connectors/*` provider modules or declarative `app/core/config/platforms.json`; product-detail pages still use normal acquisition/extraction. Specs and tunables go in `app/core/config/*`.

3. **Architecture must stay grep-friendly.** A failure must be traceable to one subsystem in one grep session. Avoid new layers whose main effect is hiding the call path.

4. **Strong contracts beat clever internals.** Typed boundaries and named objects over tuple returns and positional argument growth.

5. **Fix upstream, not downstream.** When extraction produces a bad field value, fix the extractor or config that produces it. Never add compensating normalizers in `publish/` or `pipeline/`.

---

## Anti-Patterns

These are patterns that have actually appeared in this codebase.
They are listed so agents recognize and stop them — not just understand the principles above in the abstract.

### AP-1: Inline config
Adding `TIMEOUT = 30` or `PLATFORM_RETRIES = 3` directly in service/extractor code.
**Fix:** Move to `app/core/config/` and import it.

### AP-2: Downstream compensation
Adding a fallback in `publish/verdict.py` or `pipeline/persistence.py` to handle malformed field values that should have been caught upstream.
**Fix:** Trace the bad value to its source and fix it there.

### AP-3: Cross-bucket field aliases
Defining field alias dicts in `detail_extractor.py` or `listing_extractor.py` separately from `config/field_mappings.py`.
**Fix:** All aliases live in `config/field_mappings.py` — surface-specific sections, one file.

### AP-4: Hardcoded platform names in generic paths
`if "shopify" in url` or `if "greenhouse" in host` inside `crawl_fetch_runtime.py`, `crawl_engine.py`, or any generic service.
**Fix:** Platform detection belongs in declarative `app/core/config/platforms.json` or a concrete connector module. Generic runtime paths must not branch on platform names.

### AP-5: New cross-cutting layer
Creating `manager.py`, `registry2.py`, `helpers.py`, or `utils_new.py` instead of placing code in the existing subsystem.
**Fix:** Find the owning bucket file and extend it, or split the existing file by responsibility.

### AP-6: Dead compat shims
Re-export stubs left behind after a migration.
**Fix:** Delete the old location entirely when the migration is done.

### AP-7: Private-function test coupling
Tests that import private functions or constants from service internals.
**Fix:** Delete these tests. Write contract tests that assert observable behavior from public APIs.

### AP-8: Speculative feature addition
An agent adds caching, a plugin hook, or a new abstraction layer that was not in the task scope.
**Fix:** YAGNI. Build what the active plan requires.

### AP-9: Duplicate variant/listing normalization
The same normalization or deduplication logic written in both `detail_extractor.py` and `listing_extractor.py`.
**Fix:** Identify which extraction stage owns it and remove the duplicate.

### AP-10: `LLM_TUNING` / config that bypasses env
A dict or constant inside a service module that silently overrides env-controlled settings.
**Fix:** All runtime tunables come from `config.py` via environment.

### AP-11: Parallel config sources for one runtime rule
The same endpoint tokens, thresholds, or classifier hints defined in two different config modules.
**Fix:** One canonical config owner. Derive any stage-specific views from it.

### AP-12: Repairing resolved data after the evidence graph

The canonical ecommerce-detail path is Harvest → representation-only normalization → entity graph → target selection → Resolve → Publish → verdict. Each concern has one owner.

**Violation looks like:** publication, persistence, or export rewrites titles, drops brands, repairs SKUs, filters cross-product variants, normalizes raw availability tokens, or chooses replacement assets after resolution. Publish searches unrelated entities for a value that the resolver did not select. HTTP success is reported as clean data despite unresolved identity, offer, asset, or variant conflicts.

**Fix:** keep normalization representation-only; reject or flag bad evidence during Resolve; correct product/offer/variant/asset links in entity construction; select the primary product before resolution; record accepted/rejected evidence in resolver decisions; create explicit selected/derived facts with lineage; let Publish serialize only authorized projection entries and fail closed on projection divergence. Keep `transport_outcome`, `data_integrity`, and field evidence states separate.

Artifact regressions must replay stored HTML and captured network payloads through the real pipeline. A gate based only on old `records.json`, manually assigned fixed status, or fixture-specific expected output is not sufficient.

Generic network payloads are untrusted until linked to the selected product. Ad, feed, recommendation, analytics, and sibling-product roots must not create canonical product fields, variants, offers, or assets without same-product URL, id, SKU, or selected-root evidence.

### AP-13: Config proliferation ← SECOND MOST COMMON
Creating a new `constants.py`, `config.py`, or inline dict inside a bucket folder
because "there was no obvious place" to put a constant.

**Violation looks like:** `extraction/constants.py`, `acquisition/config.py`, a `FIELD_NAMES = [...]` dict at the top of extraction runtime code.

**Fix:** Before creating any config-like file or constant, grep `app/core/config/` for an appropriate home. The correct home almost always exists. If it does not, extend the nearest file — do not create a new one without explicit confirmation.

### AP-14: Plan burial — writing plans without executing them
Creating plan documents, audit reports, and remediation specs without running a verification test afterward.
This accumulates dead work that future agents misread as authoritative guidance.

**Violation looks like:** More than 3 plan files in `docs/plans/` with status `IN PROGRESS` simultaneously. An audit doc in `docs/audits/` with findings that were never closed by a passing test run. A plan slice marked DONE with no verify command logged.

**Fix:** Close plans before opening new ones. Archive audit docs that are older than the last passing test run — their findings are either fixed or irrelevant. If a plan was abandoned, mark it explicitly `ABANDONED` and note what was verified vs what was not. Do not build on top of unverified work.

### AP-15: Grep skip — creating before searching
Writing a new function, class, or module without first confirming no existing implementation covers the case.

**Violation looks like:** Two price-cleaning functions in different files. A new `normalize_price()` written because `field_value_price.py` "seemed complex." A new URL validator added alongside `url_safety.py`.

**Fix:** Always run `grep -r "function_name_or_concept" backend/app` before writing new code. If a similar function exists, extend it. If it is too complex to extend safely, the complexity is the real bug — fix that first.

### AP-16: Detail expansion clicks site chrome
Allowing generic detail-expansion probes to click header/nav/footer controls, marketing promos, or app-assistant entry points during a PDP fetch.

**Violation looks like:** A requested product URL finishes on `about`, `AI`, `wishlist`, `homecare`, or other utility/marketing content because the expansion pass clicked outside main content. Browser diagnostics show `usable_content`, but extraction returns shell metadata or a wrong-page identity.

**Fix:** Expansion candidates must prefer in-page/main-content controls. Skip header/nav/footer chrome and real navigation links unless they are proven in-page expanders for the requested detail content.

### AP-17: Cross-module private reach-in
Importing underscore-prefixed names from another service module because "the helper already exists there."

**Violation looks like:** `extraction_runtime.py` imports `_finalize_listing_price_fields` from `listing_extractor.py`. `crawl_fetch_runtime.py` imports `_display_proxy` from `browser_runtime.py`. A facade or runtime module reaches into another module's internals instead of promoting a real owner API.

**Fix:** Either keep the logic inside the owner and call a public function, or promote the helper into the canonical owner file for that concern. If callers need the behavior, expose a non-underscore API from the owner. Private imports that already exist must be treated as explicit debt with a shrinking allowlist in `backend/tests/services/test_structure.py`. No new private cross-module imports.

### AP-18: Product taxonomy bloat
Adding local product-universe dictionaries for enrichment categories, materials, colors, sizes, or category synonyms instead of using Shopify's taxonomy and attribute files.

**Violation looks like:** `DATA_ENRICHMENT_TAXONOMY_TOKEN_ALIASES`, `matching sets -> outfit sets`, a growing list of material names in config, or a color catalog copied into service code.

**Fix:** Use canonical config data at `backend/app/data/enrichment/shopify_categories.json` for category paths and category attribute handles, and `backend/app/data/enrichment/shopify_attributes.json` for Shopify-defined attribute values. Put service logic in `backend/app/enrichment/shopify_catalog.py` and use it to improve generic matching mechanics (taxonomy paths, category attribute handles, normalized tokens). Local config may strip UI noise or define source-field lookup, but it must not become a shadow product taxonomy. Owner: `enrichment/` subsystem.

### AP-19: Duplicate public-field cleanup helpers
Adding per-field cleanup in adapters, enrichment, exports, or UI because a bad `barcode`, `gender`, `brand`, `product_type`, or structural title leaked through.

**Violation looks like:** barcode cleanup in export code, brand suffix stripping in enrichment, or another SKU prefix scrubber outside the public-field coercion owner.

**Fix:** Public field validation and final coercion stay in the single boundary owner (`field_value_core.py` / `FieldCoercion`). Extend that owner and delete the duplicate helper.

### AP-20: Synthesizing parent fields from `selected_variant`
Backfilling parent `price`, `currency`, `availability`, `color`, `size`, or `image_url` from a synthetic `selected_variant` record instead of extracting parent fields directly and flattening public variants separately.

**Violation looks like:** `_refresh_record_from_selected_variant`, parent price chosen from a synthetic active variant row, or UI/export contracts that require `selected_variant` to understand a product.

**Fix:** Parent detail fields are extracted directly. Public variants are flat rows plus `variant_count`. Remove `selected_variant` dependencies instead of compensating for them.

### AP-21: Import-time globals mutation from exported config

Loading JSON config and writing each key into `globals()` makes config invisible to static analysis and easy to break silently.

**Violation looks like:** `for name, value in exports.items(): globals()[name] = value` in `app/core/config/*`.

**Fix:** Keep exported config in an explicit typed mapping, define code-owned constants directly, and expose compatibility values through deliberate module `__getattr__`/`__all__` only when needed.

### AP-22: Blanket lint muzzle

Disabling Pylint's size, complexity, duplicate-code, or function-doc checks globally turns the lint config into decoration.

**Violation looks like:** `too-many-branches`, `too-many-statements`, `too-many-lines`, or `duplicate-code` in the global disable list.

**Fix:** Set realistic design thresholds, add focused local suppressions only when justified, and prefer structure tests for project-specific architecture limits.

### AP-23: Context-free root assets

Binary assets in the repository root become mystery blobs and make README/docs coupling hard to understand.

**Violation looks like:** `image.png` or another binary image committed at repo root with no descriptive path.

**Fix:** Move assets under `docs/assets/` or the owning frontend/static asset folder with a descriptive filename, then update references.

### AP-24: Direct extraction-memory writes

Writing templates, recipes, manifests, labels, or observations from extraction collectors or the extraction engine couples deterministic extraction to mutable storage.

**Violation looks like:** `app/extraction/*` imports extraction-memory models/repository, or a collector updates a recipe while resolving the current page.

**Fix:** Extraction emits immutable evidence, decisions, and contract outcomes. `app/persistence/extraction_memory.py` records observations after extraction; `app/api/knowledge.py` owns explicit operator refinement.

### AP-27: Parallel learned-state stores

Selectors, contract choices, review promotions, feedback, and run manifests in separate stores drift and produce conflicting runtime truth.

**Fix:** Persist all learned structural state through `models/extraction_memory.py`. Acquisition-only run profiles, cookies, and host protection stay separate.

### AP-28: Normalized-AST LOC ratchets

`ast.unparse()` line counts hide physical module size and can report less than half the maintained source surface.

**Fix:** Count nonblank physical lines and pair the budget with explicit Radon cyclomatic-complexity debt.

### AP-29: Mega test modules

Multi-thousand-line suites obscure ownership and make focused verification impossible.

**Fix:** Split by public behavior owner. Shared fixture vocabulary may live in a non-test support module; preserve collected behavior count during the split.

### AP-30: Honest maintainability gates

Backend test and tool complexity is measured with `radon.complexity.cc_visit`; a callable fails only when its exact complexity is greater than 15. Backend test/tool and frontend test LOC use nonblank physical lines with no formatting normalization. Aggregate LOC is a no-regression ratchet: changing it requires an explicit ownership rationale, not silent headroom. Large cohesive files are review signals, not automatic failures.

The only maintainability-LOC structural exclusion is `backend/alembic/versions/**`, because applied migrations are immutable schema history. Migration correctness remains covered by Alembic head, upgrade, and drift checks. Application code, tests, harnesses, root scripts, and browser probes receive no exclusion.

Frontend test callables use ESLint's `complexity` rule at 15. Backend CI runs Ruff over the full backend tree, the architecture gates through pytest, and frontend CI runs VitePlus lint/types plus all architecture policies before build.

### AP-31: Identity mutation during service startup

Creating, promoting, reactivating, or resetting a user from API lifespan makes
every restart an authorization write and turns a reused email into privilege
escalation.

**Fix:** Migrations and initial-admin creation are explicit one-off deployment
commands. Bootstrap is create-only, serialized by a durable consumed marker,
fails on an existing identity, and never runs from API or worker startup.

### AP-32: Shell-owned deployment configuration

Building DSNs in Compose, workflows, or shell scripts duplicates escaping
rules and breaks on real credentials. Overriding an image with a bare binary
also assumes an unowned `PATH`.

**Fix:** Central config accepts a complete URL or composes encoded deployment
components. Manifests pass components/URLs as values, invoke `.venv/bin/*`,
and keep migration, bootstrap, API, worker, and scheduler as distinct process
contracts.

### AP-33: Build toolchains in runtime images

Shipping compilers, headers, curl, or an unlocked dependency resolver increases
the production attack surface and makes the deployed artifact diverge from its
lockfile.

**Fix:** Pin every base image by digest. Build dependencies and browser binaries
in earlier stages. Copy the locked virtual environment into a non-root runtime
stage containing only application and browser runtime libraries.

### AP-34: Advisory-only release scanning

A scanner that uploads a report but cannot stop promotion is observability, not
a release gate. Treating missing or incomplete scan data as clean is fail-open.

**Fix:** Gate immutable image digests. Block fixable and unclassified
High/Critical findings. Keep no-fix risk acceptance false by default and require
an explicit reviewed reference. Publish sanitized SBOM/scan evidence.

### AP-25: Parallel artifact layouts

Writing URL diagnostics through more than one publisher creates conflicting forensic records and stale readers.

**Violation looks like:** both `runs/{id}/pages/...` and `runs/{id}/results/{url_result_id}/...`, duplicate HTML writes, manifests that point to files no writer emits, or a second diagnostic vocabulary.

**Fix:** The URL-result publisher writes exactly `page.html`, `record.json`, and self-contained `diagnose.json` under the result root. Run reporting reads those diagnoses and writes only `report.json`.

### AP-26: Retailer branches in generic extraction

Host or retailer names inside generic extraction turn shared fixes into site-specific behavior and hide missing evidence rules.

**Violation looks like:** `if host == "retailer.example"` in `app/extraction/*`, domain-specific selector fallbacks, or retailer adapters that bypass normal evidence and resolution.

**Fix:** Improve generic collectors, field mappings, or evidence resolution. Keep protocol collectors generic and enforce the domain-literal architecture ratchet.

---

## Required Hygiene Gates

These are mandatory controls, not suggestions.

1. `backend/tests/unit/test_final_architecture_ownership.py` is the backend architecture ratchet.
   It owns LOC budgets, config-placement checks, and the allowlist for private cross-module imports.

2. Any new violation pattern found in an audit must become one of:
   - a focused test gate
   - a tighter LOC budget
   - a smaller explicit allowlist

3. Allowlists are debt ledgers, not parking lots.
   If a private import or exception is removed in code, remove it from the allowlist in the same change.

4. Audit work is not complete until the guard exists.
   Deleting wrappers or moving config without adding the enforcement hook means the drift will return.

---

## Agent Behavior

- Read the owning module and nearby tests before changing behavior.
- Update the canonical doc when you change architecture, ownership, or user-facing contracts.
- Do not create parallel systems because an existing module is awkward; refactor the owner instead.
- Avoid turning docs into changelogs. Capture stable knowledge, not every edit.
- When an audit or plan doc conflicts with code, trust code first, then update the docs.
- After any major implementation: run `pytest tests -q`, update the plan slice, update the relevant doc.

---

## File Shape

- Split by responsibility, not by arbitrary suffixes like `_misc`, `_helpers2`, or `_v2`.
- Large files are acceptable only when they remain coherent, searchable, and clearly owned.
- If a file becomes hard to summarize in one paragraph, it needs a structural split.
- Facade files orchestrate steps; helpers move out once responsibilities diverge.

---

## Testing Rules

Test contracts and invariants, not implementation trivia.

**High-value tests:** crawl creation/normalization, fetch escalation, traversal, listing/detail extraction behavior, source priority ordering, structured-source mapping, selector CRUD, self-heal gating, review save/promote, export/provenance, LLM boundaries and failure handling.

**Low-value tests (delete):** private helper call order, mocks that restate implementation, assertions that freeze harmless refactors, tests that import private constants just to check they exist.

---

## Documentation Rules

| Doc | Job |
|-----|-----|
| `AGENTS.md` | Session bootstrap only. Keep under 200 lines. |
| `CODEBASE_MAP.md` | File-to-bucket map. Update when files move. |
| `BUSINESS_LOGIC.md` | Product decision points and owning files. |
| `ENGINEERING_STRATEGY.md` | Engineering constraints + named anti-patterns. |
| `INVARIANTS.md` | Must-preserve runtime rules with violation signatures. |
| `backend-architecture.md` | Detailed backend reference. |
| `agent/SKILLS.md` | Task recipes. Add as new patterns emerge. |
| `agent/PLAN_PROTOCOL.md` | Plan creation and management workflow. |
| `plans/ACTIVE.md` | Current plan pointer. Always up to date. |

**Audit docs in `docs/audits/`** are read-once forensic artifacts. Once the findings are fixed and verified by a passing test run, archive or delete them. Do not attach stale audit docs to new agent sessions.

**Plan docs in `docs/plans/`** are active working documents only while IN PROGRESS. Abandoned plans must be marked `ABANDONED`. Completed plans are historical. Neither abandoned nor completed plans should be attached to new agent sessions.

---

## Change Workflow

1. Identify owning subsystem from `CODEBASE_MAP.md`.
2. Grep for existing implementations before writing anything new.
3. Read local code and nearby tests first.
4. If non-trivial, create a plan per `PLAN_PROTOCOL.md`.
5. Make the smallest responsible change set. Delete before adding.
6. Add or adjust focused tests.
7. Update the canonical doc if behavior, ownership, or contracts changed.
8. Run verify command. Mark slice done only after verify passes.
