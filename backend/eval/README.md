# Extraction V3 Eval Harness

Phase 0 gate for the confidence-tiered extraction plan.

Commands from `backend/`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m eval.corpus --stats
.\.venv\Scripts\python.exe -m eval.corpus --write-proposals
.\.venv\Scripts\python.exe -m eval.run --baseline
.\.venv\Scripts\python.exe -m eval.representation --audit-samples
.\.venv\Scripts\python.exe -m eval.grounding --verified-labels
```

`--write-proposals` bootstraps label files from frozen artifacts and audit data.
Those files are review inputs only. A page counts as gold only after a human sets
`human_verified: true`.
