# Active Plan

**Current:** Final Architecture Debt Burn-Down and Crawl Quality Closure → `docs/plans/final-architecture-debt-burndown-plan.md`
**Status:** AWAITING VALID 100-SITE GATE INPUT
**Started:** 2026-06-21
**Current slice:** Q0-Q8 and Slices 9-12 complete; Slice 13 cannot execute because the configured acceptance runner resolves zero sites from `TEST_SITES.md` and the default curated site-set manifest is absent

## Queue

- Execute one quality slice at a time from the active plan; do not repeat its repository-wide audit.
- Keep one tracker only. Assign every new output failure a `QD-*` ID in the active plan and attach it to Q1-Q8; do not create another plan.
- Use the frozen 91-record JSON, existing artifacts, and synthetic fixtures for Q0-Q8. Do not run a full catalog after each fix.
- Run focused offline tests per slice, the complete offline unit/component/regression suite only in Slice 12, and one user-owned full live gate only in Slice 13.
- Slices 9-12 are verified. Backend Ruff, Mypy, architecture gates, and the complete offline unit/component/regression suite pass. Frontend Prettier, typecheck, and lint pass after the user-authorized repository formatting pass.
- Use `.\backend\.venv\Scripts\python.exe -m mypy --config-file backend\pyproject.toml ...` when type-checking from repo root.
- Slice 13 was explicitly authorized, but the runner is not currently runnable as a 100-site gate: `parse_test_sites_markdown()` returns zero entries for the raw URL-only `TEST_SITES.md`, and `backend/harness/test_site_sets/commerce_browser_heavy.json` does not exist.

## Quality Reopen

- 2026-06-23: latest supplied catalog contains 91 records and reopens output-quality closure. Baseline: 22 missing availability, 19 missing brand, 17 missing price, 17 missing currency, 6 missing images, 6 missing descriptions, 2 missing titles, 6 exact-320-character descriptions, 10 mixed parent/variant price families, and 1 primary/gallery duplicate.
- Q0-Q8 are the only tracker for the new findings. Earlier Slice 4-6 tests remain valid invariant guards but no longer prove catalog closure.

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
- Slice 2 completed on 2026-06-21: exact verification `247 passed`; changed-file Ruff and mypy passed. Recursive acquisition LOC remains above the final package budget and is recorded in the active plan.
- `docs/plans/final-architecture-improvement-plan.md` was superseded on 2026-06-21. Verified results and unresolved debt were audited into the active standalone plan.
- The Full Backend Extraction Rebuild plan was superseded on 2026-06-19. Live acceptance now belongs only to Slice 13 of the active plan.
