# CrawlerAI Core
- Deterministic crawl, extraction, review, export system.
- Top-level modules: `frontend/` React UI; `backend/` FastAPI services.
- Read frontend architecture at `mem:frontend/core` for frontend ownership.
- Read stack/tooling at `mem:tech_stack`; commands at `mem:suggested_commands`; completion gates at `mem:task_completion`; conventions at `mem:conventions`.
- Project invariants live in `docs/INVARIANTS.md`; code ownership in `docs/CODEBASE_MAP.md`; user-visible behavior in `docs/BUSINESS_LOGIC.md`.
- Fix defects at owning upstream subsystem; do not compensate downstream.
- Grep/search before adding; prefer consolidation over new abstractions.