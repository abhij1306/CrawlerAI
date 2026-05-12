---
name: "code-architecture-review"
displayName: "Code Architecture Review"
description: "Reusable code review and architecture quality power. Covers SOLID, DRY, KISS, YAGNI, dead code detection, duplicate detection with jscpd, architecture smells, and incremental refactoring recipes."
keywords: ["code-review", "architecture", "solid", "dry", "kiss", "yagni", "refactoring", "anti-patterns", "dead-code", "jscpd", "duplicate-code"]
author: "CrawlerAI Team"
---

# Code Architecture Review

## Overview

A portable engineering quality power for any codebase. Use it during code review, refactoring, or architecture audits to detect violations of core software engineering principles and fix them incrementally.

Covers:
- SOLID, DRY, KISS, YAGNI principles with violation detection
- Module depth analysis — finding shallow modules that add indirection without leverage
- Dead code and duplicate code detection (including jscpd tooling)
- Architecture smells and structural anti-patterns
- Incremental refactoring recipes — how to fix what you find without rewriting the world

## Available Steering Files

- **review-checklist** — Step-by-step code review and architecture audit workflow
- **refactoring-recipes** — Incremental refactoring patterns: extract, inline, move, consolidate, deepen

Read these on-demand based on the task at hand.

## Onboarding

### Prerequisites

For duplicate code detection with jscpd:

```bash
npm install -g jscpd
```

Or run without installing:

```bash
npx jscpd /path/to/source
```

No other tooling required. The principles and checklists work with any language or framework.

### jscpd Configuration

Create `.jscpd.json` in your project root:

```json
{
  "threshold": 5,
  "reporters": ["console", "json"],
  "ignore": [
    "**/node_modules/**",
    "**/.git/**",
    "**/.venv/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/*.min.js"
  ],
  "minLines": 5,
  "minTokens": 50,
  "output": "./reports/jscpd"
}
```

Key options:
- `threshold` — max allowed duplication percentage (CI fails above this)
- `minLines` — minimum lines to count as a clone (default 5)
- `minTokens` — minimum tokens to count as a clone (default 50)
- `--pattern` — glob pattern to scope detection (e.g. `"src/**/*.py"`)

### Quick Scan Commands

```bash
# Scan entire backend
npx jscpd backend/app --min-lines 5 --reporters console

# Scan frontend
npx jscpd frontend/src --min-lines 5 --reporters console

# Scan with HTML report
npx jscpd . --reporters html --output ./reports/jscpd

# Scan specific language
npx jscpd --pattern "**/*.py" backend/

# Scan with threshold (CI mode — exits non-zero if exceeded)
npx jscpd . --threshold 5
```

---

## Architecture Language

Use these terms consistently when discussing architecture. Consistent vocabulary prevents miscommunication.

| Term | Definition |
|------|-----------|
| **Module** | Anything with an interface and an implementation — function, class, package, or slice. Scale-agnostic. |
| **Interface** | Everything a caller must know to use the module: types, invariants, error modes, ordering, config. Not just the type signature. |
| **Depth** | Leverage at the interface — a lot of behavior behind a small interface. **Deep** = high leverage. **Shallow** = interface nearly as complex as the implementation. |
| **Seam** | Where an interface lives; a place behavior can be altered without editing in place. |
| **Adapter** | A concrete thing satisfying an interface at a seam. |
| **Leverage** | What callers get from depth — more capability per unit of interface they learn. |
| **Locality** | What maintainers get from depth — change, bugs, and knowledge concentrate in one place. |

### Key Tests

- **Deletion test:** Imagine deleting the module. If complexity vanishes, it was a pass-through (shallow). If complexity reappears across N callers, it was earning its keep (deep).
- **Interface = test surface:** Callers and tests cross the same seam. If you need to test past the interface, the module is the wrong shape.
- **One adapter = hypothetical seam. Two adapters = real seam.** Don't introduce a seam unless something actually varies across it.

---

## Core Principles

### SOLID

| Principle | Violation Signal | What To Do |
|-----------|-----------------|------------|
| **S** — Single Responsibility | File does 3+ unrelated things. Class has methods that don't share state. | Extract into focused modules. One file = one paragraph summary. |
| **O** — Open/Closed | Every new feature requires editing the same switch/if-chain. | Use strategy pattern, registry, or config-driven dispatch. |
| **L** — Liskov Substitution | Subclass overrides parent method with incompatible behavior or raises unexpected errors. | Ensure subtypes honor the parent contract. Prefer composition over inheritance if contracts diverge. |
| **I** — Interface Segregation | Callers import a module but use <20% of its exports. | Split into focused interfaces/modules. Callers depend only on what they use. |
| **D** — Dependency Inversion | High-level module imports low-level implementation details directly. | Depend on abstractions (protocols, interfaces, config). Inject dependencies. |

