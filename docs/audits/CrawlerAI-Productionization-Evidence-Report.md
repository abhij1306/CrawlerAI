# CrawlerAI Productionization Evidence Report

## 1. Executive Summary

- **Overall readiness:** GO WITH CONDITIONS
- **Readiness for enabling the requested absolute gates (LOC ≤800 and complexity ≤15, blocking CI):** NO-GO until inventory below is cleared. Local lint/format for the commands that were run is already green; the new absolute gates are not.
- **Finding counts:** P0 0; P1 3; P2 18; P3 6. Status: FAIL 22; PASS 8 (tooling/commands that currently succeed); UNVERIFIED 5; N/A 1. Register rows are grouped inventories plus discrete CI/dep/dead-code items, not one ID per oversized function.

**Five most important verified conclusions**

1. The repo already ratchets extraction/app size and complexity in tests, but the ceilings are **700 nonblank LOC allowlisted**, **complexity >20 allowlisted**, and **extraction default CC 20** — not 800 physical lines and not 15. Enabling the requested gates today would fail immediately.
2. **37 first-party files exceed 800 physical lines** (`splitlines()` count). **32 exceed 800 nonblank lines** (the method `test_extraction_architecture.py` / `test_final_architecture_ownership.py` already use). Most violations are **tests** (20) and **extraction** production modules (8).
3. **Radon found 202 callables with CC >15** (169 production, 25 tooling, 8 tests). **80 are >20** (63 production), matching the existing debt ledger style. Peak is `infer_brand_from_product_url` at **86 (grade F)**.
4. **Backend Ruff check, Ruff format --check, and mypy app currently pass** on the commands run. **Frontend `vp check` passes** (oxfmt + oxlint + type-aware). Those checks are **not all in CI**: backend CI has ruff+mypy+pytest+pip-audit but **no format**; frontend CI is Playwright smoke + high audit + build, **no `vp check` / unit tests**.
5. **Frontend is Vite+ (vite-plus 0.2.5, oxlint/oxfmt), not Next.js** despite AGENTS.md. The suitable complexity gate is **oxlint `eslint/complexity`**, already bundled; `vp lint --deny complexity` fails **8 functions at default max 20**. ESLint is not a separate committed config.

**Grader / prior-doc claims**

| Claim | Verdict |
|---|---|
| Next.js frontend | **Disproven** by `frontend/package.json` and `frontend/vite.config.ts` (Vite+ / React Router) |
| Ruff/mypy already in backend CI | **Confirmed** `.github/workflows/backend-ci.yml` |
| Frontend lint/format/unit tests in CI | **Disproven** — only Playwright smoke workflow |
| Vulture/radon as CI gates | **Disproven** — listed in `pyproject.toml` extras only |
| Pylint size/complexity globally disabled | **Confirmed** `backend/pyproject.toml` (AP-22) |
| Existing absolute 800/15 gates | **Disproven** — ratchets are 700/20 with allowlists |
| Archived 2026-07-21 audit (10 files >800, 182 dead symbols) | **Stale** — not used as current evidence; live scan differs |
| pip-audit ignore PYSEC-2025-183 | **Stale/unexplained** — `pyjwt` is not in `uv.lock`; ignore still in CI |
| Local `.venv` has ruff/radon/vulture | **Disproven** — runtime-only venv; tools run via `uvx`/`uv run` |

## 2. Repository and Tooling Baseline

- **Branch:** `main`
- **Commit:** `bfc7663660285a70c88181c18005137d5f738d57` (`bfc76636 Refactor code for improved readability and consistency`, 2026-07-23)
- **Working tree:** clean (`git status --porcelain` empty) at analysis start; this report file is the only intended docs write.

| Area | Detected technology/tool | Version | Configuration path | CI workflow/job | Status | Evidence |
|---|---|---|---|---|---|---|
| VCS | git | n/a | `.git` | n/a | PASS | `git rev-parse` |
| Backend runtime | CPython | 3.12 required; local `.venv` 3.12.13; CI 3.12; system python 3.14.6 unused | `backend/pyproject.toml` `requires-python` | `backend-ci.yml` Setup Python | PASS | pyproject L9; workflow L54 |
| Backend package | setuptools + **uv.lock** | uv.lock revision 3 | `backend/pyproject.toml`, `backend/uv.lock` | CI uses **pip install -e .[dev]** not uv | FAIL | lock unused in CI |
| Backend lint | Ruff | lock 0.15.22; no `ruff.toml` / `[tool.ruff]` | defaults only | `backend` / Ruff | PASS locally | `ruff check app tests` exit 0 |
| Backend format | Ruff format | 0.14.10 checked 552 files | defaults | **absent** | FAIL (CI gap) | format not in workflow |
| Backend types | mypy | 2.3.0 | `[tool.mypy]` pyproject | Mypy job | PASS locally | `uv run --frozen --extra dev python -m mypy app` |
| Backend types (alt) | basedpyright | extra; `pyrightconfig.json` basic/mostly off | `backend/pyrightconfig.json` | absent | N/A | not CI |
| Backend tests | pytest | lock 9.1.1 | `backend/pytest.ini` | Pytest | UNVERIFIED here | not re-run (AGENTS.md focused-only); CI has full `pytest tests -q` |
| Complexity (py) | Radon | 6.0.1 | used in tests via `cc_visit` | absent as gate | FAIL vs ≤15 | this scan |
| Dead code | Vulture | 2.16 | `[tool.vulture] min_confidence=100` | absent | PASS at 100 | one FP |
| Pylint | pylint | extra 4.x | `[tool.pylint.*]` disables size/complexity | absent | FAIL vs AP-22 | pyproject L71-121 |
| Backend audit | pip-audit | CI installs ad hoc | ignore PYSEC-2025-183 | Dependency vulnerability scan | UNVERIFIED vs lock | CI pip-resolve ≠ uv.lock |
| Frontend PM | pnpm | 11.9.0 | `packageManager` | `setup-vp` | PASS | package.json L58 |
| Frontend toolchain | vite-plus / vp | package 0.2.5; CLI vp 0.1.14; oxlint 1.73.0; oxfmt 0.58.0 | `frontend/vite.config.ts` lint/fmt | not used for lint | PASS local `vp check` | vp check exit 0 |
| Frontend lint | oxlint (config keys say `eslint` plugins) | 1.73.0 | `vite.config.ts` `lint` | absent | FAIL (CI gap) | Playwright workflow has no vp lint |
| Frontend format | oxfmt | 0.58.0 | `vite.config.ts` `fmt` | absent | FAIL (CI gap) | |
| Frontend types | TypeScript | ^7.0.2 declared | `frontend/tsconfig.json` strict | via vp check locally only | PASS local | bundled in vp check |
| Frontend unit | vitest via vp | vitest “Not found” as standalone; vp test configured | `vite.config.ts` `test` | absent | UNVERIFIED | not run |
| Frontend e2e | Playwright | 1.61.1 | `playwright.config.ts` | `playwright-smoke` | UNVERIFIED | not run |
| Node | Node.js | engines ≥20.19; CI node 24; local v26.7.0 | package.json engines | setup-vp node-version 24 | PASS | |
| Secret scan | gitleaks | action pin v3 | `.github/workflows/gitleaks.yml` | gitleaks | N/A this review | exists |
| CodeQL | codeql-action v4 | python + js/ts | `codeql.yml` | analyze | N/A this review | exists |
| Dependabot | pip / npm / gha | weekly/monthly | `.github/dependabot.yml` | n/a | PASS | committed |
| Pre-commit | vp staged `vp check --fix` | vite.config `staged` | not a `.pre-commit-config.yaml` | absent | UNVERIFIED | no git hook file found |

## 3. Current CI Quality-Gate Matrix

| Gate | Local command exists | Committed configuration | CI enforced | Blocking | Currently passes | Evidence/gap |
|---|---|---|---|---|---|---|
| Backend lint | Yes: `python -m ruff check app tests` | No ruff.toml; Ruff defaults | Yes `backend-ci.yml` L72-73 | Yes | Yes (this run, ruff 0.15.22) | CI path filter `backend/**` only |
| Backend format | Yes: `ruff format --check app tests` | Ruff defaults | **No** | n/a | Yes locally (552 files, ruff 0.14.10) | Add to backend job |
| Backend type check | Yes: `python -m mypy app` | `[tool.mypy]` | Yes L75-76 | Yes | Yes (381 files, mypy 2.3.0) | notes on untyped bodies only |
| Backend tests | Yes: `pytest tests -q` | pytest.ini | Yes L78-79 | Yes | UNVERIFIED here | CI runs full suite; not re-run |
| Backend LOC ≤800 | Partial: nonblank 700 allowlist in tests | `test_final_architecture_ownership.py`, extraction toml | Indirect via pytest | Yes but **wrong threshold** | FAIL vs 800 | OVERSIZED_MODULE_DEBT |
| Backend complexity ≤15 | Partial: CC>20 allowlist | same tests + extraction toml default 20 | Indirect via pytest | Yes but **wrong threshold** | FAIL vs 15 | COMPLEX_FUNCTION_DEBT; 202 hits |
| Frontend lint | Yes: `vp lint` / `vp check` | `vite.config.ts` lint | **No** | n/a | Yes `vp check` | smoke workflow skips |
| Frontend format | Yes: `vp fmt` / `vp check` | `vite.config.ts` fmt | **No** | n/a | Yes 225 files | smoke workflow skips |
| Frontend type check | Yes: vp check typeAware | tsconfig strict | **No** | n/a | Yes in vp check | |
| Frontend tests | Yes: `vp test`; e2e `playwright` | vite.config test; playwright.config | e2e smoke only | Yes for smoke | UNVERIFIED unit; e2e UNVERIFIED | no unit job |
| Frontend LOC ≤800 | Partial: default 400 + exceptions to 1020 | `scripts/check-frontend-architecture.mjs` | **No** (`check:policy` not in CI) | n/a | FAIL vs 800 (`log-terminal.tsx` 972, `types.ts` 831) | exceptions grandfather >800 |
| Frontend complexity ≤15 | No committed rule | oxlint complexity available | **No** | n/a | FAIL at max 20 already (8 fns) | `vp lint --deny complexity` |
| Dependency audit | Yes | CI pip-audit; frontend `vp pm audit --audit-level=high` | Yes both | Yes | Backend UNVERIFIED (resolver); frontend **FAIL** (3 high) | see §9 |
| Dead-code analysis | Yes vulture extra | min_confidence 100 | **No** | n/a | Yes at 100 (1 FP) | 60% is mostly framework noise |
| Duplication analysis | No committed jscpd config | none | **No** | n/a | 17 clones / 0.18% at min-lines 10 | not a current requirement |

