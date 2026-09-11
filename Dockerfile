FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# System deps: build tools for rapidfuzz/Pillow wheels on ARM (removed later via multi-stage not needed — slim + wheels mostly prebuilt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install uv (Astral) for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Deps first (layer cache): copy only manifests
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

# Then the code
COPY src/ ./src/
COPY config/ ./config/
COPY candidate_profile.yaml ./
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/

RUN uv sync --frozen --no-dev

# Runtime dirs (mounted as volumes in production, but exist for local runs)
RUN mkdir -p data downloads

# Daemon runs in foreground; SIGTERM handled by main.py
CMD [".venv/bin/python", "-m", "ai_job_filter.main"]
