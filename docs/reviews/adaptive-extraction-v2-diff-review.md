---
reviewed: 2026-07-02
scope: adaptive extraction v2 working tree, Slices 0.1 and 0.3-0.7
status: resolved
---

# Adaptive extraction v2 diff review

## Decisions and resolutions

1. **High — A second misleading LOC ratchet remained.** `test_final_architecture_ownership.py` also used `ast.unparse`, so replacing only the extraction-local gate would leave false global budgets. Selected option: replace both with physical nonblank LOC and explicit Radon complexity debt. Resolved.
2. **High — Selector recipes were initially read live per URL.** This violated immutable run releases and allowed operator edits to change an in-flight run. Selected option: include exact-surface and generic selector recipes in `ExtractionReleaseSnapshot`; workers read selectors only from that release. Resolved with a regression test.
3. **High — Bidirectional run/release foreign keys formed a DDL cycle.** Selected option: retain the release-to-run foreign key and use a typed UUID pointer on `CrawlRun` without a reverse database constraint. This preserves ownership and deterministic teardown. Resolved.
4. **Medium — Unified labels made reset counts/deletes too broad.** A naïve reset treated review promotions and field feedback as the same deletion scope. Selected option: filter by `label_kind` while retaining one table. Resolved.
5. **Medium — Plan metadata still said approval was pending after D1-D4 were approved.** Selected option: mark the active plan in progress and record completed slices explicitly. Resolved.

No unresolved decisions remain for Phase 0. Slice 0.2 was completed in the follow-up request using the architecture spec's grounded-truth requirements.