### DRY — Don't Repeat Yourself

**When to deduplicate:**
- Same business rule expressed in 2+ places
- Same transformation logic copy-pasted across files
- Same validation with identical conditions

**When duplication is acceptable:**
- Two blocks look similar but serve different business rules that may diverge
- Test setup code that's clearer when explicit per test
- Premature abstraction would couple unrelated concerns

**Detection:** Run `npx jscpd --pattern "**/*.py" .` or `npx jscpd --pattern "**/*.ts" .`

### KISS — Keep It Simple

**Complexity smells:**
- More than 3 levels of nesting in a function
- Function longer than 40 lines
- More than 5 parameters
- Abstraction layers that only have one implementation (shallow module)
- Generic framework built for one use case
- Indirection that requires 3+ file hops to trace a call

**Fix:** Inline the abstraction. Flatten the nesting. Split the function.

### YAGNI — You Aren't Gonna Need It

**Red flags:**
- Plugin systems with one plugin
- Event buses with one subscriber
- Abstract factory for one concrete type
- Configuration for behavior nobody requested
- "Future-proofing" layers that add indirection now for hypothetical later
- Seams with only one adapter and no realistic second adapter

**Fix:** Delete the speculative code. Build it when you actually need it.

---

## Module Depth Analysis

The most common architecture problem isn't missing abstractions — it's **shallow modules** that add indirection without hiding complexity.

### Shallow Module Signals

- Interface is nearly as complex as the implementation
- Callers must understand the internals to use it correctly
- Wrapper/manager/handler that just delegates to another module
- "Helper" that moves code out of sight but doesn't simplify the caller's life
- Fails the deletion test: deleting it would not spread complexity to callers

### Deep Module Signals

- Small interface hides significant complexity
- Callers don't need to know how it works internally
- Passes the deletion test: removing it would force N callers to reimplement the logic
- Change concentrates inside the module (locality), not across callers

### Deepening Workflow

When you find shallow modules causing friction:

1. **Explore** — Walk the area organically. Note where understanding one concept requires bouncing between many small modules. Where are pure functions extracted "for testability" but the real bugs hide in how they're called?

2. **Present candidates** — For each deepening opportunity, state:
   - **Files** — which modules are involved
   - **Problem** — why the current shape causes friction (in terms of depth/leverage/locality)
   - **Solution** — what the deepened module would look like
   - **Benefits** — how tests and maintainability improve

3. **Classify dependencies** before deepening:
   - **In-process** (pure computation) → merge freely, test directly
   - **Local-substitutable** (has test stand-in like SQLite/PGLite) → deepen with internal seam
   - **Remote but owned** (your own services) → define port, inject adapter
   - **True external** (third-party APIs) → inject as mock adapter

4. **Refactor incrementally** — see the refactoring-recipes steering file

---

## Dead Code Detection

### Patterns to Look For

1. **Unused exports** — functions/classes exported but never imported elsewhere
2. **Unreachable branches** — `if False`, `if 0`, conditions that can never be true
3. **Orphan files** — modules not imported by any other module
4. **Commented-out code** — code in comments "just in case"
5. **Compat shims** — re-exports or wrappers left after a migration
6. **Feature flags for shipped features** — conditionals for features that are always on
7. **Unused parameters** — function params that are never read in the body
8. **Dead exception handlers** — catch blocks for exceptions that can't be raised

### Detection Commands

```bash
# Python — find unused imports
python -m pyflakes backend/app/

# Python — find unused code (more aggressive)
pip install vulture
vulture backend/app/ --min-confidence 80

# TypeScript/JavaScript — find unused exports
npx ts-prune

# General — find files not imported anywhere
grep -rL "import.*from" backend/app/services/ | head -20
```

### Decision Framework

| Finding | Action |
|---------|--------|
| Unused export, no tests reference it | Delete |
| Commented-out code | Delete (git has history) |
| Compat shim after completed migration | Delete |
| Unused parameter in public API | Deprecate, then remove in next version |
| Feature flag always true | Remove the conditional, keep the body |

---

## Duplicate Code Detection with jscpd

### How jscpd Works

jscpd uses the Rabin-Karp algorithm to find duplicated token sequences across 150+ languages. It reports clone pairs with file locations, line ranges, and duplication percentage.

### Interpreting Results

