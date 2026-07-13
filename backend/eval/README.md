# Extraction Evaluation

This owner evaluates frozen capture artifacts. It never calls live sites and it
never changes extraction state.

The runtime under test is one recipe-first flow:

```text
active release.v2 recipe -> executor -> validator/publisher
no active recipe or typed miss -> deterministic compiler -> candidate executor
optional enabled model -> grounded binding proposals -> compiler -> candidate executor
```

Models may propose bindings only. Evaluation must reject any report that treats
model values, selectors, source pins, or a generic record-producing tier as an
extraction path.

Run from `backend/`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m eval.corpus --stats
.\.venv\Scripts\python.exe -m eval.corpus --stats --surface ecommerce_listing
.\.venv\Scripts\python.exe -m eval.corpus --stats --surface job_detail
.\.venv\Scripts\python.exe -m eval.corpus --stats --surface job_listing
```

Artifacts are eligible only when their run id meets the configured accepted
evidence threshold. Every listing/job surface needs at least 20
human-verified labels before it can gate a release. Proposal files are review
inputs, never gold truth. Old run reports are regressions only; they cannot
close fresh live acceptance.

Do not use `--require-pass` until accepted artifacts and human labels exist for
every required surface. The final acceptance slice records fresh live run and
result IDs, recipe state/version, compiler/model state, binding outcomes, and
causal diagnosis links in the active recovery plan.
