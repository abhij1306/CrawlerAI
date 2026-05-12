# Architecture Selection: variant-extraction-refactor

## Recommended Architecture: Inline Enhancement (Extend Existing Pipeline)

### Rationale
Lowest cross-cutting concern overhead (all changes stay within existing module boundaries), zero new files (respects "delete before adding" invariant), and directly fixes bugs at their source. The trade-off is that pipeline ordering remains implicit rather than structurally enforced.

### Components
| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| shared_variant_logic | axis inference, size/color patterns | Value-based axis inference, axis name resolution, semantic classification |
| variant_record_normalization | variant cluster, row state | Normalization orchestration: axis remap → dedup → quality gate |
| variant_structural_pruning | variant cluster | Subset elimination, cross-product dedup, low-signal row pruning |
| config/variant_policy | axis policy constants | PUBLIC_VARIANT_AXIS_FIELDS, CANONICAL_MAPPING, allowed axes |

### Information Flow
| From \ To | shared_variant_logic | variant_record_normalization | variant_structural_pruning | config/variant_policy |
|-----------|---------------------|------------------------------|---------------------------|----------------------|
| shared_variant_logic | - | called by | called by | reads |
| variant_record_normalization | calls | - | calls | reads |
| variant_structural_pruning | calls | called by | - | reads |
| config/variant_policy | read by | read by | read by | - |

### Requirement Allocation
| Requirement | Component(s) |
|-------------|--------------|
| REQ-1 (Axis Name Resolution) | shared_variant_logic, variant_record_normalization |
| REQ-2 (Duplicate Elimination) | variant_structural_pruning, variant_record_normalization |
| REQ-3 (Minimum Row Quality) | variant_record_normalization |
| REQ-4 (Value-Based Inference) | shared_variant_logic |
| REQ-5 (Pipeline Ordering) | variant_record_normalization |

### Key Design-Induced Invariants
- Axis remapping must be called before `_dedupe_variant_rows` within `normalize_variant_record`
- `infer_variant_group_name_from_values` must handle compound size tokens before returning ""
- The `state` axis must be treated as a generic/non-semantic axis eligible for value-based remap

### Alternatives Considered
| Candidate | Strength | Weakness | Why Not Selected |
|-----------|----------|----------|-----------------|
| Quality Gate Module | Clean separation of transform vs validate | Adds a new file for logic that fits in existing normalization | Violates "add architecture only when it improves generic coverage" |
| Pipeline Stages | Explicit ordering, pure functions, max testability | 5+ new files, over-engineered for the scope | Violates "delete before adding", adds architecture for one class of bugs |

### Metrics Summary
| Metric | Selected (Inline) | Alt A (Quality Gate) | Alt B (Pipeline Stages) |
|--------|-------------------|---------------------|------------------------|
| Cross-cutting reqs % | 40% | 20% | 20% |
| Cross-cutting invariants % | 17% | 17% | 0% |
| Flow density | 0.50 | 0.50 | 0.21 |
| God object score | 45% | 30% | 15% |
| Sync cycles | 0 | 0 | 0 |
| Max fan-in | 3 | 4 | 6 |
| Max fan-out | 3 | 3 | 5 |
| Evolvability cost | 1.5 | 1.2 | 1.0 |
