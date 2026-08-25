# CrawlerAI SonarQube valid-issue report

**Date:** 2026-08-25
**Server:** local Community Build 26.3.0.120487 (`C:\Tools\sonarqube-26.3.0.120487`, `http://localhost:9000`)
**Project key:** `crawlerai-local`
**Dashboard:** http://localhost:9000/dashboard?id=crawlerai-local
**Revision scanned:** `fca3b12bca0052fc2cbaa647afe37e723858d14a`
**CE task:** `0c6b8d5d-cfa1-4e24-8032-7732a3c2f88c` (SUCCESS)
**Scope:** `backend/app`, `frontend/src`, `frontend/app`, `frontend/components`, `frontend/lib` (tests and `node_modules` excluded)
**Python:** 3.12 profile

This is a reviewed subset. Sonar opened **647 issues** and **34 hotspots**. Most are style, duplicate literals, or analyzer false positives. Only items below are treated as real product risk or real maintainability debt.

## Remediation closure

The reviewed remediation scope is closed on 2026-08-25. PR `#64` supplied the main implementation; the remaining residuals were corrected in the working tree on revision `f49509018c76b415a89e26b71af58f59bcd66e83`.

- Canonical static gate passed, including Ruff, mypy, VitePlus, LOC, and complexity.
- The affected selector reached 1,293 passes before exposing one acquisition diagnostic-wrapper regression and one load-sensitive batch timeout. The wrapper contract was corrected, the batch case passed alone, and the required retry delta passed 393 tests.
- Processed closure scan: CE task `d9b690f8-d57a-431e-a7c8-a39ca299794d`, analysis `d6758fa2-423c-48fd-8e57-213f581fd34e`, status `SUCCESS`.
- That scan cleared every original audited residual except rejected V1. It found one new complexity relocation in a DOM helper; the helper was reduced locally from Sonar 19 to Radon 7 while keeping `dom.py` at its 1,217-line ceiling.
- Follow-up CE task `16ec8733-7364-4dc6-a69c-9f02dababb04` was submitted but intentionally not polled further at user direction. No additional Sonar run or query was made.

V1 remains rejected. Unnamed complexity findings remain outside this audit's remediation scope.

## Intermediate post-merge verification

PR `#64` merged as revision `f49509018c76b415a89e26b71af58f59bcd66e83`, but the remediation plan is **not complete**.

- Fresh scan CE task: `df70770a-9a62-4b27-b0a6-4b1f85a594f6` (`SUCCESS`)
- Analysis: `316713e0-5673-4d10-9abf-7266eaed0dbb`
- Scope and Python profile: unchanged from the reviewed baseline
- Targeted-rule query: 87 open issues — 79 `python:S3776`, two `python:S7503`, two `python:S5713`, and one each of `python:S1172`, `python:S1871`, `python:S112`, and `python:S7497`

Audited areas cleared by the refreshed scan: backend/frontend `S5852`, parameter-count `python:S107`, frontend complexity, frontend accessibility (`S6848`, `S6819`), and duplicate CSS (`S4666`). Eight of the 13 named backend complexity targets also cleared.

Valid residuals at the merged revision:

| Rule | Current location | Residual |
| --- | --- | --- |
| `python:S7503` | `crawl/pipeline/retry/stage.py:214`; `crawl/pipeline/runtime_helpers.py:70` | Two audited fake-async helpers remain. |
| `python:S1172` | `acquisition/browser_page_flow.py:126` | `browser_engine` remains unused after the argument-list refactor. |
| `python:S112` | `acquisition/fetch/fetch_context.py:337` | Audited generic acquisition exception remains. |
| `python:S1871` | `core/records/url_identity.py:628` | Audited identical URL-token branch remains. |
| `python:S5713` | `core/records/js_state_scope.py:332`; `acquisition/fetch/fetch_context.py:304` | One audited and one changed-file redundant exception tuple remain. |
| `python:S3776` | `core/shared/field_coerce.py:194`; `core/records/structured_variant_state.py:172`; `extraction/collectors/dom.py:281,340,549` | Five named complexity targets remain above 15 (20, 18, 22, 19, and 24 respectively). |

The remaining 74 `python:S3776` findings are outside the plan's named complexity scope. V1 remains open in Sonar as `python:S7497`, but is rejected below based on regression evidence.

## Headline measures

| Metric | Value |
| --- | --- |
| LOC | 106,472 |
| Bugs | 2 |
| Vulnerabilities | 0 |
| Security hotspots (to review) | 34 |
| Code smells | 645 |
| Duplicated lines | 0.1% |
| Maintainability rating | A |
| Security rating | A |
| Reliability rating | C (driven by the two bugs) |

## Valid issues (fix these)

### P1 — correctness