```
Clone found (javascript):
 - src/services/userService.js [10:25]
 - src/services/adminService.js [45:60]
```

This means lines 10-25 in userService.js are a clone of lines 45-60 in adminService.js.

### Triage Clones

| Clone Type | Action |
|------------|--------|
| Same business logic in 2 files | Extract to shared deep module |
| Similar but diverging logic | Leave as-is, document why they differ |
| Boilerplate (imports, setup) | Ignore — not worth abstracting |
| Test fixtures | Usually acceptable duplication |
| Config/constants repeated | Consolidate into single config source |

### CI Integration

```yaml
# GitHub Actions example
- name: Check code duplication
  run: npx jscpd . --threshold 5 --min-lines 5 --reporters console
```

Threshold of 5% is a reasonable starting point. Tighten as codebase improves.

---

## Architecture Smells

### Structural Smells

| Smell | Signal | Fix |
|-------|--------|-----|
| **God Class/Module** | File >500 LOC doing multiple unrelated things | Split by responsibility |
| **Shallow Module** | Interface nearly as complex as implementation; fails deletion test | Inline or deepen by merging with related modules |
| **Feature Envy** | Method uses more data from another class than its own | Move method to the module it envies |
| **Shotgun Surgery** | One change requires edits in 5+ files | Consolidate related logic into one deep module |
| **Divergent Change** | One file changes for multiple unrelated reasons | Split into focused modules |
| **Middle Man** | Class that only delegates to another class | Inline — it's a shallow pass-through |
| **Speculative Generality** | Abstract class with one subclass, interface with one impl | Inline until you need the abstraction (one adapter = hypothetical seam) |

### Dependency Smells

| Smell | Signal | Fix |
|-------|--------|-----|
| **Circular Dependencies** | A imports B, B imports A | Extract shared concern into C |
| **Deep Import Chains** | A → B → C → D → E to trace one behavior | Flatten or introduce a facade |
| **Cross-layer Reach** | UI code imports database internals | Add proper seam between layers |
| **Config Sprawl** | Same constant defined in 3 places | Single source of truth |
| **Private Reach-in** | Importing `_private_helper` from another module | Promote to public API or keep internal |
| **Leaky Seam** | Callers must understand internals to use the interface correctly | Redesign the interface to hide the complexity |

### Naming Smells

| Smell | Signal | Fix |
|-------|--------|-----|
| **Generic names** | `utils.py`, `helpers.js`, `misc.ts`, `common.py` | Name by responsibility |
| **Numbered suffixes** | `handler2.py`, `service_new.py`, `v2.ts` | Rename to describe the difference |
| **Misleading names** | Function name doesn't match what it does | Rename to match behavior |

---

## Review Workflow (Quick Reference)

1. **Scan for duplication** — `npx jscpd --pattern "**/*.{py,ts}" . --min-lines 5`
2. **Check dead code** — `vulture backend/app/` or `npx ts-prune`
3. **Grep before adding** — `grep -r "concept_name" src/` before writing new code
4. **Verify single responsibility** — Can you summarize each changed file in one sentence?
5. **Check module depth** — Apply deletion test to any new abstraction. Is it earning its keep?
6. **Check dependency direction** — Do dependencies point inward (toward core logic)?
7. **Spot YAGNI** — Is there new abstraction without a second use case? One adapter = hypothetical seam.
8. **Confirm config placement** — Are magic numbers and strings in config, not inline?

For the full step-by-step review workflow, read the `review-checklist` steering file.

---

## Best Practices

- **Fix upstream, not downstream.** Bad data should be fixed where it's produced, not patched where it's consumed.
- **One concern, one owner.** Every piece of logic has exactly one canonical home.
- **Delete before adding.** Remove duplication and dead code as part of the change, not as a separate task.
- **Grep before creating.** Always search for existing implementations before writing new code.
- **Refactor incrementally.** Small, verified steps. Never rewrite a working system in one shot.
- **Deepen, don't scatter.** When consolidating, aim for fewer modules with more leverage — not more modules with thinner interfaces.
- **Architecture must stay grep-friendly.** A failure should be traceable to one subsystem in one search session.
- **Generic code stays generic.** Platform-specific behavior goes in adapters or config, not in shared paths.
- **Strong contracts beat clever internals.** Typed boundaries and named objects over positional args and tuple returns.
- **The interface is the test surface.** If you can't test through the public interface, the module is the wrong shape.

---

## Configuration

**No additional configuration required** beyond optional jscpd setup (see Onboarding section).

This power is pure documentation and guidance — it works with any language, framework, or project structure.
