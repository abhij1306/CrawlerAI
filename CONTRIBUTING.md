# Contributing

CrawlerAI changes follow the same rules humans and agents use in this repo.

## Start Here

1. Read `AGENTS.md`.
2. Use `docs/CODEBASE_MAP.md` only when ownership is unclear.
3. Read the canonical doc that matches the subsystem you touch.
4. Grep for existing owners before adding code.

## Coding Standards

Use `docs/agent/coding-standards.md` for naming, refactoring, and review rules.

Keep changes small. Prefer existing owners over new layers. Config belongs in `backend/app/core/config/*`. Fix extraction and acquisition bugs upstream, not in publish or export code.

## Verification

After a meaningful implementation change:

```powershell
.\scripts\check.ps1 -Scope Backend
# or: .\scripts\check.ps1 -Scope Frontend
```

Before completion or push:

```powershell
.\scripts\check.ps1
```

Then run `.\scripts\test.ps1`. The repository gates cover backend/frontend static, type, format,
architecture, dead-code, dependency, API-contract, LOC, and complexity policy, while the test
selector maps changed code to affected tests. Do not replace the completion gate with hand-picked
commands. Full suites, measured coverage, builds, and full E2E are CI-only.