## 4. Files Over 800 LOC

**Counting method (this scan):** UTF-8 `splitlines()` length = **physical lines** (no trailing-newline empty extra). **Nonblank physical** = `bool(line.strip())`, matching `backend/tests/unit/test_extraction_architecture.py:39-42` and `test_final_architecture_ownership.py:166-169`.

**Exclusions applied (from repo ignore patterns + standard artifacts, not invented to pass):** `.venv`, `node_modules`, `__pycache__`, `dist`, `coverage`, `playwright-report`, `test-results`, `.git`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `htmlcov`. Frontend lint/fmt already ignore `dist/**`, `node_modules/**`, `coverage/**`, `test-results/**` (`vite.config.ts` L131-183). Alembic migrations, harness, and `browser_surface_probe` were **not** excluded.

**Summary (physical total >800):** 37 files. By role: test 20, production source 14, script/tooling 3. By subsystem: backend/tests 19, backend/extraction 8, backend/tooling 3, frontend/crawl-ui 2, frontend 1, enrichment 1, intelligence 1, persistence 1, core 1.

**Nonblank >800:** 32 files (the 5 that are >800 total but ≤800 nonblank: `intelligence/service.py`, `extraction/pipeline.py`, `lib/api/types.ts`, `tests/unit/test_evaluation_phase4.py`, `tests/unit/test_crawl_run_95_regressions.py`).

