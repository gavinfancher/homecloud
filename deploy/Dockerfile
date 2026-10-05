# syntax=docker/dockerfile:1
# Build context is the repo root:
#   docker build -f deploy/Dockerfile .

ARG PYTHON_IMAGE=python:3.12-slim

# --- build: resolve the locked deps into /app/.venv -------------------------
FROM ${PYTHON_IMAGE} AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependencies first, so editing src/ doesn't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself, installed as a regular (non-editable) wheel so the
# package — including provision/roles/**/*.yml — lives in site-packages and
# the runtime image needs no source tree.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- runtime -----------------------------------------------------------------
FROM ${PYTHON_IMAGE}

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app \
    && chown -R app:app /app

COPY --from=build --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health', timeout=4)"]

CMD ["homecloud"]
