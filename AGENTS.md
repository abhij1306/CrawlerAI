# AGENTS.md — CrawlerAI Session Bootstrap

Speak tersely in caveman style: short, direct, low-fluff sentences; keep technical accuracy and full task context.

For trivial work that needs no substantive reasoning—running tests, formatting, or straightforward documentation updates—delegate to GPT-5.4 mini when model delegation is available. Keep reasoning-heavy implementation and debugging on the primary capable model.

---

## What This Project Is

CrawlerAI is a deterministic crawl, extraction, review, and export system for ecommerce, jobs, automobiles, and tabular targets.

- Backend: FastAPI + PostgreSQL + Redis + Celery + Playwright
- Frontend: React + Vite+
- Extraction order: adapter -> structured source -> DOM
- LLM is opt-in backfill only, never the primary extractor

---

## Default Startup Flow

Before coding:

1. Identify the owning area from `docs/CODEBASE_MAP.md` if file ownership is unclear.
2. Read only the canonical doc that matches the task.
3. Grep before adding code: `grep -r "concept_or_function_name" backend/app`

Do not read every project doc by default.
Read more only when the task crosses subsystem boundaries or changes shared behavior.

---

## Read-On-Demand Guide

Read these only when relevant:

- `docs/INVARIANTS.md`
  Read for extraction, acquisition, persistence, selector memory, LLM gating, config placement, or any shared runtime contract.
- `docs/CODEBASE_MAP.md`
  Read when ownership is unclear, when moving files, or before creating a new file.
- `docs/BUSINESS_LOGIC.md`
  Read when changing user-visible behavior, run shaping, verdicts, routing, review flows, or output semantics.
- `docs/ENGINEERING_STRATEGY.md`
  Read when refactoring, adding structure, or touching shared architecture. Pay attention to AP-12 through AP-15.
- `docs/agent/SKILLS.md`
  Read when the task matches an existing recipe.
- `docs/backend-architecture.md`
  Read for backend subsystem detail not covered above.
- `docs/frontend-architecture.md`
  Read for frontend structure or UI flow changes.
- `docs/agent/PLAN_PROTOCOL.md`
  Read only when creating or repairing a plan.

---

## Always-On Rules

1. Config does not live in service code.
   Strings, thresholds, tokens, field names, and runtime tunables belong in `app/core/config/*`.

2. Fix upstream, not downstream.
   Do not compensate in `publish/*`, `pipeline/*`, or exports for bugs caused in acquisition or extraction.

3. Grep before adding.
   Extend or consolidate existing code before creating a new function, class, file, or config source.

4. One concern, one owner.
   If a change does not clearly belong to an existing subsystem, stop and identify the owning file from `docs/CODEBASE_MAP.md`.

5. Delete before adding.
   Remove duplication, dead branches, compat shims, or now-redundant logic as part of the change.

6. Add architecture only when it improves generic coverage.
   Do not add new layers, abstractions, or pipelines for one site unless the user explicitly asks for a site-specific solution.

7. Respect explicit user controls.
   Do not silently rewrite `surface`, traversal intent, proxy settings, or `llm_enabled`.

8. LLM is explicit and degradable.
   It only runs when enabled by both run settings and active config. It fills gaps; it does not replace deterministic extraction.

9. Do not attach stale docs.
   Ignore archived audits and abandoned plans unless the task explicitly asks for historical review.

---

## Extraction Warning


If the task is about missing ecommerce variants or price gaps, read `docs/INVARIANTS.md` Rule 3 first.
Known root causes already documented there:

- early exit before DOM tier when variant DOM cues exist
- JS state mapper returning after the first object
- backfill calls skipped on early return paths

Fix those in place before adding browser interaction or downstream fallbacks.

---

## Plans

- Do not check plan files by default.
- Read `docs/plans/ACTIVE.md` only when the user explicitly asks for plan work.
- If the active plan is `COMPLETE`, do not keep treating it as active work.
- A slice is not done until its verify step passes.
- Do not open a new plan for a problem already covered by an unverified plan.

---

## Quick Task Routing

- Small/local bugfix or UI tweak:
  Inspect code directly. Open docs only if ownership or behavior is unclear.
- New behavior or contract change:
  Read `docs/BUSINESS_LOGIC.md` and any relevant section of `docs/INVARIANTS.md`.
- Refactor or file creation:
  Read `docs/CODEBASE_MAP.md` and `docs/ENGINEERING_STRATEGY.md`.
- Extraction/acquisition bug:
  Read `docs/INVARIANTS.md`, then `docs/agent/SKILLS.md` if needed.
- Plan work:
  Read `docs/plans/ACTIVE.md` and the pointed plan file. Open `docs/agent/PLAN_PROTOCOL.md` only if the plan needs to be created or repaired.

---

## Verify Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\path\to\relevant_test.py -q
.\.venv\Scripts\python.exe -m ruff check .

cd ..\frontend
vp test app/domain-memory/page-view.test.tsx
vp check --fix
vp build
```

Backend verification uses focused pytest files only. Do not run broad `pytest tests -q`
unless the user explicitly asks for a full backend sweep.

Frontend tooling is VitePlus. Use direct `vp` commands:
`vp test <path>`, `vp check --fix`, and `vp build`.
Do not use npm wrappers. Do not use Jest flags such as `--runTestsByPath` or `--runInBand`.

Do not run smoke scripts. Do not add or run fixture/corpus replay gates unless the
user explicitly asks for corpus work.
