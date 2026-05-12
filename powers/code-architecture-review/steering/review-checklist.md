# Code Review & Architecture Audit Checklist

Step-by-step workflow for reviewing code changes or auditing architecture quality.

---

## Pre-Review: Context Gathering

Before reviewing, establish context:

1. **Identify the change scope** — What files were modified? What's the intent?
2. **Identify the owning subsystem** — Which module/service owns this behavior?
3. **Check for existing patterns** — How does the rest of the codebase handle similar concerns?

---

## Phase 1: Duplication & Dead Code Scan

### 1.1 Run jscpd on Changed Files

```bash
# Scan the specific directories that changed
npx jscpd path/to/changed/directory --min-lines 5 --reporters console

# Or scan the full project for baseline
npx jscpd . --threshold 5 --reporters console --ignore "**/node_modules/**,**/.venv/**,**/dist/**"
```

**Questions to answer:**
- Did this change introduce new duplication?
- Does the new code duplicate existing logic elsewhere?
- Are there clones that should be consolidated?

### 1.2 Check for Dead Code

```bash
# Python
vulture path/to/changed/files --min-confidence 80

# TypeScript
npx ts-prune | grep -i "unused"
```

**Questions to answer:**
- Did this change orphan any existing code?
- Are there unused imports or exports?
- Were old compat shims left behind?

---

## Phase 2: Principle Violations

### 2.1 Single Responsibility Check

For each changed file, ask:
- [ ] Can I summarize this file's job in one sentence?
- [ ] Does every function in this file relate to that one job?
- [ ] If I added a new feature, would I need to touch this file for unrelated reasons?

**Violation:** File does multiple unrelated things → Split by responsibility.

### 2.2 DRY Check

- [ ] Does the new code duplicate logic that exists elsewhere?
- [ ] Run: `grep -r "key_function_or_concept" src/` — does similar code already exist?
- [ ] If consolidating, is the duplication genuinely the same rule (not just similar-looking code)?

**Violation:** Same business rule in 2+ places → Extract to shared location.
**False positive:** Similar-looking code that serves different business rules → Leave separate.

### 2.3 KISS Check

- [ ] Are there more than 3 levels of nesting?
- [ ] Are functions longer than 40 lines?
- [ ] Are there more than 5 parameters?
- [ ] Is there a new abstraction layer with only one implementation?
- [ ] Does tracing a call require hopping through 3+ files?

**Violation:** Unnecessary complexity → Inline, flatten, or split.

### 2.4 YAGNI Check

- [ ] Is there new code that isn't required by the current task?
- [ ] Plugin system with one plugin?
- [ ] Configuration for behavior nobody requested?
- [ ] Abstract base class with one concrete subclass?
- [ ] "Future-proofing" that adds indirection now?
- [ ] Seam with only one adapter and no realistic second?

**Violation:** Speculative code → Delete it. Build when needed.

### 2.5 Open/Closed Check

- [ ] Does adding a new variant require editing a switch/if-chain?
- [ ] Could this be handled by config, registry, or strategy pattern instead?

### 2.6 Dependency Inversion Check

- [ ] Does high-level code import low-level implementation details?
- [ ] Are there circular imports?
- [ ] Does the change introduce a new cross-layer dependency?

---

## Phase 3: Module Depth Analysis

### 3.1 Deletion Test

For each new module, class, or abstraction introduced:

- [ ] **Imagine deleting it.** Does complexity vanish (it was a pass-through) or reappear across N callers (it was earning its keep)?
- [ ] If complexity vanishes → the module is shallow. Consider inlining.
- [ ] If complexity spreads to callers → the module is deep. It belongs.

### 3.2 Shallow Module Detection

- [ ] Is the interface nearly as complex as the implementation?
- [ ] Must callers understand internals to use it correctly? (leaky seam)
- [ ] Is it a wrapper/manager/handler that just delegates?
- [ ] Were pure functions extracted "for testability" but the real bugs hide in how they're called?

**Violation:** Shallow module adding indirection without leverage → Inline or deepen.

