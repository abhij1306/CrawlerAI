# Incremental Refactoring Recipes

Safe, step-by-step patterns for improving code structure without rewriting the world.

**Golden rule:** Each step must leave the code in a working, tested state. Never refactor and change behavior in the same commit.

---

## General Refactoring Principles

1. **One thing at a time.** Separate refactoring from feature work.
2. **Tests first.** Ensure tests cover the behavior before changing structure.
3. **Small steps.** Each step is independently verifiable.
4. **Preserve behavior.** Refactoring changes structure, not outcomes.
5. **Commit after each step.** If something breaks, you can revert one step, not the whole thing.
6. **Run tests after every step.** Green bar before moving on.
7. **Deepen, don't scatter.** Aim for fewer modules with more leverage, not more modules with thinner interfaces.

---

## Recipe 1: Extract Function

**When:** A function is too long, does multiple things, or has a block that deserves a name.

**Steps:**

1. Identify the block to extract (look for comments explaining "what this does")
2. Identify all variables the block reads (parameters) and writes (return values)
3. Create a new function with a descriptive name
4. Move the block into the new function
5. Replace the original block with a call to the new function
6. Run tests

**Before:**
```python
def process_order(order):
    # validate order
    if not order.items:
        raise ValueError("Empty order")
    if order.total < 0:
        raise ValueError("Negative total")
    
    # calculate discount
    discount = 0
    if order.customer.is_premium:
        discount = order.total * 0.1
    if order.total > 100:
        discount = max(discount, order.total * 0.05)
    
    # apply and save
    order.total -= discount
    db.save(order)
```

**After:**
```python
def process_order(order):
    validate_order(order)
    discount = calculate_discount(order)
    order.total -= discount
    db.save(order)

def validate_order(order):
    if not order.items:
        raise ValueError("Empty order")
    if order.total < 0:
        raise ValueError("Negative total")

def calculate_discount(order):
    discount = 0
    if order.customer.is_premium:
        discount = order.total * 0.1
    if order.total > 100:
        discount = max(discount, order.total * 0.05)
    return discount
```

**Caution:** Don't over-extract. If the extracted function is only called once and its name just restates the code, you've created a shallow module. Apply the deletion test.

---

## Recipe 2: Consolidate Duplicates

**When:** jscpd or manual review finds the same logic in 2+ places.

**Steps:**

1. Confirm both blocks implement the same business rule (not just similar-looking code)
2. Identify the canonical home for this logic (grep for related code)
3. Write the shared function in the canonical location
4. Replace the first occurrence with a call to the shared function
5. Run tests
6. Replace the second occurrence
7. Run tests
8. Delete any now-dead code

**Decision: Where does the shared code live?**

| Situation | Home |
|-----------|------|
| Both callers are in the same module | Same module, new private function |
| Callers are in different modules, same subsystem | Subsystem's primary file |
| Callers are in different subsystems | Shared utility in the appropriate layer |
| Logic is config/constants | Config system |

**Warning signs you're over-consolidating:**
- The "shared" function needs `if caller == X` branches
- The two blocks will likely diverge in the future
- Consolidation couples two unrelated subsystems

---

## Recipe 3: Inline Unnecessary Abstraction

**When:** A class/function/module exists but only wraps another without adding value. Fails the deletion test — deleting it would not spread complexity.

**Steps:**

1. Apply the deletion test: would removing this module spread complexity to callers, or just remove indirection?
2. If complexity doesn't spread → it's a shallow pass-through. Proceed.
3. Find all callers of the middle-man
4. Replace each caller's reference with a direct call to the underlying implementation
5. Run tests
6. Delete the middle-man
7. Run tests

**Before:**
```python
class OrderManager:
    def __init__(self, repo):
        self.repo = repo
    
    def get_order(self, id):
        return self.repo.get(id)
    
    def save_order(self, order):
        return self.repo.save(order)
```

**After:** Callers use `repo` directly. `OrderManager` deleted.

