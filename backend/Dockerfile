FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app/backend

# skipcq: DOK-DL3008 - base-image package versions must track Debian security updates.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Pinned uv toolchain; dependencies install from uv.lock only (reproducible).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

COPY backend/ ./

# --locked: fail on lockfile drift instead of re-resolving. --no-dev + the prod
# extra mirrors the previous pip install ".[prod]" (psycopg2 stays prod-only).
RUN uv sync --locked --no-dev --extra prod && \
    .venv/bin/python -m patchright install --with-deps chromium

RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/backend/artifacts /app/backend/cookie_store /ms-playwright && \
    chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8001

# Run from the uv-synced venv; the system site-packages stay untouched.
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
