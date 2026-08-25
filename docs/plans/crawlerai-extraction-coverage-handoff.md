# Handoff Prompt — CrawlerAI Source-Backed Extraction Coverage (PR 2)

Paste the block below as the first message in a new chat.

---

Implement `docs/plans/crawlerai-extraction-coverage-plan.md` (PR 2). Read that plan first — it carries the baseline, the slice order, the approaches already measured and rejected, and the review findings inherited from PR 1.

**Start state**

- PR 1 (`codex/crawlerai-data-accuracy`) is merged. Branch from updated `main` as `codex/crawlerai-extraction-coverage`.
- Its evidence is in `docs/audits/crawlerai-data-accuracy-report.md`. Read the sections "Correction: Variant Assertions Were Never Being Checked" and "Review Findings Addressed" before touching the harness.
- Fresh live captures are in `backend/artifacts/runs/3` (82 captures, git-ignored). External analysis: `docs/audits/crawlerai_run3_comparison.md` and `docs/audits/crawlerai_defects_run3.json`.

**Baseline to reproduce before changing anything**

```python
from harness.artifact_quality_cases import (
    load_artifact_quality_cases, audit_artifact_quality_cases,
)
refs = load_artifact_quality_cases("app/evaluation/reference")
res = audit_artifact_quality_cases(refs, backend_root=".", partitions=None)
```

Expect **288 failing assertions across 72 cases**, of which **83 are `variants`**. Do not start until you reproduce that number — if it differs, find out why first.

**Objective**

Work the slices in order. Slice 1 (DOM selected state) and Slice 2 (variant/option completeness) hold the large majority of the remaining failures.

**Method that produced PR 1's results — follow it**

1. Measure candidate sources against the failing cases **before** writing code. Record correct/wrong counts.
2. Prefer a rejected approach with numbers over an untested plausible one. Two obvious-looking rules were rejected on measurement in PR 1 and are tabulated in the plan — do not retry them blind.
3. After each slice: full replay, diff the failure set against the previous run, and confirm **zero regressions** before moving on.
4. Accuracy wins over coverage. A missing value is acceptable; a wrong price, stock state, or sibling product is not.

**Constraints**

- No site-specific branches, retailer aliases, or casing tables in generic extraction code.
- No acquisition/browser/traversal changes and no option clicking. Absent source artifacts stay capture-limited.
- Extraction-package LOC and complexity budgets in `backend/app/core/config/extraction_semantic_surface.toml` are **downward ratchets and currently saturated**. Prefer extracting a module over growing one; document any budget change in `tests/unit/test_extraction_architecture.py` the way the existing exceptions are documented.
- Every published value must come from an authorized projection with lineage. A post-serialization alias trips `PUBLIC_RESOLUTION_DIVERGENCE` and suppresses the whole record — PR 1 hit this; do not repeat it.
- Amazon case 55 returning no product is **correct** behaviour for an anti-automation shell, not a defect.

**Inherited review findings**

The plan has an "Inherited Review Findings" table of eight items raised on PR 1 and deliberately deferred — pipe-rule title stripping, selected group merging, selected-variant price vs `existing_fact_keys`, DOM `parse_money` locale, JSON-LD selected-variant identity, the `colorproductcode` axis, the harness `asin`/`style_id` fallbacks, and case 79's reference inconsistency. Each concerns code predating PR 1 and arrived without a reproduction. **Confirm each with a failing case before changing offer or variant selection semantics.**

**Gates**

`.\scripts\check.ps1` and `.\scripts\test.ps1` must pass. `git diff --check` clean. Update `docs/audits/crawlerai-extraction-coverage-report.md` after every major slice, including the approaches you measured and rejected.

**Ask me before**: changing the public field type contract (the `rating`/`review_count` string-vs-numeric decision in Slice 6), re-capturing the price-drift cases, or anything that would widen acquisition scope.
