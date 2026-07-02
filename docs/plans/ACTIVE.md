# Active Plan

**Current:** Extraction Correctness Overhaul — Clean Foundation → Compiled Recipes → Learned Fallback → `docs/plans/crawlerai-adaptive-extraction-v2-plan.md`
**Status:** IN PROGRESS — Phase 0 complete; Phases 1–7 expanded into decision-complete slices; next step is Phase 1 implementation
**Started:** 2026-07-02
**Notes:** Single authoritative extraction roadmap. Corrected sequence: Phase 0 clean foundation & baseline (delete dead LLM paths + post-extraction repair, consolidate the five overlapping recipe/memory stores to one, split the mega test suite, replace the `ast.unparse` LOC ratchet with physical LOC, freeze deterministic baseline, define evaluation + grounded-label schema) → 1 deterministic contracts → 2 real compiled recipe fast path → 3 operator correction & labels → 4 offline ML research & evaluation → 5 evaluation-gated runtime ML fallback → 6 Sentinel → 7 grounded LLM repair. Debt deletion required every phase. Product/ops/governance deferred to `CrawlerAI_Deferred_Product_Operations_Architecture.md`. Prior extraction plans are retired and intentionally not referenced. Phase 1 implementation has not started.