| ID | Rule | Location | Why it is valid |
| --- | --- | --- | --- |
| V2 | `python:S7503` | `backend/app/crawl/batch_runtime.py:90` `_prewarm_browser_pool` | Marked `async` and always `return None` with no await. Callers think they prewarm a pool. Dead no-op. |
| V3 | `python:S7503` | `backend/app/crawl/pipeline/retry/stage.py:143`, `acquisition/fetch/attempt_plan.py:88`, `crawl/pipeline/runtime_helpers.py:31`, `intelligence/discovery.py:414`, `mcp_server/tools.py:32` | Async functions with no await. Misleading concurrency contract; extra event-loop hops for no work. |

### P1 — untrusted-input ReDoS (hotspots, MEDIUM)

Crawler feeds page HTML, URLs, and log text into these regexes. A hostile or huge page can stall a worker. Treat as real DoS risk, not crypto.

| Rule | Locations |
| --- | --- |
| `python:S5852` | `acquisition/variant_endpoint_expansion.py:102`; `core/records/html_helpers.py:113`; `core/records/url_identity.py:110,148`; `core/shared/field_coerce.py:448,460,478`; `core/shared/field_coerce_text.py:534`; `core/shared/text_coerce.py:105`; `core/shared/url_utils.py:462`; `enrichment/shopify_repository.py:178`; `extraction/pipeline.py:672` |
| `typescript:S5852` | `frontend/components/crawl/log-terminal-utils.ts:133,205`; `frontend/components/ui/dropdown.tsx:15`; `frontend/lib/crawl/format.ts:50` |

Highest-value first: `html_helpers.py` dotted-assignment regex on script text, `url_identity.py`, and `field_coerce.py` price/text patterns.

### P2 — unused parameters (dead contract)

These are real: names sit on public/internal signatures and are never read. That hides stale pipeline wiring.

| Location | Unused |
| --- | --- |
| `acquisition/fetch/fetch_context.py:190` | `engine_attempts` |
| `acquisition/fetch/attempt_host_policy.py:36` | `proxy` |
| `extraction/resolution/variant_rollup.py:489` | `existing_fact_keys` |
| `crawl/pipeline/learn_once.py:212` | `run_id` |
| `crawl/pipeline/persistence.py:515-517` | `run`, `acquisition_result`, `preliminary_source_url` |
| `extraction/validation.py:34` | `requested_fields` |
| `extraction/jobs.py:222` | `page_url` |
| `core/redis.py:153` | `operation_name` |
| `crawl/batch_runtime.py:164` | `settings_view`, `run` |
| `enrichment/llm_diagnostics.py:316` | `product` |
| `intelligence/discovery.py:91` | `source_domain_value` |

### P2 — parameter explosions (real design debt)

These match how acquisition/extraction actually grew: too many args, hard to test, easy to pass the wrong neighbor.

| Function | Params | File |
| --- | --- | --- |
| `fetch_page` | 22 | `acquisition/fetch/fetch_context.py:206` |
| `browser_fetch` | 21 | `acquisition/browser_fetch_runner.py:607` |
| `build_browser_diagnostics` | 20 | `acquisition/browser_result_builder.py:588` |
| `serialize_browser_page_content` | 16 | `acquisition/browser_page_flow.py:236` |
| `settle_browser_page` | 15 | `acquisition/browser_settle.py:313` |
| `recover_browser_challenge` | 14 | `acquisition/browser_recovery.py:187` |
| `process_single_url` | 14 | `crawl/pipeline/extraction_loop.py:100` |
| `record_acquisition_contract_outcome` | 14 | `crawl/profile/acquisition_contract.py:337` |

Fix by grouping into existing request/context objects. Do not add a new layer.

### P2 — cognitive complexity hotspots

88 `python:S3776` hits. Valid where complexity is far above 15. Worst first:

| Complexity | Location |
| --- | --- |
| 33 | `core/shared/field_coerce.py:194` |
| 33 | `core/records/structured_variant_state.py:65` |
| 30 | `extraction/collectors/dom.py:538` |
| 30 | `core/records/structured_variant_state.py:176` |
| 29 | `extraction/collectors/dom.py:277` |
| 29 | `crawl/batch_runtime.py:350` `_process_urls_in_parallel` |
| 28 | `extraction/collectors/dom.py:333` |
| 27 | `intelligence/discovery.py:199` |
| 26 | `extraction/representation/flat_map.py:251` |
| 26 | `connectors/llm/config_service.py:165` |
| 25 | `core/request_body_limit.py:36` |
| 25 | `core/records/divergence.py:113` |
| 25 | `core/logfire_integration.py:62` |

Frontend: `crawl-target-card.tsx:48` (19), `domain-memory/utils.ts:73` (18), `ui/field.tsx:11` (17), `lib/ui/syntax.ts:27` (17).

### P2 — frontend accessibility

Native-control rules on custom widgets. Valid for keyboard/screen-reader use of crawl UI.

