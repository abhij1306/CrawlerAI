# Active Plan

**Current:** Final Architecture Debt Burn-Down and Crawl Quality Closure → `docs/plans/final-architecture-debt-burndown-plan.md`
**Status:** IN PROGRESS
**Started:** 2026-06-21
**Current slice:** Slice 3 — Listing Discovery and Listing Card Integrity

## Queue

- Execute one slice at a time from the active plan; do not repeat its repository-wide audit.
- Do not create another architecture plan for this debt cycle; attach new findings to the owning slice.
- Run the slice's focused offline tests, then stop and record the handoff.
- Run the complete offline unit/component/regression suite only in Slice 12.
- Use `.\backend\.venv\Scripts\python.exe -m mypy --config-file backend\pyproject.toml ...` when type-checking from repo root.
- Never run smoke/live commands. Slice 13 belongs to the user.


## Previously Completed

- Slice 2 completed on 2026-06-21: exact verification `247 passed`; changed-file Ruff and mypy passed. Recursive acquisition LOC remains above the final package budget and is recorded in the active plan.
- `docs/plans/final-architecture-improvement-plan.md` was superseded on 2026-06-21. Verified results and unresolved debt were audited into the active standalone plan.
- The Full Backend Extraction Rebuild plan was superseded on 2026-06-19. Live acceptance now belongs only to Slice 13 of the active plan.
