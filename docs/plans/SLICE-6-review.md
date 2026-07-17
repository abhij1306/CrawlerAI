Found 6 actionable issues.

High — Artifact rename breaks active consumers and can violate exactly-three invariant.
backend/app/persistence/url_result_artifacts.py:50-75 changes page.html/record.json to source.html/result.json, but active consumers still use old names:

backend/app/evaluation/baseline.py:62-70 silently treats every new result as zero records.
backend/app/evaluation/grounded_corrections.py:279-287 fails representative replay as artifact missing.
frontend/components/crawl/use-run-recipe-actions.ts:43-47 submits grounding against a nonexistent artifact.
Also, republishing into an existing result directory leaves old files beside new ones, producing five files because the writer never removes legacy names. Either retain canonical names or update all consumers and add atomic cleanup/migration logic plus a republish test.

High — Readiness and extraction still count different artifact sets.
backend/app/acquisition/browser_readiness.py:401-407 counts only the current top-level HTML. Extraction reads base HTML plus rendered fragments and visual HTML through LISTING_HTML_ARTIFACT_IDS. A shadow-DOM/recovery case can therefore report listing_card_count=0 and not-ready while extraction finds records.
backend/tests/unit/test_job_listing_cascade.py:160-187 misses this because it passes _RENDERED_FRAGMENT directly to readiness while passing _JS_SHELL_HTML plus the fragment to extraction. Test the real split inputs and make readiness consume the same coordinated artifact set or establish one shared aggregate count.

High — Architecture/LOC ledgers are not reconciled; required gates fail.
The focused architecture run reports four failures. Newly introduced failures include:

backend/app/core/config/extraction_semantic_surface.toml:59: surfaces.py budget remains 258, actual is 274.
backend/tests/unit/test_final_architecture_ownership.py:52: probe_browser_readiness debt remains complexity 30, actual is 39.
backend/tests/unit/test_final_architecture_ownership.py:177-184: total application LOC is 86,139 against 85,727.
Reconcile by reducing the new growth or explicitly updating both ratchet ledgers with justified final values. Do not ship with architecture gates red.

Medium — Shell text does not override broad no-results matches.
backend/app/acquisition/browser_readiness.py:439-458 computes both signals but marks ready_empty whenever a no-results phrase appears, even when shell_detected=True. A loading SPA containing stale “No jobs found” text becomes terminal-ready and fast-finalizes. Require a no-results marker without shell evidence, or scope the marker to the active results container and confirm stability across probes. Add a combined loading-plus-no-results test.

Medium — Exhausted URL budget still starts another acquisition.
backend/app/crawl/pipeline/retry/stage.py:185-206 passes remaining_url_budget_seconds() directly, including 0.0, then commits and invokes acquisition. This creates an already-expired fetch deadline, increments the escalation count, and records a generic browser failure instead of skipping as budget-exhausted. Guard before request construction/commit/acquire when remaining budget is non-positive, and add an expired-budget test.

Medium — Failed or timed-out escalation attempts disappear from diagnose.v3.
backend/app/crawl/pipeline/retry/stage.py:201-227 creates and propagates EscalationAttemptDiagnostics only after acquisition succeeds. The exception path at :229-251 updates browser diagnostics but never appends the capability request or failure outcome. Thus the most important failed rung is absent from diagnose.v3 escalation history. Create the typed attempt before acquisition and propagate a typed outcome/error classification on success, timeout, and failure.

Verification:

New focused behavior tests: 40 passed.
Architecture-focused tests: 4 failed.
git diff --check also reports trailing blank-line errors in four changed files.

I have completed my analysis. Everything compiles, all 40 focused tests pass, and ruff is clean. Below are my findings for the main agent. Per my role, I did not modify any code.

Analysis: §6 readiness + diagnose.v3 (5f8d0c9..308ed61)
Correctness issue — rename not fully propagated (high priority)
The commit renamed the two URL artifacts page.html→source.html and record.json→result.json in the writer (url_result_artifacts.py) and in record_artifacts.py, but two readers outside the changed set still open the old names and will fail at runtime:

backend/app/evaluation/grounded_corrections.py:280 — artifact_uri = f"runs/{run.id}/results/{url_result.id}/page.html". This is the only path read; read_text will now raise representative_artifact_missing for every bundle written by the new writer. Should be source.html.
backend/app/evaluation/baseline.py:66 — record_path = result_dir / "record.json". Falls back to {"record_count": 0, "records": []} when missing, so baselines will silently report zero records for all new bundles. Should be result.json (and the module docstring at line 4 also references record.json).
These aren't in the diff, so they're easy to miss, but the rename is an artifact-contract change that breaks them. Worth confirming with the main agent whether they should be updated in this change or are intentionally out of scope. (The invariant is "exactly three URL artifacts by fixed name" — readers must agree.)

Duplication / simplification
listing_cards.py card_diagnostics_from_html empty-case dict (~line 45) — the hand-written empty dict is exactly ListingCardDiagnostics().as_dict() (verified identical). Replace the literal with ListingCardDiagnostics().as_dict() to remove the duplication and keep it in sync with the dataclass shape automatically.

retry/stage.py:214-218 dead defensive branch — escalation_attempts is now a declared field on URLProcessingContext (default list), and context is typed URLProcessingContext. The getattr(context, "escalation_attempts", None) + isinstance(... list) + setattr dance is unreachable defensiveness; it can collapse to context.escalation_attempts.append(attempt).

retry/stage.py:207-225 duplicated fields — rung and attempt are both assigned context.browser_escalation_count in the model and again in the summary dict, and max(1, max_attempts) appears three times. Minor: the summary-dict rung/attempt/max_attempts just echo the last appended attempt; could derive them from attempts[-1] (or a small local) instead of recomputing, reducing the four literal repetitions. Low value — only take if touching this block.

Tests
New tests (test_browser_readiness.py, test_diagnose.py, test_url_result_artifacts.py, and the additions to test_job_listing_cascade.py / test_escalation_ladder.py) each cover a distinct invariant (shell rejection, ready_empty, timeout-not-ready, three-artifact naming, count/readiness/extract agreement, security scrubbing, escalation provenance). No redundant tests spotted; they follow the existing pytestmark = pytest.mark.unit + SimpleNamespace acquisition-fixture pattern.
test_diagnose.py asserts "private@example.test"/"token=secret" absent from the serialized discovery section — good security-invariant coverage of the bounded provenance.
No issues found with
No surface literals leaked into readiness logic — probe_browser_readiness now drives off surface_spec(...).cardinality and spec-provided patterns; the shell/no-results regexes in cascade.py are generic UI states, not host/platform names (invariant preserved).
Config centralization (diagnose.py constants, cascade.py pattern tables) is clean; the diagnose.py module aliases SCHEMA_VERSION = DIAGNOSE_SCHEMA_VERSION etc. rather than duplicating values.
Bounds/limits applied consistently (escalation ≤4, network provenance ≤10, rejection samples/reasons capped, shrink steps added for discovery.*).
Net recommendation: fix the two stale readers (correctness), apply #1 and #2 (clear wins), and treat #3 as optional. No behavior-changing refactors beyond these are justified.