### 3.3 Seam Discipline

- [ ] Does any new interface/abstraction have only one implementation?
- [ ] One adapter = hypothetical seam. Is there a realistic second adapter?
- [ ] Are internal seams being exposed through the external interface?

**Violation:** Premature seam → Remove until a second adapter is justified.

### 3.4 Depth Opportunities

- [ ] Are there clusters of tightly-coupled small modules that could be merged into one deep module?
- [ ] Would merging improve locality (bugs/changes concentrate in one place)?
- [ ] Would merging improve leverage (callers get more from a simpler interface)?

---

## Phase 4: Architecture Smells

### 4.1 Structural Review

- [ ] **God class?** — Any file >500 LOC doing multiple things?
- [ ] **Feature envy?** — Method reaching into another module's data more than its own?
- [ ] **Shotgun surgery?** — Would a single logical change require touching 5+ files?
- [ ] **Middle man?** — New class that only delegates without adding value?
- [ ] **Divergent change?** — One file changing for multiple unrelated reasons?

### 4.2 Dependency Review

- [ ] **Circular dependencies?** — A imports B, B imports A?
- [ ] **Private reach-in?** — Importing `_underscore_prefixed` names from another module?
- [ ] **Config sprawl?** — New constants/config defined inline instead of in the config system?
- [ ] **Cross-module coupling?** — Does the change make two modules harder to change independently?
- [ ] **Leaky seam?** — Must callers know implementation details to use the interface?

### 4.3 Naming Review

- [ ] Are new files/functions named by responsibility (not `utils`, `helpers`, `misc`)?
- [ ] Do function names describe what they do, not how they do it?
- [ ] Are there numbered suffixes (`v2`, `_new`, `2`) that should be proper names?

---

## Phase 5: Config & Constants

- [ ] Are magic numbers and strings in config, not inline in service code?
- [ ] Is there a single source of truth for each tunable value?
- [ ] Are environment-controlled settings going through the config system (not hardcoded)?
- [ ] No parallel config sources for the same runtime rule?

---

## Phase 6: Testing Impact

- [ ] Do existing tests still pass?
- [ ] Does the change need new tests for new behavior?
- [ ] Are tests testing through the module's interface (not past it)?
- [ ] No tests importing private/underscore-prefixed internals?
- [ ] No mocks that just restate the implementation?
- [ ] Would tests survive an internal refactor without changing assertions?

---

## Phase 7: Final Checks

- [ ] **Grep before adding** — Was existing code searched before writing new functions?
- [ ] **Fix upstream** — If there's a data quality issue, is it fixed at the source?
- [ ] **Delete before adding** — Was dead code, duplication, or compat shims removed?
- [ ] **Docs updated** — If behavior or ownership changed, are docs current?
- [ ] **One obvious home** — Does every new piece of code have a clear owning module?
- [ ] **Depth check** — Do new abstractions pass the deletion test?

---

## Severity Classification

| Severity | Criteria | Action |
|----------|----------|--------|
| **Blocker** | Violates core contract, breaks existing behavior, introduces security issue | Must fix before merge |
| **Major** | SOLID violation, shallow module adding friction, significant duplication, architecture smell | Should fix before merge |
| **Minor** | Naming issue, minor style inconsistency, small dead code | Fix in follow-up or same PR |
| **Suggestion** | Could be better but works fine as-is | Author's discretion |

---

## Review Output Template

```markdown
## Review Summary

**Scope:** [files/modules reviewed]
**Duplication:** [jscpd result — X% duplication, Y clones found]
**Dead code:** [any orphaned code found]
**Depth issues:** [shallow modules or premature seams identified]

### Blockers
- [ ] [description + file:line]

### Major Issues
- [ ] [description + file:line + principle violated]

### Minor Issues
- [ ] [description + file:line]

### Deepening Opportunities
- [module cluster that could be merged for better leverage/locality]

### Suggestions
- [description]

### What's Good
- [positive observations — deep modules, clean seams, good locality]
```
