This is a comment left during a code review.
Path: backend/app/services/acquisition/browser_background_tasks.py
Line: 69-75

Comment:
**Orphaned task when outer coroutine is cancelled**

`asyncio.wait` does not cancel the tasks it watches when *it* is cancelled. If the caller's task receives a `CancelledError` while awaiting line 70, the exception propagates immediately and `task` has been neither registered in `_eviction_cleanup_tasks` nor awaited. The background close coroutine keeps running but is untracked, producing "Task was destroyed but it is pending!" warnings and preventing the clean-drain contract from holding during shutdown. Fix by registering the task before the first `await`, or adding an `except BaseException` guard that registers it when propagating cancellation.

How can I resolve this? If you propose a fix, please make it concise.
This is a comment left during a code review.
Path: backend/app/services/extract/detail/resolution.py
Line: 29-55

Comment:
**Parent availability computed before negative-stock normalisation; zero-stock OOS path removed**

`variant_parent_availability_value` is called before `_resolve_negative_variant_stock`. Variants with `stock_quantity < 0` have not yet had `availability` set to `AVAILABILITY_OUT_OF_STOCK`, so they contribute `None` to the `values` set instead of `AVAILABILITY_OUT_OF_STOCK`. For products where OOS is only signalled through negative stock (no explicit availability field), the parent's availability is never updated.

Additionally, `_all_variants_have_zero_stock` was removed from `variant_parent_availability_value`. Without it, products where all variants carry `stock_quantity = 0` but no explicit availability marker no longer trigger OOS at the parent level. Fix: move the `variant_parent_availability_value` call to after `_resolve_negative_variant_stock`, and re-add a zero-stock branch.

How can I resolve this? If you propose a fix, please make it concise.
This is a comment left during a code review.
Path: frontend/lib/api/schemas.ts
Line: 73-84

Comment:
**`review_bucket` Zod schema silently drops `evidence_id` and `reason` fields**

The backend's `_review_bucket_from_decisions` emits `{ key, value, source, evidence_id, reason }` per row. The schema here only declares `{ key, value, source }`. Zod's `z.object()` strips undeclared keys by default, so any call through `safeValidate(crawlRecordSchema, ...)` will silently discard `evidence_id` and `reason`. Add the missing fields or call `.passthrough()` on the inner object to preserve them.

How can I resolve this? If you propose a fix, please make it concise.

This is a comment left during a code review.
Path: frontend/lib/api/schemas.ts
Line: 135-141

Comment:
**`safeValidate` throws on failure — name implies a non-throwing variant**

Callers who read the name as analogous to `safeParse` or `safeParseAsync` will expect a result-type (never throws). Since this always throws on failure, renaming it (e.g. `strictValidate`) avoids silent contract mismatches.

```suggestion
export function strictValidate<T>(schema: z.ZodSchema<T>, data: unknown, context: string): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new Error(`API validation failure in ${context}: ${result.error.message}`);
  }
  return result.data;
}
```

How can I resolve this? If you propose a fix, please make it concise.
