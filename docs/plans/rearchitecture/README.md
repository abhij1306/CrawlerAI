# Extraction-cascade rearchitecture status

This directory preserves the design record for the extraction-cascade rearchitecture and identifies the remaining close-out work after the implementation checkpoint merged in PR #23 on 2026-07-16.

## Current source of truth

- `SLICE-4-HANDOFF.md` records the detailed implementation history, invariants, and original remaining-slice scope. Its Slice 4 and LEARN-ONCE sections are completed.
- `LEARN-ONCE-STATUS.md` records the completed LEARN-ONCE hardening work.
- `EVAL-TEST-SITES.md` is the current live/sandbox validation corpus.
- This README supersedes older completion markers in the preserved planning artifacts below.

## Completed and merged

- Extraction cascade foundation and surface schemas.
- Commerce listing cascade and job-detail cascade integration.
- LEARN-ONCE compile/replay, persistence, grounding, lease, drift, and retry hardening.
- Bounded multi-rung extraction retry contract.
- Rung-2 browser network-capture fulfillment and `network_json` replay visibility.
- Unified listing-card selection, admission, canonical identity, query normalization, and total-unique traversal `card_count`.

## Still pending

1. Finish listing readiness shell/no-results classification and coordinated `diagnose.v3` discovery/network provenance.
2. Extend the eval harness to load `extraction_v3_label.v1`, including URL-aware fixtures and variant scoring.
3. Capture and revalidate all eight labeled commerce-detail HTML fixtures.
4. Run baseline/candidate scoring and retain every selector floor unless a genuinely independent selector-free candidate meets or beats its baseline.
5. Reconcile the exact final non-blank LOC and complex-function debt ledgers.
6. Refresh stale extraction documentation after the final implementation shape is known.
7. Run deterministic sandbox and selected live-retailer validation.
8. Pass the final backend gate: one full `pytest tests -q`, `ruff check .`, `mypy app`, and `import app.main` smoke test.

## Preserved historical plans

These files are retained for rationale and sequencing context. They are historical plans, not a statement that every task remains open:

- `DECISIONS.md`
- `context-brief.md`
- `REMAINING-SLICES-IMPLEMENTATION-PROMPT.md`
- `subplans/extraction-cascade.md` and summary
- `subplans/acquisition-ladder.md` and summary
- `subplans/crosscut-migration.md`

When a historical plan conflicts with current code or the status above, trust current code, architecture tests, and this README.
