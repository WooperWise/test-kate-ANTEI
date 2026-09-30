# syntax=docker/dockerfile:1

# --- Stage 1: dependencies (cached layer via uv) ---
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-dev

# --- Stage 2: project code ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY skills ./skills
COPY setting.py harness.yaml main.py ./
COPY config ./config
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
# non-root user
RUN useradd --create-home harness && chown -R harness:harness /app
USER harness
ENTRYPOINT ["python", "main.py"]
