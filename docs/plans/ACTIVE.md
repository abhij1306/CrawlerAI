# Active Plan

No active plan.

## Queue
1. LOC and Complexity Reduction from Duplication Audits → `docs/plans/loc-complexity-reduction-plan.md` — blocked on external extraction smoke DNS/browser failure
2. Agentic Browser Playground → `docs/plans/agentic-browser-playground-plan.md` — queued, not yet started

## Previously Completed
- Core Architecture Production Hardening → `docs/plans/core-architecture-production-hardening-plan.md`
  (DONE 2026-06-11; core-only architecture hardening; private reach-ins removed from pipeline, Product Intelligence, and detail identity tests; fetch compatibility shim removed; config export magic reduced; backend `pytest tests -q` 1364 passed)
- Site-Link Category Discovery for Crawl Studio → `docs/plans/site-link-category-discovery-plan.md`
  (DONE 2026-06-04; shared Crawl Studio category discovery API; static sitemap/homepage first, rendered DOM site-link fallback; Playground consumes shared contract; backend `pytest tests -q` 1326 passed; frontend lint passed; frontend vitest 133 passed)
- Self-Healing Observability & Run-Audit Layer → `docs/plans/self-healing-observability-plan.md`
  (DONE 2026-05-30; Phase 1: trace + honest artifacts + audit + baseline; Phase 2: LLM diagnosis + frontend tab + full verification; obs tests 56 passed, vitest 127 passed)
- Product Discovery Identity-Anchor Rework (deterministic, No LLM) → `docs/plans/product-discovery-identity-anchor-plan.md`
  (DONE 2026-05-30; live-verified on real Nike Promina product; full backend suite `pytest tests -q` = 1174 passed; Slices 1–5 all DONE)
