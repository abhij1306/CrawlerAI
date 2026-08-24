FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv-tool

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app/backend
COPY --from=uv-tool /uv /uvx /bin/
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/init_db.py backend/bootstrap_admin.py ./

# Resolve only from the committed lock. Browser binaries are downloaded here;
# OS browser libraries are installed separately in the runtime stage.
RUN uv sync --locked --no-dev --extra prod && \
    .venv/bin/python -m patchright install chromium

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/app/backend/.venv/bin:$PATH

WORKDIR /app/backend
COPY --from=build /app/backend /app/backend
COPY --from=build /ms-playwright /ms-playwright

# Patchright owns the browser runtime library list. Compiler headers, curl, uv,
# and package build tooling stay in earlier stages.
RUN .venv/bin/python -m patchright install-deps chromium && \
    apt-get purge -y xvfb && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/backend/artifacts /app/backend/cookie_store && \
    chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8001

CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
