# Task Completion
Frontend changes are complete only after the smallest relevant checks pass, then broader gates for shared behavior:
- `cd frontend && npm run typecheck`
- `cd frontend && npm run lint`
- `cd frontend && npm test`
- `cd frontend && npm run build`
- Run targeted Vitest files first for local changes; run Playwright when user-visible flows or routing change.
- Run `npm run format:check` before finalizing broad refactors.
- Review Git diff for unintended generated files, line-ending churn, or unrelated edits.