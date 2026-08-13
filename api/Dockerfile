# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT="--system"

# libpq-dev is needed by asyncpg at build time; libpq5 at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libpq5 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.8.12

WORKDIR /app

# --- dependency layer: cache uv sync ---
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# --- application layer ---
COPY app ./app
COPY README.md ./README.md
# Ship the config template as a reference; `config.yml` itself is provided
# at runtime via a Railway variable / volume mount / CONFIG_PATH.
COPY config.example.yml ./config.example.yml

# Drop privileges (best-effort; Railway runs as non-root by default).
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser 2>/dev/null || true
USER appuser

EXPOSE 8000

# Honor the platform's $PORT (Railway, Fly, etc.). Falls back to 8000.
ENV PORT=8000

# Apply schema migrations before starting the server. On Railway we also
# run this in the `release` phase via railway.toml, but doing it here means
# plain `docker run` works too.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]