# Active Plan

**Current:** Final Architecture Debt Burn-Down and Crawl Quality Closure → `docs/plans/final-architecture-debt-burndown-plan.md`
**Status:** IN PROGRESS — FINAL 97-SITE REMEDIATION
**Started:** 2026-06-21
**Current slice:** Slices 1-6 implemented and offline-validated. Slice 7 is complete for offline validation; live 97-site acceptance remains user-owned and pending.

## Queue

- Use `output.json` as the authoritative failing output for this remediation cycle.
- Use stored crawl diagnostics only to trace a listed failure's root cause.
- Do not rebuild, expand, re-audit, or replace the final bug list.
- Slices 1-6 are implemented against generic upstream extraction and resolution boundaries.
- The user authorized end-to-end offline validation on 2026-06-23. Do not run a live crawl or acceptance gate.
- Do not rerun the 97-site crawl during implementation.
- Preserve completed architecture work and previously verified results.
- Fix generic upstream causes only. No site-specific product values, URL exceptions, output patches, or persistence/export corrections.
- Slice 7 offline validation passed: Ruff, Mypy, 404 unit tests, 520 component/regression tests, and focused remediation regressions.
- The cycle remains open only for the user-run 97-site acceptance crawl.

## Final Remaining Scope

1. Blocked-page and shell-record integrity.
2. Brand quality and product-brand association.
3. Title and description quality.
4. Image identity and image quality.
5. Missing-field recovery and incomplete-record truthfulness.
6. Variant boundaries, axes, availability, and pricing.
7. Final offline validation preparation and later user-owned 97-site acceptance crawl.

## Previously Completed

- Slice 3 completed on 2026-06-21: exact verification `83 passed`; changed-file Ruff and mypy passed.
- Slice 4 completed on 2026-06-21: exact verification `75 passed`; full offline unit/component/regression suite passed with `985 passed, 1 deselected`; repo-wide Ruff, Mypy, and Prettier passed.
- Slice 5 completed on 2026-06-21: exact verification `92 passed`; full offline unit/component/regression suite passed with `988 passed, 1 deselected`; repo-wide Ruff, Mypy, and frontend Prettier passed.
- Slice 6 completed on 2026-06-21: exact verification `82 passed`; backend Ruff and scoped Mypy passed; frontend typecheck, lint, and Prettier check passed.
- Slice 7 completed on 2026-06-21: exact verification `89 passed`; immutable provenance writes retired from publish/review/accepted-field paths.
- Slice 8 completed on 2026-06-21: exact verification `101 passed`; batch runtime is 637 LOC and crawl long-function debt entries were removed.
- Slice 9 completed on 2026-06-23: exact focused verification `52 passed`; scoped Ruff and Mypy passed.
- Slice 10 completed on 2026-06-23: one acquisition-contract coverage regression fixed in the owning field-policy/profile path; exact focused verification `183 passed`; canonical enrichment/intelligence LOC and architecture gates pass.
- Slice 11 completed on 2026-06-23: exact focused verification `29 passed`; LLM runtime/circuit/config behavior remains green.
- Slice 12 completed on 2026-06-23: `1,120 passed` across the complete offline unit/component/regression selection; backend Ruff passed; Mypy passed for `314 source files`; frontend Prettier, typecheck, and lint passed after formatting the 25 user-authorized files.
- Slice 13 failed on 2026-06-23 using the user-supplied latest 97-site crawl result. Parsed evidence contains 92 records; audit summary saved to `backend/artifacts/test_sites_acceptance/20260623__97_site_gate_audit.json`. The plan remains active and Q1-Q8 are reopened.
- Slice 2 completed on 2026-06-21: exact verification `247 passed`; changed-file Ruff and mypy passed. Recursive acquisition LOC remains above the final package budget and is recorded in the active plan.
- `docs/plans/final-architecture-improvement-plan.md` was superseded on 2026-06-21. Verified results and unresolved debt were audited into the active standalone plan.
- The Full Backend Extraction Rebuild plan was superseded on 2026-06-19. Live acceptance now belongs only to Slice 13 of the active plan.
