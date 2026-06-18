# Contributing

Invoro changes follow the same rules humans and agents use in this repo.

## Start Here

1. Read `AGENTS.md`.
2. Check `docs/plans/ACTIVE.md`.
3. Use `docs/CODEBASE_MAP.md` only when ownership is unclear.
4. Read the canonical doc that matches the subsystem you touch.
5. Grep for existing owners before adding code.

## Coding Standards

Use `docs/agent/coding-standards.md` for naming, refactoring, and review rules.

Keep changes small. Prefer existing owners over new layers. Config belongs in `backend/app/services/config/*`. Fix extraction and acquisition bugs upstream, not in publish or export code.

## Verification

Run the smallest relevant check first. For backend-wide changes:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
```

For frontend changes:

```powershell
cd frontend
npm ci
npm run lint
npm run build
```