- `frontend/components/ui/dropdown.tsx` (`typescript:S6848`, `S6819`) — non-native interactive + `option`/`combobox` roles
- `frontend/components/crawl/records-table.tsx` (`S6819`) — `table`/`row`/`cell` roles instead of `<table>`
- `frontend/components/ui/tooltip.tsx:76` (`S6848`)

### P3 — smaller valid smells

- `python:S5713` redundant exception classes in `core/security.py:82` (if `Argon2Error` already covered), `extraction_memory/recipe_artifacts.py`, `js_state_scope.py`, `field_coerce.py`, `enrichment/deterministic.py`, `variant_endpoint_expansion.py`. Dead catch arms hide which errors are actually handled.
- `python:S1871` identical branch bodies in `core/records/html_helpers.py:46-48` and `core/records/url_identity.py:573-579`. Behavior OK; merge or comment why they stay split.
- `css:S4666` `frontend/app/globals.css:1006` and `:1022` both define `.crawl-terminal`. Second block is intentional font-synthesis override; merge into one rule.
- `python:S112` bare `Exception` in `acquisition/fetch/fetch_context.py:371` and `planned_http.py:81`. Broad catch on fetch path; narrow to transport failures.

## Reviewed and rejected (do not treat as bugs)

| Finding | Verdict |
| --- | --- |
| V1 / `python:S7497` `browser_stage_runner.py:98` | **False bug.** Caller cancellation propagates out of the stage runner. Teardown intentionally consumes cancellation from the already-cancelled child task. `backend/tests/unit/test_browser_stage_runner.py` proves caller cancellation escapes after cleanup and stage timeout remains `TimeoutError`. |
| `typescript:S7727` `use-run-log-stream.ts:161` `.reduce(appendLiveLog)` | **False bug.** `appendLiveLog(current, incoming)` ignores extra `reduce` args. |
| `python:S3516` `batch_runtime.py:282,350` “always same return” | **False.** `_record_url_result` and `_process_urls_in_parallel` return varying `verdict` / counts. Analyzer collapsed the tuple shape. |
| `python:S5655` `_attempt_browser_rung` type mismatch | **False.** Call site matches `(context, fetched, request, ...)`. |
| `python:S5864` `proxy_secrets.py:127` iterate `references` | **False.** Guarded with `isinstance(references, list)`. |
| 0 vulnerabilities | No confirmed injection/authz flaws in this scan. |
| `python:S3330` CSRF cookie without HttpOnly | **Expected.** Double-submit CSRF must be JS-readable. Session cookie is already `httponly=True`. |
| `python:S1313` IPs in `core/config/security_rules.py` | **Expected.** SSRF denylist (`169.254.169.254`, CGNAT, Azure IMDS). |
| `S5332` “use https not http” | **Noise for a crawler.** HTTP targets, Playwright proxy, and scheme detection are required. |
| `typescript:S2245` `Math.random` | **Low.** Request-id fallback only when `crypto.randomUUID` missing. Not a secret generator. |
| `python:S1192` duplicated field-name strings (`product.url`, `offer.price`, …) | **Noise.** Canonical field names already live in config/surfaces; forcing more constants here is churn. |
| `python:S2208` wildcard imports in `extraction_rules/_*.py` | **Config composition.** Style only. |
| `python:S8396` optional FrozenModel fields without defaults | **Likely noise.** Call sites must pass full entities; defaults would hide missing wiring. |
| Most `typescript:S7763/S7764/S7781/S6759/S6571` | React/TS style (useless fragments, unicorn prefs). Not defects. |

## What not to do next

- Do not raise complexity/LOC gates to silence these.
- Do not “fix” HTTP scheme, denylist IPs, or CSRF HttpOnly.
- Do not add a Sonar-specific compatibility layer. Fix unused params and cancel propagation in the owning modules (`acquisition/`, `crawl/batch_runtime.py`, `extraction/`).

## Suggested fix order

1. Preserve V1 production behavior and its cancellation/timeout regressions.
2. Remove `async` from the two residual S7503 helpers and update callers.
3. Remove the residual browser parameter and correct the remaining exception/branch findings.
4. Reduce the five residual named complexity callables to 15 or less.
5. Run the canonical check/test selectors and repeat the targeted Sonar query before closure.

## Scan notes

- Scanner: SonarScanner CLI 8.1.0.6389 (`C:\Tools\sonar-scanner-8.1.0.6389-windows-x64`).
- `backend/app/data/enrichment/shopify_categories.json` skipped (>20MB).
- Missing git blame on 6 uncommitted acquisition/url-safety files; issue authors may be blank there.
- Local Sonar admin login was not `admin`/`admin`. Password was reset locally so this scan could authenticate. Change that admin password after you are in. Do not commit tokens.
- User token for scanner lives only in `%USERPROFILE%\.sonar\` (not in this repo).
