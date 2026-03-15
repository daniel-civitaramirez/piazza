# syntax=docker/dockerfile:1

# --- Builder stage ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/injection_patterns.example.json config/injection_patterns.example.json

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "piazza.main:app", "--host", "0.0.0.0", "--port", "8000"]