**When NOT to inline:**
- The wrapper adds validation, logging, or error handling (it's earning its keep)
- The wrapper provides a stable interface over an unstable dependency
- Multiple implementations exist behind the abstraction (real seam)
- Deleting it would spread complexity to callers (passes deletion test)

---

## Recipe 4: Deepen a Shallow Module Cluster

**When:** Multiple small, tightly-coupled modules bounce callers between them without hiding complexity. Understanding one concept requires reading 4+ files.

This is the inverse of "extract" — you're merging shallow modules into one deep module with better leverage and locality.

**Steps:**

1. Identify the cluster: which modules are tightly coupled and always change together?
2. Apply the deletion test to each: which ones are pass-throughs?
3. Classify dependencies of the cluster:
   - **In-process** (pure computation) → merge freely
   - **Local-substitutable** (has test stand-in) → merge, keep internal seam for testing
   - **Remote/external** → define port at the seam, inject adapter
4. Design the deepened module's interface: what's the simplest surface that gives callers full leverage?
5. Merge modules one at a time:
   a. Move functions into the target module
   b. Update callers to use the new interface
   c. Run tests
6. Delete the emptied shallow modules
7. Write new tests at the deepened module's interface
8. Delete old unit tests that tested shallow internals

**Before:**
```
order_validator.py      → validates order fields
order_calculator.py     → computes totals/discounts  
order_persister.py      → saves to DB
order_manager.py        → calls all three in sequence
```
Callers must know about all 4 files. `order_manager` is a shallow pass-through.

**After:**
```
order_service.py        → validates, computes, persists (deep module)
```
One interface. Callers call `order_service.process(order)`. Complexity is hidden.

**Key insight:** The old unit tests on `order_validator` and `order_calculator` become waste. New tests go through `order_service`'s interface — they test behavior, not implementation.

**When NOT to deepen:**
- The modules genuinely serve different callers with different needs
- They change independently (not coupled)
- Merging would create a god module (>500 LOC doing unrelated things)

---

## Recipe 5: Move Function to Owner

**When:** A function lives in module A but mostly operates on data from module B (feature envy).

**Steps:**

1. Identify which module's data the function primarily uses
2. Check that moving it won't create a circular dependency
3. Move the function to the owning module
4. Update all imports
5. Run tests
6. If the old module re-exported it, add a deprecation re-export temporarily
7. Remove the re-export after all callers are updated

**Circular dependency escape hatch:**
If moving creates a cycle, extract the shared concern into a third module that both can import.

---

## Recipe 6: Replace Conditional with Strategy/Registry

**When:** A growing if/elif/switch chain that changes every time a new variant is added.

**Steps:**

1. Identify the dispatch condition (what determines which branch runs)
2. Define an interface/protocol for the behavior
3. Create one implementation per branch
4. Build a registry mapping condition → implementation
5. Replace the if-chain with a registry lookup
6. Run tests
7. Delete the old if-chain

**Before:**
```python
def extract(source_type, data):
    if source_type == "json_ld":
        return extract_json_ld(data)
    elif source_type == "microdata":
        return extract_microdata(data)
    elif source_type == "opengraph":
        return extract_opengraph(data)
```

**After:**
```python
EXTRACTORS = {
    "json_ld": extract_json_ld,
    "microdata": extract_microdata,
    "opengraph": extract_opengraph,
}

def extract(source_type, data):
    extractor = EXTRACTORS.get(source_type)
    if not extractor:
        raise ValueError(f"Unknown source type: {source_type}")
    return extractor(data)
```

**When NOT to use this pattern:**
- Only 2-3 branches that rarely change
- The branches have significantly different signatures
- Adding a registry would be YAGNI for the current scope

---

## Recipe 7: Flatten Deep Nesting

**When:** Function has 4+ levels of indentation making it hard to follow.

**Steps:**

1. Identify guard clauses (early returns for invalid cases)
2. Invert conditions and return early
3. Extract nested blocks into named functions (only if they pass the deletion test)
4. Run tests after each change

**Before:**
```python
def process(item):
    if item is not None:
        if item.is_valid:
            if item.has_data:
                result = transform(item.data)
                if result.success:
                    save(result)
                    return result
                else:
                    log_error(result)
                    return None
            else:
                return None
        else:
            return None
    else:
        return None
```

**After:**
```python
def process(item):
    if item is None:
        return None
    if not item.is_valid:
        return None
    if not item.has_data:
        return None
    
    result = transform(item.data)
    if not result.success:
        log_error(result)
        return None
    
    save(result)
    return result
```

---

## Recipe 8: Extract Config from Code

**When:** Magic numbers, strings, thresholds, or feature flags are inline in service code.

**Steps:**

1. Identify the hardcoded value
2. Determine if it's a tunable (might change per environment) or a constant (fixed by design)
3. For tunables: move to config system (env vars, config files)
4. For constants: move to a named constant in the appropriate config module
5. Replace inline value with reference to config/constant
6. Run tests

**Before:**
```python
def should_retry(response):
    return response.status_code in [429, 503] and self.attempts < 3
```

**After:**
```python
# In config module
MAX_RETRY_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = [429, 503]

# In service
def should_retry(response):
    return (response.status_code in RETRYABLE_STATUS_CODES 
            and self.attempts < MAX_RETRY_ATTEMPTS)
```

---

## Recipe 9: Break Circular Dependency

**When:** Module A imports from B, and B imports from A.

**Steps:**

1. Draw the dependency: what does A need from B? What does B need from A?
2. Identify the shared concept that both modules need
3. Extract that concept into a new module C (or an existing shared module)
4. Update A to import from C instead of B (or vice versa)
5. Run tests
6. Verify no circular import remains

**Common patterns:**
- **Shared types/interfaces** → Extract to a `types` or `protocols` module
- **Shared utility function** → Move to the module that owns that concern
- **Mutual callbacks** → Use dependency injection or events

---

## Recipe 10: Split God Module

**When:** A file is >500 LOC and handles multiple unrelated responsibilities.

**Steps:**

1. List all responsibilities in the file (group functions by what they do)
2. Identify 2-3 coherent groups
3. Create new modules named by responsibility
4. Move one group at a time:
   a. Move functions to new module
   b. Update imports in all callers
   c. Run tests
5. If the original module was a facade, keep it as a thin orchestrator that imports from the new modules
6. Run full test suite

**Naming the new modules:**
- Name by responsibility, not by what was split: `price_extraction.py` not `detail_extractor_part2.py`

**Important:** Don't split into modules so small they become shallow. Each resulting module should pass the deletion test — it should hide meaningful complexity behind its interface.

---

## Recipe 11: Remove Dead Code

**When:** Unused exports, unreachable branches, orphan files, or commented-out code found.

**Steps:**

1. Confirm the code is actually dead:
   - `grep -r "function_name" .` — zero results outside its definition?
   - Check test files too — is it only referenced in tests for itself?
   - Check dynamic usage — could it be called via string lookup, reflection, or config?
2. If confirmed dead:
   a. Delete the code
   b. Delete any tests that only tested the dead code
   c. Run full test suite
3. If uncertain:
   - Add a deprecation warning/log
   - Monitor for a release cycle
   - Then delete

**Special cases:**
- **Commented-out code:** Always delete. Git has history.
- **Compat re-exports:** Delete if migration is complete. Grep for the old import path first.
- **Feature-flagged code where flag is always on:** Remove the conditional, keep the body.

---

## Recipe 12: Promote Private to Public API

**When:** Other modules import `_private_function` from your module (private reach-in smell).

**Steps:**

1. Identify all external callers of the private function
2. Decide: should this be a public API of the owning module?
   - Yes → Rename without underscore, add to module's public interface
   - No → The callers need their own copy, or the logic belongs in a shared module
3. If promoting: rename, update all callers, add docstring
4. If not promoting: move the logic to where callers live, or extract to shared module
5. Run tests

---

## Recipe 13: Consolidate Config Sources

**When:** Same tunable/threshold/constant defined in multiple places.

**Steps:**

1. Grep for the value or concept across the codebase
2. Identify all locations where it's defined
3. Choose the canonical home (usually the config system)
4. Move the definition to the canonical home
5. Update all other locations to import from the canonical source
6. Delete the duplicate definitions
7. Run tests

---

## Recipe 14: Introduce a Seam for Testability

**When:** A module has a hard dependency on I/O, external service, or infrastructure that makes it untestable through its interface.

**Steps:**

1. Identify the dependency that blocks testing
2. Classify it:
   - **Local-substitutable** (e.g., Postgres → PGLite, filesystem → in-memory) → Use the stand-in directly in tests. Internal seam only.
   - **Remote but owned** (your own service) → Define a port (interface), inject adapter
   - **True external** (third-party API) → Define a port, mock adapter for tests
3. Extract the dependency behind a port (interface/protocol)
4. Create the production adapter
5. Create the test adapter (in-memory, mock, or stand-in)
6. Inject the adapter into the module
7. Rewrite tests to use the test adapter through the module's public interface
8. Delete old tests that tested past the interface

**Key discipline:**
- One adapter = hypothetical seam. Only introduce if testing genuinely requires it.
- Two adapters (prod + test) = real seam. Justified.
- Don't expose internal seams through the module's external interface.

**Testing after deepening:**
- Old unit tests on shallow internals → delete
- New tests at the deepened module's interface → keep
- Tests should survive internal refactors without changing assertions

---

## Anti-Patterns in Refactoring

### Don't Do These

| Anti-Pattern | Why It's Bad |
|--------------|--------------|
| **Big bang rewrite** | High risk, hard to verify, blocks other work |
| **Refactor + feature in same PR** | Can't tell if a bug is from refactoring or new behavior |
| **Refactor without tests** | No safety net to verify behavior is preserved |
| **Premature abstraction** | Creating interfaces/patterns before the second use case exists |
| **Rename everything at once** | Hard to review, easy to miss a reference |
| **Move files without updating docs** | Creates stale references that mislead future work |
| **Scatter into many shallow modules** | More files ≠ better architecture. Aim for depth. |
| **Extract for testability alone** | If the real bugs hide in how functions are called, extracting them doesn't help |

### Refactoring Smells (You're Doing It Wrong If...)

- The refactoring PR is >500 lines changed
- You're adding new dependencies to "improve" structure
- The refactoring requires changing test assertions (behavior changed)
- You need to explain the new structure with a diagram (too complex)
- The refactoring makes the code harder to grep
- You created more modules but each one is shallower than before

---

## Prioritization: What to Refactor First

| Priority | Target | Reason |
|----------|--------|--------|
| 1 | Code you're about to modify for a feature | Refactoring makes the feature easier |
| 2 | Shallow module clusters causing shotgun surgery | Deepening reduces change spread |
| 3 | High-duplication areas (jscpd hotspots) | Reduces maintenance burden |
| 4 | God modules blocking team velocity | Multiple people editing same file |
| 5 | Dead code accumulation | Reduces cognitive load |
| 6 | Naming/organization issues | Improves discoverability |

**Never refactor:**
- Code that works, isn't changing, and isn't blocking anyone
- Code you don't understand yet (read first, refactor later)
- Code during an incident or urgent fix
