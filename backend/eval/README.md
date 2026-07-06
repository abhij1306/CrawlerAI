# Extraction V3 Eval Harness

Phase 0 gate for the confidence-tiered extraction plan.

Commands from `backend/`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m eval.corpus --stats
.\.venv\Scripts\python.exe -m eval.corpus --write-proposals
.\.venv\Scripts\python.exe -m eval.run --baseline
.\.venv\Scripts\python.exe -m eval.run --engine v3 --tier generalized --no-recipes --no-selectors --out eval\reports\v3_gate.json
.\.venv\Scripts\python.exe -m eval.run --engine v3 --tier generalized --no-recipes --no-selectors --require-pass
.\.venv\Scripts\python.exe -m eval.representation --audit-samples
.\.venv\Scripts\python.exe -m eval.grounding --verified-labels
```

`--write-proposals` bootstraps label files from frozen artifacts and audit data.
Those files are review inputs only. A page counts as gold only after a human sets
`human_verified: true`.

The V3 gate report is allowed to be red while slices are still in progress.
Use `--require-pass` only for a hard gate: it exits nonzero when `gate_passed`
is false. `--llm-config <json>` may point at a generalized-extraction config
snapshot when the gate should invoke the hosted model instead of reporting
`generalized_adapter_missing` / `generalized_tier_not_invoked`.
