from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_compose_uses_venv_processes_and_solo_worker() -> None:
    compose = _text("docker-compose.yml")

    assert "apt-get upgrade" not in _text("backend/Dockerfile")
    assert '[".venv/bin/python", "init_db.py"]' in compose
    assert '[".venv/bin/python", "bootstrap_admin.py"]' in compose
    assert '[".venv/bin/uvicorn", "app.main:app"' in compose
    assert '".venv/bin/celery"' in compose
    assert '"--pool=solo"' in compose
    assert '"--concurrency=1"' in compose
    assert "inspect ping --destination worker@$$HOSTNAME" in compose
    assert "http://127.0.0.1:8001/health/live" in compose
    assert 'BOOTSTRAP_ADMIN_ONCE: "false"' in compose


def test_compose_delegates_database_url_encoding_to_application_config() -> None:
    compose = _text("docker-compose.yml")

    assert 'DATABASE_URL: ""' in compose
    assert "DATABASE_HOST: db" in compose
    assert "postgresql+asyncpg://${" not in compose


def test_production_override_fails_closed_and_does_not_force_local_services() -> None:
    production = _text("docker-compose.production.yml")

    assert "APP_ENV: production" in production
    assert "DATABASE_URL: ${DATABASE_URL:?DATABASE_URL must be set}" in production
    assert "REDIS_URL: ${REDIS_URL:?REDIS_URL must be set}" in production
    assert production.count('BOOTSTRAP_ADMIN_ONCE: "false"') >= 4
    assert 'profiles: ["local-only"]' in production
    assert "depends_on: !reset {}" in production


def test_frontend_image_is_non_root_static_spa_with_security_headers() -> None:
    dockerfile = _text("frontend/Dockerfile")
    nginx = _text("frontend/nginx.conf")
    headers = _text("frontend/security-headers.conf")

    assert "pnpm install --frozen-lockfile --ignore-scripts" in dockerfile
    assert "FROM nginxinc/nginx-unprivileged" in dockerfile
    assert "USER 101" in dockerfile
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "location = /health/live" in nginx
    assert "X-Content-Type-Options" in headers
    assert "Content-Security-Policy" in headers
    assert "frame-ancestors 'none'" in headers
    assert "apk upgrade" not in dockerfile


def test_container_bases_are_digest_pinned_and_backend_runtime_is_hardened() -> None:
    backend = _text("backend/Dockerfile")
    frontend = _text("frontend/Dockerfile")
    backend_from = [line for line in backend.splitlines() if line.startswith("FROM ")]
    frontend_from = [line for line in frontend.splitlines() if line.startswith("FROM ")]

    assert len(backend_from) == 3
    assert len(frontend_from) == 2
    assert all("@sha256:" in line for line in [*backend_from, *frontend_from])
    assert " AS build" in backend
    assert " AS runtime" in backend
    runtime_stage = backend.split(" AS runtime", maxsplit=1)[1]
    assert "build-essential" not in runtime_stage
    assert "libpq-dev" not in runtime_stage
    assert "COPY --from=uv-tool" not in runtime_stage
    assert "COPY backend/ ./" not in backend
    assert "USER appuser" in runtime_stage


@pytest.mark.asyncio
async def test_init_database_applies_pending_migrations(monkeypatch) -> None:
    import init_db

    calls: list[str] = []

    async def _apply() -> None:
        calls.append("migrated")

    monkeypatch.setattr(init_db, "apply_pending_migrations_async", _apply)

    await init_db.init_database()

    assert calls == ["migrated"]