| File | LOC (physical) | Nonblank | Classification | Current responsibility | Suggested split seams | Likely owner/destination | Risk | Related tests | Finding ID |
|---|---:|---:|---|---|---|---|---|---|---|
| `backend/tests/component/test_crawl_fetch_runtime.py` | 4279 | 3720 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_crawl_fetch_runtime.py | Q-LOC-01 |
| `backend/tests/component/test_browser_context.py` | 3639 | 3035 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_browser_context.py | Q-LOC-02 |
| `backend/tests/component/test_product_intelligence.py` | 3213 | 2782 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_product_intelligence.py | Q-LOC-03 |
| `backend/browser_surface_probe/core.py` | 2178 | 2007 | script/tooling | Harness/probe/migration script, not runtime service | Split report rendering vs probe loop vs fixtures; alembic file is a single migration and should stay atomic or be excluded only if classified generated | CODEBASE_MAP support files / alembic | Low-medium | tests/regression/test_harness_support.py, test_browser_surface_probe.py | Q-LOC-04 |
| `backend/tests/regression/test_batch_runtime.py` | 1906 | 1681 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/regression/test_batch_runtime.py | Q-LOC-05 |
| `backend/tests/unit/test_extraction_contract_behavior.py` | 1846 | 1639 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_contract_behavior.py | Q-LOC-06 |
| `backend/harness/support.py` | 1604 | 1463 | script/tooling | Harness/probe/migration script, not runtime service | Split report rendering vs probe loop vs fixtures; alembic file is a single migration and should stay atomic or be excluded only if classified generated | CODEBASE_MAP support files / alembic | Low-medium | tests/regression/test_harness_support.py, test_browser_surface_probe.py | Q-LOC-07 |
| `backend/app/persistence/extraction_memory.py` | 1535 | 1394 | production source | Learn-once recipe compile/persist, release snapshots, drift, knowledge query projections | Split persist/claim/lock vs compile vs knowledge query vs observation recording | persistence/extraction_memory.py (CODEBASE_MAP Bucket 6/9) | High: runtime learn-once and knowledge routes share this module | tests/component/test_learn_once_persistence.py, test_contract_runtime.py | Q-LOC-08 |
| `backend/tests/component/test_crawl_service.py` | 1513 | 1325 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_crawl_service.py | Q-LOC-09 |
| `frontend/components/crawl/crawl-run-screen.test.tsx` | 1433 | 1264 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | frontend/components/crawl/crawl-run-screen.test.tsx | Q-LOC-10 |
| `backend/tests/unit/test_extraction_js_state_behavior.py` | 1373 | 1265 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_js_state_behavior.py | Q-LOC-11 |
| `backend/tests/component/test_public_api.py` | 1323 | 1127 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_public_api.py | Q-LOC-12 |
| `backend/tests/regression/test_harness_support.py` | 1254 | 1083 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/regression/test_harness_support.py | Q-LOC-13 |
| `backend/alembic/versions/20260703_0001_greenfield_schema.py` | 1240 | 1227 | script/tooling | Harness/probe/migration script, not runtime service | Split report rendering vs probe loop vs fixtures; alembic file is a single migration and should stay atomic or be excluded only if classified generated | CODEBASE_MAP support files / alembic | Low-medium | tests/regression/test_harness_support.py, test_browser_surface_probe.py | Q-LOC-14 |
| `backend/app/extraction/collectors/dom.py` | 1157 | 1069 | production source | DOM collector: brand/offer/image/variant controls + CSS recipe evidence | Keep DomCollector; move variant-control helpers and CSS recipe evidence to sibling collector modules already in collectors/ | extraction/collectors/dom.py | High: DOM is last-tier extractor; wrong split can drop variant cues (INVARIANTS Rule 3) | tests/unit/test_extraction_*_behavior.py | Q-LOC-15 |
| `backend/tests/unit/test_extraction_runtime_behavior.py` | 1146 | 1029 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_runtime_behavior.py | Q-LOC-16 |
| `backend/app/extraction/engine.py` | 1127 | 1059 | production source | Extraction facade: attempt loop, recipe replay, assess, diagnostics | Keep extract() facade; move assessment/diagnostics/recipe-replay helpers already listed as private functions | extraction/engine.py | High: facade is the extraction entry; do not add a parallel engine | tests/unit/test_extraction_runtime_behavior.py, test_extraction_architecture.py | Q-LOC-17 |
| `backend/tests/unit/test_extraction_integrity_behavior.py` | 1115 | 973 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_integrity_behavior.py | Q-LOC-18 |
| `backend/tests/component/test_learn_once_persistence.py` | 1100 | 946 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_learn_once_persistence.py | Q-LOC-19 |
| `backend/tests/component/test_contract_runtime.py` | 1099 | 988 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_contract_runtime.py | Q-LOC-20 |
| `backend/tests/regression/test_data_enrichment.py` | 1052 | 926 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/regression/test_data_enrichment.py | Q-LOC-21 |
| `backend/tests/unit/test_extraction_variant_behavior.py` | 1045 | 944 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_variant_behavior.py | Q-LOC-22 |
| `backend/app/core/config/extraction_rules/_detail.py` | 1032 | 1026 | production source | Declarative detail extraction rules/config | Split by rule family already implied by sibling _listing_* files; keep all tunables in core/config | core/config/extraction_rules/_detail.py | Medium: config must stay in core/config (AP-13) | tests/unit/test_extraction_architecture.py ratchet | Q-LOC-23 |
| `backend/app/extraction/contracts.py` | 1029 | 856 | production source | Typed extraction contracts, records, field_contracts_for_surface | Separate FieldContract tables vs result/record dataclasses vs surface contract lookup | extraction/contracts.py | High: contract types are imported widely | tests/unit/test_extraction_contract_behavior.py | Q-LOC-24 |
| `backend/app/extraction/collectors/js_state.py` | 988 | 914 | production source | JS-state / network-row collector | Split network_row vs variant heuristics vs object walk; do not early-return after first object (INVARIANTS) | extraction/collectors/js_state.py | High: variant completeness | tests/unit/test_extraction_js_state_behavior.py | Q-LOC-25 |
| `backend/tests/unit/test_extraction_asset_behavior.py` | 979 | 889 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_extraction_asset_behavior.py | Q-LOC-26 |
| `frontend/components/crawl/log-terminal.tsx` | 972 | 926 | production source | Crawl log terminal UI: icons, grouping, coverage, expanded rows | log-terminal-utils.ts already exists; move remaining grouping/coverage/render helpers there; keep LogTerminal component thin | components/crawl/log-terminal.tsx + log-terminal-utils.ts | Medium: UI-only | components/crawl/crawl-run-screen.test.tsx | Q-LOC-27 |
| `backend/app/enrichment/service.py` | 959 | 905 | production source | Data enrichment job orchestration + LLM apply | Keep run_job owner; move LLM payload apply and batch load to existing enrichment/ siblings | enrichment/service.py | High: Celery job path | tests/regression/test_data_enrichment.py, tests/component/test_pi_de_job_tasks.py | Q-LOC-28 |
| `backend/app/extraction/collectors/jsonld.py` | 936 | 871 | production source | JSON-LD product/variant collector | Split product node vs variant options vs graph walk | extraction/collectors/jsonld.py | Medium | tests/unit/test_extraction_variant_behavior.py | Q-LOC-29 |
| `backend/app/extraction/entities.py` | 932 | 850 | production source | Entity graph construction: products, variants, offers | Split identity/grouping vs offer linking vs primary-root scoring | extraction/entities.py | High: AP-12 entity graph owner | tests/unit/test_extraction_integrity_behavior.py | Q-LOC-30 |
| `backend/tests/component/test_sitemap_resolver.py` | 917 | 806 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/component/test_sitemap_resolver.py | Q-LOC-31 |
| `backend/app/extraction/result_building.py` | 888 | 824 | production source | Field evidence states, unpublished state, retry_request | Split evidence-state projection vs retry/request shaping | extraction/result_building.py | High | tests/unit/test_extraction_contract_behavior.py | Q-LOC-32 |
| `backend/tests/unit/test_evaluation_phase4.py` | 867 | 768 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_evaluation_phase4.py | Q-LOC-33 |
| `backend/app/extraction/pipeline.py` | 837 | 781 | production source | Detail harvest/normalize/quality flags; unused collect_ecommerce_detail wrapper | Keep harvest/normalize owner; move flag helpers; delete unused wrapper after grep confirmation | extraction/pipeline.py | High | tests/unit/test_extraction_integrity_behavior.py | Q-LOC-34 |
| `frontend/lib/api/types.ts` | 831 | 758 | production source | Generated-looking API DTO union for frontend | Split by domain owner parallel to lib/api/*.ts (crawls, records, jobs, …) rather than a catch-all types file | lib/api/*.ts owners listed in check-frontend-architecture.mjs | Medium: contract drift if types split without API owners | lib/check-crawl-architecture.test.ts | Q-LOC-35 |
| `backend/app/intelligence/service.py` | 821 | 761 | production source | Product intelligence job create/poll/score | Keep orchestration; scoring already has matching.py / service_support.py — finish the split | intelligence/service.py | High | tests/component/test_product_intelligence.py | Q-LOC-36 |
| `backend/tests/unit/test_crawl_run_95_regressions.py` | 801 | 698 | test | Focused behavior suite that grew past AP-29 mega-test limit | Split by public owner/behavior (fetch vs browser vs PI vs extraction family); shared fixtures to support modules | backend/tests or frontend colocated tests | Medium: split must preserve collected test count | backend/tests/unit/test_crawl_run_95_regressions.py | Q-LOC-37 |

## 5. Complexity Violations

**Metric:** Radon McCabe cyclomatic complexity via `radon.complexity.cc_visit` (same as `test_extraction_architecture.py:45-47`). **Grade mapping used:** A 1–5, B 6–10, C 11–20, D 21–30, E 31–40, F 41+. **Requested ceiling 15 is inside grade C**; a grade-C gate (`--min C`) would still allow 16–20 and is **not** equivalent.

**Current repo metric:** `test_no_new_complex_functions` flags **CC >20** with `COMPLEX_FUNCTION_DEBT`. Extraction toml `default_module_cyclomatic_complexity_budget = 20` (`extraction_semantic_surface.toml:41`).

**Tool limitations:** Radon does not count boolean short-circuit the same as oxlint classic (optional chaining / default args). Nested functions are separate blocks. Parser errors: **0**. Class methods reported as `Class.method` when `classname` present.

**Frontend equivalent:** oxlint rule `complexity` ([oxc eslint/complexity](https://oxc.rs/docs/guide/usage/linter/rules/eslint/complexity.html)), McCabe classic or modified; default max **20**. Close enough to Radon for a CI twin; not bit-identical. `vp lint --deny complexity` (default 20) **FAIL** on 8 functions. A max-15 oxlint run was **not successfully configured** (`-c` conflicts with vp; `complexity:15` flag ignored). Treat 16–20 TS inventory as **UNVERIFIED** except the 8 already >20.

**Python summary:** 202 callables >15; 122 in 16–20; 80 >20; production 169; max 86.

**Frontend oxlint default-20 failures (production):**

| File:line | Symbol | Language | Complexity | Production/test | Control-flow cause | Simplification seam | Finding ID |
|---|---|---|---:|---|---|---|---|
| `frontend/app/data-enrichment/page-view.tsx:27` | `DataEnrichmentPage` | TSX | 43 | production | Page-level job/state branches | Delegate to existing hook/reducer owners (architecture script already forbids reducer in page) | Q-CC-FE-01 |
| `frontend/components/crawl/log-terminal.tsx:648` | anonymous render | TSX | 31 | production | Group rendering conditionals | Move to helpers in `log-terminal-utils.ts` | Q-CC-FE-02 |
| `frontend/components/crawl/run-summary.tsx:61` | `useRunSummary` | TS | 28 | production | Derived metrics branches | Split selectors by metric family | Q-CC-FE-03 |
| `frontend/components/crawl/crawl-config-logic.ts:212` | `buildDispatch` | TS | 27 | production | Optional settings mapping | Table-driven field mapping | Q-CC-FE-04 |
| `frontend/components/crawl/crawl-run-screen.tsx:38` | `CrawlRunWorkspace` | TSX | 26 | production | Workspace mode/state | Existing screen already near 400-line policy cap | Q-CC-FE-05 |
| `frontend/components/ui/dropdown.tsx:18` | `Dropdown` | TSX | 25 | production | Positioning/open-state | Extract positioning predicates | Q-CC-FE-06 |
| `frontend/app/product-intelligence/use-product-intelligence.ts:162` | `useProductIntelligence` | TS | 22 | production | Job polling/review branches | Split poll vs review vs create | Q-CC-FE-07 |
| `frontend/components/domain-memory/knowledge-graph-tab.tsx:20` | `KnowledgeGraphTab` | TSX | 21 | production | Graph/tab conditionals | Split view vs data mapping | Q-CC-FE-08 |

**Complete Python Radon inventory (CC >15):**

| File:line | Symbol | Language | Complexity | Production/test | Control-flow cause | Simplification seam | Finding ID |
|---|---|---|---:|---|---|---|---|
| `backend/app/core/shared/field_coerce_text.py:248` | `infer_brand_from_product_url` | Python | 86 | production | Long URL/host/token heuristic ladder | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-001 |
| `backend/browser_surface_probe/core.py:1015` | `build_findings` | Python | 78 | tooling | Deep nested predicates / heuristic scoring | Extract named predicates; do not create a new utils layer | Q-CC-PY-002 |
| `backend/run_extraction_smoke.py:186` | `_run_one` | Python | 57 | tooling | Deep nested predicates / heuristic scoring | Extract named predicates; do not create a new utils layer | Q-CC-PY-003 |
| `backend/app/acquisition/browser_detail.py:238` | `_candidate_is_admitted` | Python | 56 | production | Admission predicates combining URL, identity, and chrome filters | Extract named predicates; do not create a new utils layer | Q-CC-PY-004 |
| `backend/app/core/shared/field_coerce_dispatch.py:212` | `coerce_field_value` | Python | 54 | production | Per-field dispatch with nested type/format branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-005 |
| `backend/app/extraction/result_building.py:197` | `field_evidence_states` | Python | 46 | production | Nested field/variant/asset state matrix | Extract named predicates; do not create a new utils layer | Q-CC-PY-006 |
| `backend/harness/support.py:397` | `classify_failure_mode` | Python | 43 | tooling | Deep nested predicates / heuristic scoring | Extract named predicates; do not create a new utils layer | Q-CC-PY-007 |
| `backend/app/extraction/collectors/js_state.py:368` | `network_row` | Python | 41 | production | Network payload shape detection + field mapping | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-008 |
| `backend/app/extraction/pipeline.py:566` | `normalize_evidence` | Python | 40 | production | Multi-flag quality/normalization pipeline | Extract named predicates; do not create a new utils layer | Q-CC-PY-009 |
| `backend/app/core/shared/field_coerce_text.py:159` | `infer_brand_from_page_identity` | Python | 39 | production | Many independent boolean gates in one callable | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-010 |
| `backend/app/extraction/resolution/price_units.py:14` | `_price_unit_repairs` | Python | 37 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-011 |
| `backend/app/observability/run_report.py:126` | `_root_causes` | Python | 37 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-012 |
| `backend/harness/support.py:1175` | `_observed_quality_failure_mode` | Python | 37 | tooling | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-013 |
| `backend/run_test_sites_acceptance.py:225` | `main` | Python | 37 | tooling | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-014 |
| `backend/app/acquisition/browser_readiness.py:63` | `analyze_extractable_content` | Python | 35 | production | Readiness signal combination | Extract named predicates; do not create a new utils layer | Q-CC-PY-015 |
| `backend/app/core/records/divergence.py:278` | `_compare_assets` | Python | 35 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-016 |
| `backend/tests/component/test_crawls_api_domain_recipe.py:84` | `test_crawls_domain_recipe_routes_round_trip` | Python | 35 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-017 |
| `backend/app/extraction/validation.py:580` | `_validate_child_join_failures` | Python | 33 | production | Many independent boolean gates in one callable | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-018 |
| `backend/app/intelligence/discovery.py:579` | `_parse_serpapi_immersive_results` | Python | 33 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-019 |
| `backend/app/core/shared/field_coerce.py:391` | `sanitize_option_scalar` | Python | 32 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-020 |
| `backend/app/acquisition/browser_block_detection.py:274` | `_block_policy_matches` | Python | 30 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-021 |
| `backend/app/acquisition/browser_capture.py:495` | `_repair_truncated_json_prefix` | Python | 30 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-022 |
| `backend/app/core/records/field_url_normalization.py:166` | `canonical_public_record_url` | Python | 30 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-023 |
| `backend/app/extraction/pipeline.py:315` | `_flag_brand_conflicts` | Python | 30 | production | Many independent boolean gates in one callable | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-024 |
| `backend/app/persistence/publish/metrics.py:57` | `build_url_metrics` | Python | 30 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-025 |
| `backend/app/core/records/schema_service.py:59` | `_snapshot_to_resolved` | Python | 29 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-026 |
| `backend/app/extraction/pipeline.py:751` | `_title_flags` | Python | 29 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-027 |
| `backend/app/extraction/replay.py:49` | `fixture_bundle_from_inputs` | Python | 29 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-028 |
| `backend/harness/support.py:182` | `load_site_set` | Python | 29 | tooling | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-029 |
| `backend/app/core/records/url_identity.py:425` | `_short_numeric_product_asset_conflicts` | Python | 28 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-030 |
| `backend/app/persistence/publish/verdict.py:61` | `run_health_verdict` | Python | 28 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-031 |
| `backend/app/core/records/normalizers/__init__.py:196` | `normalize_value` | Python | 27 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-032 |
| `backend/app/extraction/engine.py:660` | `_assess` | Python | 27 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-033 |
| `backend/harness/artifact_quality_cases.py:137` | `_audit_case` | Python | 27 | tooling | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-034 |
| `backend/app/acquisition/source_capabilities.py:35` | `build_source_capability_diagnostics` | Python | 26 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-035 |
| `backend/app/core/records/normalizers/__init__.py:79` | `normalize_decimal_price` | Python | 26 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-036 |
| `backend/app/extraction/publication.py:573` | `serialize_commerce_detail_projection` | Python | 26 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-037 |
| `backend/browser_surface_probe/core.py:876` | `_target_root_cause` | Python | 26 | tooling | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-038 |
| `backend/tests/component/test_dashboard_service.py:144` | `test_split_reset_crawl_data_and_domain_memory_preserve_the_other_scope` | Python | 26 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-039 |
| `backend/app/core/shared/url_utils.py:374` | `extract_urls` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-040 |
| `backend/app/enrichment/service.py:365` | `run_job` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-041 |
| `backend/app/extraction/resolution/derived.py:111` | `_semantic_derived_facts` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-042 |
| `backend/app/extraction/resolution/variant_rollup.py:27` | `_reconcile_variant_prices` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-043 |
| `backend/app/extraction/validation.py:676` | `_validate_availability_consistency` | Python | 25 | production | Many independent boolean gates in one callable | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-044 |
| `backend/app/intelligence/service.py:703` | `_poll_candidates_and_score` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-045 |
| `backend/app/observability/diagnose.py:68` | `build_diagnosis` | Python | 25 | production | Many independent boolean gates in one callable | Extract named predicates; do not create a new utils layer | Q-CC-PY-046 |
| `backend/app/acquisition/platform_policy.py:141` | `detect_platform_family` | Python | 24 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-047 |
| `backend/app/crawl/crud.py:49` | `create_crawl_run` | Python | 24 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-048 |
| `backend/app/extraction/entities.py:683` | `_variant_identity_keys` | Python | 24 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-049 |
| `backend/eval/score.py:98` | `score_surface` | Python | 24 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-050 |
| `backend/app/core/extraction_memory/contract_runtime.py:24` | `match_template` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-051 |
| `backend/app/core/extraction_memory/contract_runtime.py:117` | `resolved_contract_outcomes` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-052 |
| `backend/app/core/records/confidence.py:254` | `_field_penalties` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-053 |
| `backend/app/core/records/divergence.py:191` | `_compare_variants` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-054 |
| `backend/app/crawl/site_link_discovery.py:85` | `discover_rendered_category_links` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-055 |
| `backend/app/extraction/collectors/_helpers.py:202` | `_subject_id` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-056 |
| `backend/app/extraction/collectors/js_state.py:611` | `_looks_like_variant` | Python | 23 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-057 |
| `backend/app/acquisition/browser_identity.py:79` | `build_playwright_context_spec` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-058 |
| `backend/app/acquisition/browser_listing_visual.py:145` | `listing_visual_elements_html` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-059 |
| `backend/app/acquisition/browser_page_helpers.py:50` | `_select_primary_browser_html` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-060 |
| `backend/app/acquisition/browser_readiness.py:187` | `_has_detail_dom_signals` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-061 |
| `backend/app/core/shared/text_coerce.py:99` | `is_title_noise` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-062 |
| `backend/app/crawl/profile/acquisition_contract.py:77` | `build_success_acquisition_contract` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-063 |
| `backend/app/extraction/resolution/decisions.py:157` | `_resolve_scalar` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-064 |
| `backend/app/extraction/resolution/derived.py:271` | `_brand_from_title` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-065 |
| `backend/app/extraction/resolution/offers.py:80` | `_offer_atomic_price_currency_preferences` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-066 |
| `backend/app/extraction/resolution/variant_rollup.py:470` | `_inherit_variant_offer_facts` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-067 |
| `backend/app/intelligence/matching.py:313` | `extract_search_result_snapshot` | Python | 22 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-068 |
| `backend/harness/artifact_quality_cases.py:202` | `_replay_case` | Python | 22 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-069 |
| `backend/harness/artifact_quality_cases.py:593` | `_acquisition_status_code` | Python | 22 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-070 |
| `backend/harness/quality_evaluator.py:71` | `build_acceptance_gate_report` | Python | 22 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-071 |
| `backend/app/core/records/divergence.py:102` | `compare_records_to_projection` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-072 |
| `backend/app/core/records/js_state_scope.py:336` | `path_product_identity_conflicts` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-073 |
| `backend/app/core/records/structured_variant_state.py:231` | `with_parent_variant_axes` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-074 |
| `backend/app/crawl/sitemap_nav.py:186` | `_looks_like_category_url` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-075 |
| `backend/app/extraction/entities.py:569` | `_variant_groups` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-076 |
| `backend/app/intelligence/matching.py:240` | `_apply_identity_floor` | Python | 21 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-077 |
| `backend/harness/artifact_quality_cases.py:83` | `validate_artifact_quality_cases` | Python | 21 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-078 |
| `backend/harness/quality_evaluator.py:211` | `validate_catalog_quality_manifest` | Python | 21 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-079 |
| `backend/tests/component/test_pi_de_job_tasks.py:681` | `test_enrichment_run_job_batch_loads_products_and_records` | Python | 21 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-080 |
| `backend/app/acquisition/fetch/planned_http.py:346` | `handle_planned_http_result` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-081 |
| `backend/app/core/records/url_identity.py:173` | `detail_title_from_url` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-082 |
| `backend/app/crawl/profile/merge.py:116` | `merge_saved_run_profile` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-083 |
| `backend/app/crawl/review/__init__.py:117` | `save_review` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-084 |
| `backend/app/extraction/collectors/jsonld.py:174` | `_product` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-085 |
| `backend/app/extraction/listing_records.py:478` | `_anchorless_records` | Python | 20 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-086 |
| `backend/harness/support.py:951` | `_quality_category_clean_ok` | Python | 20 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-087 |
| `backend/tests/unit/test_ai_visibility_scoring.py:182` | `test_aggregate_run_rates_and_stability` | Python | 20 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-088 |
| `backend/app/acquisition/cookie_store.py:703` | `_http_cookie_pairs_for_url` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-089 |
| `backend/app/acquisition/fetch/planned_http.py:420` | `run_browser_http_handoff` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-090 |
| `backend/app/acquisition/traversal_helpers.py:62` | `looks_like_paginate_control` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-091 |
| `backend/app/ai_visibility/gemini_parser.py:139` | `sanitize_metadata` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-092 |
| `backend/app/ai_visibility/service.py:208` | `create_run` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-093 |
| `backend/app/core/records/confidence.py:23` | `score_record_confidence` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-094 |
| `backend/app/crawl/sitemap_resolver.py:110` | `resolve_category_urls_with_site_links` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-095 |
| `backend/app/enrichment/deterministic.py:184` | `normalize_sizes` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-096 |
| `backend/app/enrichment/service.py:596` | `_apply_llm_payload` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-097 |
| `backend/app/enrichment/shopify_catalog.py:274` | `phrase_path_category_match` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-098 |
| `backend/app/extraction/collectors/_helpers.py:124` | `_brand_role` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-099 |
| `backend/app/extraction/entities.py:449` | `_product_identity_sets_compatible` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-100 |
| `backend/app/extraction/entities.py:739` | `_link_offers` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-101 |
| `backend/app/extraction/listing_records.py:369` | `_best_grid_children` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-102 |
| `backend/app/extraction/resolution/variants.py:71` | `_resolve_variants` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-103 |
| `backend/app/extraction/validation.py:423` | `_validate_offers` | Python | 19 | production | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-104 |
| `backend/harness/support.py:245` | `parse_test_sites_markdown` | Python | 19 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-105 |
| `backend/run_local_extraction_corpus.py:232` | `_summary` | Python | 19 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-106 |
| `backend/run_test_sites_acceptance.py:80` | `_build_summary` | Python | 19 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-107 |
| `backend/tests/unit/test_extraction_architecture.py:451` | `test_universal_model_config_does_not_live_in_extraction_service_code` | Python | 19 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-108 |
| `backend/tests/unit/test_extraction_architecture.py:552` | `test_publish_surface_does_not_receive_raw_evidence_or_entity_graph` | Python | 19 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-109 |
| `backend/tests/unit/test_publish_metrics.py:14` | `test_build_url_metrics_promotes_traversal_diagnostics` | Python | 19 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-110 |
| `backend/app/acquisition/browser_capture.py:147` | `BrowserNetworkCapture.close` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-111 |
| `backend/app/acquisition/browser_readiness.py:296` | `wait_for_listing_readiness` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-112 |
| `backend/app/acquisition/browser_readiness.py:512` | `probe_browser_readiness` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-113 |
| `backend/app/acquisition/cookie_store.py:555` | `_normalize_cookies` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-114 |
| `backend/app/acquisition/platform_policy.py:190` | `resolve_listing_readiness_platform` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-115 |
| `backend/app/ai_visibility/scoring.py:398` | `_headline_aggregates` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-116 |
| `backend/app/core/records/divergence.py:28` | `compare_public_record_to_projection` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-117 |
| `backend/app/crawl/domain_memory_service.py:215` | `compose_runtime_selector_rules` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-118 |
| `backend/app/crawl/review/__init__.py:43` | `build_review_payload` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-119 |
| `backend/app/crawl/review/domain_recipe_support.py:126` | `_collect_record_selector_candidates` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-120 |
| `backend/app/crawl/sitemap_resolver.py:596` | `_extract_homepage_candidate_entries` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-121 |
| `backend/app/extraction/collectors/dom.py:1072` | `css_recipe_evidence` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-122 |
| `backend/app/extraction/engine.py:1055` | `_diagnostic_summary` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-123 |
| `backend/app/extraction/entities.py:184` | `_primary_product_root_score` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-124 |
| `backend/app/extraction/publication.py:113` | `_commerce_detail_policy` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-125 |
| `backend/app/extraction/resolution/variant_rollup.py:338` | `_aggregate_partial_variant_price` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-126 |
| `backend/app/extraction/resolution/variants.py:214` | `_put_variant_offer` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-127 |
| `backend/app/extraction/result_building.py:464` | `_unpublished_field_state` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-128 |
| `backend/app/extraction/result_building.py:510` | `_record_field_state` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-129 |
| `backend/app/extraction/result_building.py:644` | `retry_request` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-130 |
| `backend/app/extraction/targeting.py:132` | `scoped_graph` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-131 |
| `backend/app/extraction/targeting.py:167` | `_select_product_by_url` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-132 |
| `backend/app/extraction/validation.py:312` | `_validate_expected_variant_axes` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-133 |
| `backend/app/intelligence/candidate_urls.py:38` | `looks_like_product_detail_url` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-134 |
| `backend/app/observability/diagnose.py:569` | `_projection_entries_by_public_field` | Python | 18 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-135 |
| `backend/harness/artifact_quality_cases.py:290` | `_case_signals` | Python | 18 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-136 |
| `backend/harness/support.py:493` | `_challenge_summary_from_diagnostics` | Python | 18 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-137 |
| `backend/app/acquisition/acquirer.py:152` | `PageEvidence.indicates_block` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-138 |
| `backend/app/acquisition/browser_diagnostics.py:159` | `browser_failure_kind` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-139 |
| `backend/app/acquisition/browser_readiness.py:658` | `classify_browser_outcome` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-140 |
| `backend/app/acquisition/browser_result_builder.py:701` | `_ready_probe_supports_fast_finalize` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-141 |
| `backend/app/acquisition/runtime.py:184` | `should_escalate_to_browser` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-142 |
| `backend/app/ai_visibility/gemini.py:59` | `safe_quota_detail` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-143 |
| `backend/app/api/crawls.py:404` | `crawls_logs_ws` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-144 |
| `backend/app/core/extraction_memory/contract_runtime.py:255` | `select_active_recipe` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-145 |
| `backend/app/core/shared/field_coerce_price.py:153` | `repair_price_unit` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-146 |
| `backend/app/crawl/pipeline/runtime_helpers.py:146` | `record_detail_expansion_extraction_outcome` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-147 |
| `backend/app/crawl/profile/acquisition_contract.py:35` | `apply_acquisition_contract_to_profile` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-148 |
| `backend/app/crawl/profile/acquisition_contract.py:273` | `record_acquisition_contract_outcome` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-149 |
| `backend/app/crawl/review/__init__.py:336` | `_resolve_recipe_fields` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-150 |
| `backend/app/evaluation/model_harness.py:36` | `ModelPrediction` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract hook vs view vs mapping tables | Q-CC-PY-151 |
| `backend/app/extraction/entities.py:222` | `_link_products` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-152 |
| `backend/app/extraction/entities.py:402` | `_product_identities` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-153 |
| `backend/app/extraction/listing_tier0.py:466` | `_value_for_kind` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-154 |
| `backend/app/extraction/pipeline.py:278` | `_flag_ambiguous_dom_prices` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-155 |
| `backend/app/extraction/resolution/assets.py:156` | `_variant_parent_fallback` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-156 |
| `backend/app/persistence/extraction_memory.py:79` | `compile_recipe_layers` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-157 |
| `backend/app/tasks.py:191` | `_sweep_run_artifacts` | Python | 17 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-158 |
| `backend/harness/quality_evaluator.py:149` | `build_catalog_quality_report` | Python | 17 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-159 |
| `backend/tests/unit/test_extraction_architecture.py:383` | `test_phase4_evaluation_modules_are_offline_only` | Python | 17 | test | Large test function with many assertions/branches | Extract named predicates; do not create a new utils layer | Q-CC-PY-160 |
| `backend/app/acquisition/browser_block_detection.py:162` | `_has_product_identity_content` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-161 |
| `backend/app/acquisition/browser_block_detection.py:199` | `_collect_block_evidence` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-162 |
| `backend/app/acquisition/browser_listing_visual.py:193` | `_normalize_snapshot` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-163 |
| `backend/app/acquisition/browser_page_flow.py:122` | `navigate_browser_page` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-164 |
| `backend/app/acquisition/browser_storage_state.py:29` | `persist_context_storage_state` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-165 |
| `backend/app/acquisition/internal_api_replay.py:97` | `_replay_endpoint` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-166 |
| `backend/app/acquisition/traversal_helpers.py:244` | `_collect_structured_script_fragments` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-167 |
| `backend/app/ai_visibility/anthropic_parser.py:32` | `_answer_and_citations` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-168 |
| `backend/app/ai_visibility/openrouter_parser.py:44` | `_citations` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-169 |
| `backend/app/ai_visibility/openrouter_parser.py:83` | `parse_openrouter_completion` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-170 |
| `backend/app/core/config/__init__.py:233` | `_check_secret_defaults` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-171 |
| `backend/app/core/extraction_memory/recipe_compiler.py:281` | `_build_recipe` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-172 |
| `backend/app/core/extraction_memory/recipe_transforms.py:71` | `_normalize_field` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-173 |
| `backend/app/core/public_auth.py:89` | `authenticate_public_api_key` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-174 |
| `backend/app/core/records/js_state_scope.py:154` | `_object_matches_target` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-175 |
| `backend/app/core/records/normalizers/__init__.py:148` | `_canonicalize_decimal_candidate` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-176 |
| `backend/app/core/shared/field_coerce_text.py:70` | `infer_brand_from_title_host` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named heuristic tables into core/config + keep one coercion owner | Q-CC-PY-177 |
| `backend/app/crawl/review/__init__.py:230` | `_promote_review_bucket_fields` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-178 |
| `backend/app/crawl/review/domain_recipe_support.py:33` | `derive_acquisition_info` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-179 |
| `backend/app/crawl/review/domain_recipe_support.py:200` | `_collect_field_learning` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-180 |
| `backend/app/enrichment/shopify_repository.py:198` | `load_attribute_repository_data` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-181 |
| `backend/app/evaluation/grounded_corrections.py:420` | `_candidate_recipe_proposal` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-182 |
| `backend/app/evaluation/model_harness.py:50` | `ModelPrediction.validate_evidence_only_prediction` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-183 |
| `backend/app/extraction/collectors/dom.py:78` | `DomCollector` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Keep collector owner; extract predicate helpers beside existing _helpers.py | Q-CC-PY-184 |
| `backend/app/extraction/collectors/dom.py:458` | `_product_image_nodes` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-185 |
| `backend/app/extraction/collectors/jsonld.py:812` | `_jsonld_variant_options` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-186 |
| `backend/app/extraction/engine.py:804` | `_failure_classifications` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-187 |
| `backend/app/extraction/pipeline.py:481` | `assess_ecommerce_detail_quality` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-188 |
| `backend/app/extraction/pipeline.py:698` | `_flag_description_value` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-189 |
| `backend/app/extraction/resolution/assets.py:74` | `resolve_product_assets` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-190 |
| `backend/app/extraction/resolution/decisions.py:73` | `_url_mismatched_product_subjects` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-191 |
| `backend/app/extraction/resolution/derived.py:26` | `_derived` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-192 |
| `backend/app/extraction/resolution/variant_rollup.py:251` | `_aggregate_variant_field` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-193 |
| `backend/app/extraction/validation.py:217` | `_validate_descriptions` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Split per-finding validators already implied by validation.py helpers | Q-CC-PY-194 |
| `backend/app/intelligence/matching.py:97` | `extract_product_snapshot` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-195 |
| `backend/app/intelligence/service_support.py:44` | `_score_candidate_if_ready` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-196 |
| `backend/app/persistence/extraction_memory.py:431` | `selector_rules_from_release` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-197 |
| `backend/app/persistence/extraction_memory.py:1129` | `_record_observed_field_preferences` | Python | 16 | production | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-198 |
| `backend/harness/artifact_quality_cases.py:553` | `_has_blocked_product_source` | Python | 16 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-199 |
| `backend/harness/support.py:1280` | `_looks_like_site_shell_success` | Python | 16 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-200 |
| `backend/run_test_sites_acceptance.py:129` | `_expectation_met` | Python | 16 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-201 |
| `backend/run_test_sites_acceptance.py:154` | `_expected_contract_met` | Python | 16 | tooling | Branching beyond current 15 ceiling (if/and/or/try) | Extract named predicates; do not create a new utils layer | Q-CC-PY-202 |

## 6. Dead-Code Findings

- **Tool:** vulture 2.16
- **Command:** `uvx --from vulture==2.16 vulture app --min-confidence {100,80,60} --exclude .venv` (cwd `backend`)
- **Config:** `[tool.vulture] min_confidence = 100` (`backend/pyproject.toml:137-138`)
- **Limitations:** Does not see FastAPI/`APIRouter` registration, Celery `.task`, Pydantic fields, SQLAlchemy mapped columns, tests (when scanning `app` only), `__getattr__` config exports (AP-21 risk). Confidence 60 emits **823** mostly-false names.

### Confirmed

| Symbol | Evidence | Finding ID |
|---|---|---|
| `collect_ecommerce_detail` (`pipeline.py:92`) | Only definition in repo; wrapper around `harvest_ecommerce_detail`; no imports | Q-DEAD-01 |
| `parse_json_ld`, `harvest_js_state_objects` (`prompt_rendering.py:19,36`) | Defined, never called in app or tests (tests use other helpers in that module) | Q-DEAD-02 |
| `extend_browser_engine_attempts_after_block` (`browser_policy.py:282`) | Superseded by `fetch_context._extend_browser_engine_attempts_after_block`; no other references | Q-DEAD-03 |

### Likely

| Symbol | Notes | Finding ID |
|---|---|---|
| `build_playwright_context_options` | Used **only in tests** (`test_browser_context.py`); production uses `build_playwright_context_spec`. Keep if tests are the contract, or fold into spec. | Q-DEAD-04 |

### Uncertain/dynamic

Almost all `app/api/*.py` “unused functions” (FastAPI handlers). Celery `sweep_run_artifacts_task` is referenced in tests and `app/tasks.py`. `configured_adapter_names` / `is_job_platform_signal` used from harness and unit tests. Pydantic `model_config`, `schema_version`, ORM columns, `__getattr__` config names (~302 hits under `app/core/config`). **Do not delete from Vulture 60%.**

### False positives

| Symbol | Why |
|---|---|
| `ExportRecord.model_post_init(__context=)` (`export/schema.py:75`) | **100%** Vulture hit; required Pydantic v2 hook parameter |
| FastAPI route functions | Decorator registration |
| `field_contracts_for_surface` | Used in unit tests |
| `rollback_release_snapshot_for_run` | Used in `test_contract_runtime.py` |
| `build_compact_page_representation` | Used in `test_evaluation_phase4.py` |
| `beat_schedule` | Assigned on Celery app in `celery_app.py:82` |

## 7. Duplication Findings

- **Command:** `npx --yes jscpd@4.0.5 --silent --reporters json --output %TEMP%\jscpd-crawlerai --ignore "**/.venv/**,**/node_modules/**,**/dist/**,**/coverage/**,**/__pycache__/**,**/.git/**,**/playwright-report/**,**/test-results/**,**/htmlcov/**,**/.mypy_cache/**,**/.ruff_cache/**,**/alembic/versions/**" --min-lines 10 --min-tokens 70 backend/app frontend/app frontend/components frontend/lib frontend/src`
- **Totals:** 672 files, **17 clones**, **223 duplicated lines (0.18%)**, 2385 duplicated tokens. Exit 0.

**High-value consolidation candidates**

| Paths | Lines | Owner | Note | Finding ID |
|---|---:|---|---|---|
| `extraction/collectors/js_state.py` ↔ `metadata.py` (two clones, 16+12) | 28 | extraction collectors | Shared JSON/script harvest helpers belong in `collectors/_helpers.py` | Q-DUP-01 |
| `extraction/documents.py:43-55` ↔ `representation/flat_map.py:239-251` | 13 | extraction documents | Child-text join; keep documents as owner, call it | Q-DUP-02 |
| `intelligence/service.py` ↔ `service_support.py` snapshot mapping | 11 | intelligence | Finish moving constructors to one owner | Q-DUP-03 |
| `intelligence/service.py` internal 133–144 vs 437–447 | 11 | intelligence | Same job-create preamble | Q-DUP-04 |
| `api/ai_visibility.py` CSV vs markdown export handlers | 13 | api/ai_visibility | Shared run-lookup + 404 | Q-DUP-05 |
| `acquisition/fetch/attempt_plan.py` ↔ `planned_http.py` | 12 | acquisition fetch | Shared attempt bookkeeping | Q-DUP-06 |

**Intentional/acceptable**

- Frontend test clones (app-shell/sidebar, ai-visibility form fixtures, client.test.ts) — fixture repetition.
- ORM FK column blocks `models/data_enrichment.py` ↔ `product_intelligence.py` — parallel job schemas, not a fake shared mixin unless models already share a base.
- `ai-visibility/domain-workspace.tsx` ↔ `project-form-dialog.tsx` 12-line form field lists — readable duplication unless one form owner exists.

**Recommended future CI threshold (not an approved requirement):** fail if **duplicated-line percentage > 1.0%** at `--min-lines 15 --min-tokens 80` on `backend/app` + `frontend/{app,components,lib,src}` excluding `**/*.test.*` and `**/*.spec.*`. Current 0.18% would pass; keeps pressure without blocking tests. Alternative: jscpd `--threshold 1` after excluding tests.

## 8. Lint and Format Findings

### Backend

- **Lint command (tested):** `uvx --from ruff==0.15.22 ruff check app tests` → exit **0**.
- **Format command (tested):** `uvx --from ruff==0.14.10 ruff format --check app tests` → exit **0**, 552 files. (Lockfile Ruff is 0.15.22; format not re-run on 0.15.22 — treat format-on-0.15.22 as **proposed**.)
- **Types (tested):** `uv run --frozen --extra dev python -m mypy app` → exit **0**, 381 files.
- **Missing committed Ruff config:** no `[tool.ruff]`, so CI uses Ruff defaults (not `I` isort unless selected). Import sorting ownership is **implicit defaults**, overlapping disabled Pylint `wrong-import-order`.
- **Pylint:** design limits exist (`max-module-lines = 1000`, `max-branches = 12`) but messages are **globally disabled** including `too-many-lines`, `too-many-branches`, `duplicate-code` — AP-22. Not in CI.
- **CI:** ruff + mypy + pytest + pip-audit; **no** `ruff format --check`. Path filters skip frontend-only changes (OK). `pip` cache on `pyproject.toml` **not** `uv.lock`.
- **Recommended gate owner:** extend `.github/workflows/backend-ci.yml` job `backend` with format + later LOC/CC scripts; do not add a parallel workflow.

### Frontend

- **Actual stack:** `vp check` = oxfmt + oxlint (plugins listed as eslint/typescript/react/jsx-a11y in `vite.config.ts`) + type-aware. **Not Prettier/ESLint CLI, not Next lint.**
- **Tested:** `vp check` exit **0** (225 formatted, 220 lint/type clean).
- **CI gap:** `.github/workflows/frontend-playwright-smoke.yml` runs `vp install`, `vp pm audit -- --audit-level=high`, `vp build`, Playwright. **No `vp check`, `vp lint`, `vp test`.**
- **Policy scripts:** `package.json` `check:policy` (architecture LOC 400 default, exceptions to 1020) **not in CI**.
- **Package manager:** pnpm 11.9.0 via vp; consistent.
- **Warnings:** vp check reported no warnings. `vp lint --deny complexity` is **errors**, blocking if added.
- **Recommended gate owner:** new job on frontend path (or the smoke workflow’s frontend steps) running `vp check` and `node scripts/check-frontend-architecture.mjs` after lowering exceptions to 800; keep Playwright separate.

## 9. Dependency Findings

**Manifests:** `backend/pyproject.toml` + `backend/uv.lock`; `frontend/package.json` + `frontend/pnpm-lock.yaml`. CI backend **does not install from uv.lock**.

### Backend

| Package | Direct/transitive | Current version | Target version | Update class | Security/support reason | Compatibility risk | Required verification | Finding ID |
|---|---|---|---|---|---|---|---|---|
| cryptography | Direct (`pyproject` L17) | 49.0.0 locked | 50.0.0 | **Major (bound `<50`)** | PYSEC-2026-3552 / CVE-2026-69247 PKCS#7 oracle | Bound currently **blocks** the fix; app uses Fernet + HMAC only — **PKCS7 APIs not referenced** (grep `pkcs7` empty). Reachability **low**. | Bump upper bound; `pytest` security/cookie/JWT tests; pip-audit | Q-DEP-BE-01 |
| fastapi | Direct | 0.139.2 | stay `<1` | none required from this scan | none from pip-audit export | — | — | Q-DEP-BE-02 |
| starlette | Direct pin ≥1.3.1 | 1.3.1 | follow FastAPI | minor later | none in this audit | FastAPI coupling | API tests | Q-DEP-BE-03 |
| ruff | Direct extra | 0.15.22 lock | current | none | lint | — | `ruff check` | Q-DEP-BE-04 |
| pyjwt / PYSEC-2025-183 | **Not in uv.lock** | n/a | n/a | n/a | CI ignore is unexplained | none | Remove ignore or document if pip resolver pulls it | Q-DEP-BE-05 |

Local `pip-audit --path .venv` (incomplete runtime venv): **no vulns**. `pip-audit --no-deps` on `uv export --frozen --extra dev`: **cryptography 49.0.0** only. Duplicate row is the same ID twice.

### Frontend

| Package | Direct/transitive | Current version | Target version | Update class | Security/support reason | Compatibility risk | Required verification | Finding ID |
|---|---|---|---|---|---|---|---|---|
| react-router (via react-router-dom) | Transitive of direct 7.18.1 | <7.18.2 vulnerable | 7.18.2 | Patch | GHSA-qwww-vcr4-c8h2 RSC CSRF | App uses `createBrowserRouter` SPA, **not RSC**. Reachability **low**. Still needed for `vp pm audit --audit-level=high` | `vp check`; smoke e2e | Q-DEP-FE-01 |
| undici | Transitive via jsdom/vitest | <7.29.0 | ≥7.29.0 | Patch (dev) | GHSA-4cwx-7wf7-3272 | Test/tooling path, not production bundle | `vp test`; audit | Q-DEP-FE-02 |
| nanoid | Transitive via postcss/vite | <3.3.18 | ≥3.3.18 | Patch (dev) | GHSA-2v37-7h3g-55p8 size-0 generator | Unlikely reachable unless custom nanoid(0) | audit; vp build | Q-DEP-FE-03 |
| react / react-dom | Direct | 19.2.7 | 19.2.8 | Patch | maintenance | low | vp check / test | Q-DEP-FE-04 |
| @tanstack/react-query | Direct | 5.101.2 | 5.101.4 | Patch | maintenance | low | vp test | Q-DEP-FE-05 |
| vite-plus | Direct dev | 0.2.5 | 0.2.9 | Patch/minor | toolchain | medium (vp CLI 0.1.14 vs package 0.2.5 already diverges) | vp check/build | Q-DEP-FE-06 |
| @testing-library/jest-dom | Direct dev | 6.9.1 | 7.0.1 | **Major** | none security in this scan | breaking test APIs | vp test | Q-DEP-FE-07 |
| jsdom | Direct dev | 29.1.1 | 30.0.1 | **Major** | pulls undici | test env | vp test | Q-DEP-FE-08 |
| @types/node | Direct dev | 25.9.5 | 26.x | Major types | none | TS 7 + Node 24 CI | vp check | Q-DEP-FE-09 |
| lucide-react | Direct | 1.25.0 | 1.33.0 | Minor | none | icon API | vp check | Q-DEP-FE-10 |

`vp pm audit -- --audit-level=high` exit **1**: 8 vulns, **3 high / 5 moderate**. CI frontend job would fail on current tree.

**Safe update batches**

1. **Frontend audit green:** `react-router-dom@7.18.2`; pnpm overrides or jsdom/undici/nanoid patches. Verify `vp check`, `vp test`, `vp pm audit -- --audit-level=high`.
2. **Frontend patch/minors:** react 19.2.8, query 5.101.4, radix patches, playwright 1.62.1. Separate from vite-plus bump.
3. **Frontend majors (own PR):** jest-dom 7, jsdom 30, @types/node 26, lucide 1.33 if breaking.
4. **Backend cryptography 50:** own PR; raise `cryptography` upper bound; verify Fernet cookie/JWT; pip-audit.
5. **Make CI use `uv.lock`:** `uv sync --frozen --extra dev` instead of naked pip resolve. Separate from version bumps.

Do not “update everything.” TypeScript 7 and vite-plus stay coupled; bump vite-plus only with `vp check`/`vp build`.

## 10. Other Verified Production Blockers

None found in this focused review that are independent P0/P1 **runtime** stop-launch issues. Cryptography CVE is **not reachable** on observed call sites. React Router advisory targets RSC mode this SPA does not use. Frontend **CI high-audit is red**, which is a **release-process P1** if that workflow is required to merge (Q-CI-FE-AUDIT).

## 11. Finding Register

| ID | Title | Area | Status | Severity | Confidence | Evidence | Owner | Depends on | Verification command |
|---|---|---|---|---|---|---|---|---|---|
| Q-GATE-LOC | Absolute ≤800 physical LOC not enforced; 37 files over | Quality gates | FAIL | P2 | high | §4 scan; ratchets 700+allowlist | tests/structure + CI | Q-LOC-* splits | proposed LOC scanner |
| Q-GATE-CC | Absolute CC≤15 not enforced; 202 Python + 8 TS >20 | Quality gates | FAIL | P2 | high | Radon JSON; vp lint --deny complexity | extraction/core + CI | Q-CC-* | radon + vp lint |
| Q-CI-BE-FMT | Backend format not in CI | CI | FAIL | P2 | high | backend-ci.yml vs local format pass | backend-ci.yml | none | `ruff format --check app tests` |
| Q-CI-FE-CHECK | Frontend vp check not in CI | CI | FAIL | P2 | high | frontend-playwright-smoke.yml | frontend workflow | none | `vp check` |
| Q-CI-FE-UNIT | Frontend unit tests not in CI | CI | FAIL | P2 | high | no vp test job | frontend workflow | none | `vp test` (unexecuted here) |
| Q-CI-LOCK | Backend CI pip-resolves instead of uv.lock | CI / deps | FAIL | P1 | high | backend-ci.yml L63-66 vs uv.lock | backend-ci.yml | none | `uv sync --frozen --extra dev` then pip-audit |
| Q-CI-FE-AUDIT | Frontend high audit fails on HEAD | CI / deps | FAIL | P1 | high | vp pm audit exit 1 | frontend lockfile | Q-DEP-FE-01..03 | `vp pm audit -- --audit-level=high` |
| Q-CI-PYJWT | pip-audit ignore PYSEC-2025-183 with no pyjwt in lock | CI | FAIL | P3 | high | workflow L70; uv.lock grep | backend-ci.yml | Q-CI-LOCK | pip-audit without ignore |
| Q-TOOL-VENV | Local backend .venv missing extras | Tooling | FAIL | P3 | high | python -m ruff missing | developer setup | none | `uv sync --extra dev` |
| Q-PYLINT-AP22 | Pylint size/complexity globally disabled | Lint | FAIL | P3 | high | pyproject L71-121 | pyproject / drop pylint or enable | Q-GATE-CC | pylint not in CI |
| Q-FE-ARCH-800 | Frontend architecture exceptions allow 1020/875 LOC | LOC | FAIL | P2 | high | check-frontend-architecture.mjs L17-24 | frontend scripts | Q-LOC frontend splits | `node scripts/check-frontend-architecture.mjs` |
| Q-DOC-NEXT | AGENTS.md claims Next.js | Docs | FAIL | P3 | high | AGENTS.md vs package.json | AGENTS.md | none | n/a |
| Q-DEAD-01 | Unused `collect_ecommerce_detail` | Dead code | FAIL | P3 | high | repo grep | extraction/pipeline.py | none | grep + pytest extraction |
| Q-DEAD-02 | Unused LLM HTML harvest helpers | Dead code | FAIL | P3 | high | grep | connectors/llm/prompt_rendering.py | none | grep + llm tests |
| Q-DEAD-03 | Unused browser_policy extend_after_block | Dead code | FAIL | P3 | high | grep vs fetch_context private copy | acquisition/fetch | none | grep + fetch tests |
| Q-DEAD-04 | Test-only `build_playwright_context_options` | Dead code | FAIL | P3 | medium | tests only | acquisition/browser_identity.py | none | browser_context tests |
| Q-DUP-01 | js_state/metadata helper clones | Duplication | FAIL | P3 | medium | jscpd | extraction/collectors | none | jscpd + collector tests |
| Q-DEP-BE-01 | cryptography 49 vs fix 50 blocked by `<50` | Deps | FAIL | P2 | high | pip-audit export; pyproject bound; no pkcs7 usage | pyproject cryptography | none | pip-audit + security tests |
| Q-DEP-FE-01 | react-router <7.18.2 high advisory | Deps | FAIL | P2 | high | audit; low RSC reachability | frontend package.json | none | audit + e2e |
| Q-LOC-INV | 37-file LOC inventory | LOC | FAIL | P2 | high | §4 | per-file owners | none | LOC scanner |
| Q-CC-INV-PY | 202 Python CC>15 | Complexity | FAIL | P2 | high | §5 | per-symbol owners | Q-LOC splits first where files huge | radon |
| Q-CC-INV-FE | 8 TS functions CC>20 | Complexity | FAIL | P2 | high | vp lint --deny complexity | frontend components | Q-FE-ARCH-800 | `vp lint --deny complexity` |
| Q-BE-RUFF | Backend ruff check green | Lint | PASS | P3 | high | ruff 0.15.22 | n/a | n/a | ruff check |
| Q-BE-MYPY | Backend mypy green | Types | PASS | P3 | high | mypy 2.3.0 | n/a | n/a | mypy app |
| Q-FE-CHECK | Frontend vp check green | Lint/format/types | PASS | P3 | high | vp check | n/a | n/a | vp check |
| Q-BE-FMT-LOCAL | Backend format green locally | Format | PASS | P3 | medium | ruff 0.14.10 not lock ruff | n/a | n/a | ruff format --check |
| Q-VUL-100 | Vulture 100 only Pydantic FP | Dead code | PASS | P3 | high | vulture min 100 | n/a | n/a | vulture --min-confidence 100 |
| Q-BE-PYTEST-CI | Full backend pytest in CI | Tests | UNVERIFIED | P2 | high | workflow present, not run here | backend-ci | n/a | `pytest tests -q` |
| Q-FE-TEST | Frontend unit tests | Tests | UNVERIFIED | P2 | high | not run | frontend | n/a | `vp test` |
| Q-FE-CC15 | oxlint max 15 inventory | Complexity | UNVERIFIED | P2 | medium | config not applied | vite.config lint.rules | Q-CC-INV-FE | proposed complexity: [error, 15] |
| Q-PIP-AUDIT-CI | pip-audit as CI pip-resolve | Deps | UNVERIFIED | P2 | medium | different resolver than lock | backend-ci | Q-CI-LOCK | CI log |

## 12. Recommended Work Slices

### Slice A — Quality-tool configuration (no behavior change)

- **Objective:** Commit Ruff settings, oxlint `complexity` max 15 (non-CI first or matching current 20), Vulture config, jscpd ignore file; document counting method (physical vs nonblank).
- **IDs:** Q-TOOL-VENV, Q-PYLINT-AP22, Q-DOC-NEXT, Q-FE-CC15
- **Why together:** Config-only, reviewable without splits.
- **Files:** `backend/pyproject.toml`, `frontend/vite.config.ts`, `AGENTS.md`, optional `jscpd.json`.
- **Preconditions:** none.
- **Verify:** `ruff check`, `vp check` (must stay green if max stays 20).
- **Blocking CI at end?** No (would fail absolute 15/800).

### Slice B — Delete confirmed dead code

- **Objective:** Remove Q-DEAD-01..03 after grep; optionally fold Q-DEAD-04.
- **IDs:** Q-DEAD-01, Q-DEAD-02, Q-DEAD-03, Q-DEAD-04
- **Why together:** Deletion-before-split reduces LOC/CC noise.
- **Files:** `pipeline.py`, `prompt_rendering.py`, `browser_policy.py`, maybe `browser_identity.py`.
- **Preconditions:** Slice A optional.
- **Verify:** focused pytest on extraction/llm/fetch; `vulture app --min-confidence 100`.
- **Blocking CI?** No.

### Slice C — Split production files >800 (extraction first)

- **Objective:** Bring production modules under 800 physical lines by responsibility, not `_misc` suffixes. Honor CODEBASE_MAP / INVARIANTS (no new layers; config stays in `core/config`).
- **IDs:** Q-LOC-INV (production rows), Q-GATE-LOC, Q-FE-ARCH-800
- **Why together:** Same gate; do tests in Slice D.
- **Files:** extraction collectors/engine/contracts/entities/result_building/pipeline; persistence/extraction_memory; enrichment/service; intelligence/service; `_detail.py`; frontend log-terminal + types.ts.
- **Preconditions:** Slice B preferred.
- **Verify:** existing extraction/architecture tests; frontend architecture script with lowered caps.
- **Blocking CI?** Not yet (tests still over).

### Slice D — Split mega-tests (AP-29)

- **Objective:** Split 20 test files >800 without dropping cases.
- **IDs:** remaining Q-LOC-*.
- **Why together:** Test-only, independent of runtime.
- **Files:** `backend/tests/component/test_crawl_fetch_runtime.py` et al.; `crawl-run-screen.test.tsx`.
- **Preconditions:** none strictly.
- **Verify:** `pytest` on split files; `vp test` affected.
- **Blocking CI?** LOC gate can become blocking after C+D.

### Slice E — Reduce CC ≤15 by owner

- **Objective:** Decompose callables >15; shrink COMPLEX_FUNCTION_DEBT then delete it.
- **IDs:** Q-CC-INV-PY, Q-CC-INV-FE, Q-GATE-CC
- **Why together:** After files are splittable; complexity often lives in the same owners as Slice C.
- **Files:** `field_coerce_text.py`, `field_coerce_dispatch.py`, `browser_detail.py`, `result_building.py`, `js_state.py`, `pipeline.py`, frontend page/hooks listed in §5.
- **Preconditions:** Slice C for huge files.
- **Verify:** radon filter >15 empty; `vp lint --deny complexity` with max 15.
- **Blocking CI?** Yes after inventory empty.

### Slice F — Lint/format CI (existing commands only)

- **Objective:** Add `ruff format --check` to backend-ci; add `vp check` (+ optionally `check:policy`) to frontend CI.
- **IDs:** Q-CI-BE-FMT, Q-CI-FE-CHECK
- **Why together:** Already-green local commands.
- **Files:** GitHub workflows only.
- **Preconditions:** format already green; keep complexity rule off or at 20 until Slice E.
- **Verify:** CI on PR.
- **Blocking CI?** Yes for lint/format/types.

### Slice G — Dependency patches + lockfile CI

- **Objective:** Green high audit; uv frozen install in CI; drop stale pyjwt ignore.
- **IDs:** Q-CI-LOCK, Q-CI-FE-AUDIT, Q-CI-PYJWT, Q-DEP-*
- **Why together:** Resolver/audit consistency. Keep cryptography 50 and jsdom 30 in sub-batches as in §9.
- **Preconditions:** none for router patch; cryptography bound change isolated.
- **Verify:** pip-audit / vp pm audit; focused auth and e2e.
- **Blocking CI?** Audit already blocking; will stay red until G.

### Slice H — Enable absolute LOC/CC CI gates

- **Objective:** Blocking scanners with documented exclusions only.
- **IDs:** Q-GATE-LOC, Q-GATE-CC
- **Preconditions:** C, D, E green locally.
- **Verify:** commands in §13.
- **Blocking CI?** Yes. Do not ship exemptions.

## 13. Exact Proposed CI Gate Commands

Working directories as shown. Prefer `uv run --frozen --extra dev` once Slice G lands.

**Tested (use as-is)**

```powershell
# backend (cwd backend)
uvx --from ruff==0.15.22 ruff check app tests
uv run --frozen --extra dev python -m mypy app
uvx --from vulture==2.16 vulture app --min-confidence 100 --exclude .venv
uvx --from radon==6.0.1 python -c "from pathlib import Path; from radon.complexity import cc_visit; ..."
# frontend (cwd frontend)
vp check
vp lint --deny complexity
vp pm audit -- --audit-level=high
```

`ruff format --check app tests` tested with **ruff 0.14.10** only → exit 0. **Proposed** with lockfile Ruff: `uvx --from ruff==0.15.22 ruff format --check app tests` (must re-run).

**Proposed LOC ≤800 (must validate on CI image):** physical `splitlines()` count, same exclusions as §4. Do not use `ast.unparse` (AP-28). Align with either total physical (this inventory) or nonblank (existing tests) — pick one and change tests/CI together.

**Proposed complexity ≤15 Python:** Radon `cc_visit`; fail if any block `.complexity > 15` under `backend/app`, `backend/tests` (if tests included), excluding `.venv`. **Do not use `--min C`.**

**Proposed complexity ≤15 frontend:** add to `vite.config.ts` `lint.rules`: `'complexity': ['error', 15]` then `vp lint`. **Unexecuted at 15.** Tested equivalent: `vp lint --deny complexity` (max 20).

**Proposed tests for quality-tool changes:** focused pytest on `tests/unit/test_final_architecture_ownership.py` and `tests/unit/test_extraction_architecture.py`; frontend `node scripts/check-frontend-architecture.mjs`. Full `pytest tests -q` exists in CI but was **not run here** (AGENTS.md).

**Proposed dependency audits:**

```powershell
# backend: after uv sync --frozen --extra dev
uvx pip-audit --path .venv --vulnerability-service osv
# or hashed export
uv export --frozen --extra dev --no-hashes -o $env:TEMP\reqs.txt
uvx pip-audit --no-deps -r $env:TEMP\reqs.txt --vulnerability-service osv
# frontend
vp pm audit -- --audit-level=high
```

`pip-audit . --locked` **failed** (no poetry/Pipfile lock). Do not use that command.

**jscpd (tested, optional future):** command in §7. Not a stated absolute requirement.

## 14. Verification Log

| Working directory | Exact command | Exit code | Duration | Result summary | Truncation / limits |
|---|---|---:|---|---|---|
| repo root | `git rev-parse --abbrev-ref HEAD`; `git rev-parse HEAD`; `git status --porcelain`; `git log -1` | 0 | ~17s (batch) | main, bfc76636, clean | none |
| backend | `python --version`; `.venv` python `--version` | 0 | same batch | 3.14.6 system; 3.12.13 venv | none |
| backend | `.venv\Scripts\python.exe -m ruff` | 1 | ~12s | No module named ruff | incomplete venv |
| repo | `python %TEMP%\crawlerai_loc_scan.py` | 0 | ~25s | 808 files; 37 >800 total | none |
| backend | `uvx --from radon==6.0.1 python %TEMP%\crawlerai_cc_scan.py` | 0 | ~16s | 202 hits; 0 parse errors | listed in JSON |
| backend | `uvx --from vulture==2.16 vulture app --min-confidence 100 --exclude .venv` | 3 | ~15s | 1 hit `__context` | none |
| backend | same min-confidence 80 | 3 | ~15s | same 1 hit | none |
| backend | same min-confidence 60 | 3 | ~14s | 823 lines | output saved 78KB |
| backend | `uvx --from ruff==0.14.10 ruff check app tests` | 0 | ~13s | All checks passed | none |
| backend | `uvx --from ruff==0.14.10 ruff format --check app tests` | 0 | ~14s | 552 files formatted | none |
| backend | `uvx --from ruff==0.15.22 ruff check app tests` | 0 | ~16s | All checks passed | none |
| backend | `uv run --frozen --extra dev python -m mypy app` | 0 | ~153s | 381 files; annotation-unchecked notes | uv installed 28 pkgs into cache |
| frontend | `vp check` | 0 | ~42s | 225 fmt pass; 220 lint/type pass | none |
| frontend | `vp lint --deny complexity` | 1 | ~15s | 8 functions >20 | default max 20 |
| frontend | `vp lint --deny complexity:15` | 0 | ~17s | **No effect** (syntax ignored) | cannot treat as max 15 |
| frontend | `vp lint -c %TEMP%\oxlintrc-cc15.json` | 1 | ~13s | `-c` cannot be used multiple times | max 15 inventory incomplete |
| frontend | `npx oxlint@1.73.0 -c ...` | 1 | ~18s | vp oxlint LSP wrapper | not a real scan |
| repo | `npx --yes jscpd@4.0.5 ...` | 0 | ~49s | 17 clones, 0.18% | JSON ~8k lines |
| frontend | `vp pm audit -- --audit-level=high` | 1 | ~18s | 3 high, 5 moderate | none |
| frontend | `pnpm outdated` | 0 | same | table of current vs latest | latest≠compatible |
| backend | `uvx pip-audit --python .venv\...` | 2 | ~32s | unsupported flag | pip-audit 2.10.1 |
| backend | `uvx pip-audit . --locked` | 1 | ~14s | no lockfiles found | uv.lock not poetry |
| backend | `uvx pip-audit --path .venv --vulnerability-service osv` | 0 | ~15s | No known vulnerabilities | incomplete env |
| backend | `uv export --frozen --extra dev --no-hashes` + `pip-audit --disable-pip -r` | 1 | ~15s | needs hashes | — |
| backend | `uvx pip-audit --no-deps -r %TEMP%\crawlerai-uv-export.txt --vulnerability-service osv --desc` | 1 | ~152s | cryptography PYSEC-2026-3552 | duplicate ID row |
| frontend | `vp --version`; `node --version`; `pnpm --version` | 0 | in vp check batch | vp 0.1.14; node 26.7.0; pnpm 11.9.0 | none |

**Not run:** `pytest tests -q`, `vp test`, `vp build`, Playwright, bandit, pylint as a gate, basedpyright, CodeQL, gitleaks, live npm registry “newest compatible” for every Python package beyond lock+audit.

## 15. Unverified Items and Questions

- Whether GitHub Actions on this commit is currently red (frontend audit) — inferred from local audit, not a downloaded Actions log.
- Full backend pytest and frontend vitest/Playwright status at this commit.
- Complete TypeScript inventory of callables with CC 16–20 (oxlint max 15 not applied).
- `ruff format --check` under Ruff **0.15.22**.
- pip-audit result of **CI’s** `pip install -e ".[dev]"` resolver vs `uv.lock` (may differ).
- Newest stable versions on PyPI for every direct backend pin except those inspected via lock+OSV (network used for OSV/npm audit/pnpm outdated/CVE writeups).
- Whether production deploy uses `psycopg2` prod extra vs local `psycopg2-binary`.
- Pre-commit / vp `staged` actually installed on developer machines.
- Reachability of the 5 moderate npm advisories (audit output truncated to highs in the tool result; command reported 8 total).

