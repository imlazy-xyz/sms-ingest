# Cloud Run image for the SMS Ingest backend.
# This Dockerfile is the single source of truth for the deployed image; the local
# infra/docker-compose.yml is dev/test only and never builds the production image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Install the package and its runtime dependencies from pyproject.toml.
# Copy only what the build and runtime need (no .venv, tests, or caches).
COPY pyproject.toml README.md ./
COPY app ./app
COPY cli ./cli
COPY migrations ./migrations
RUN pip install .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

# Cloud Run injects $PORT (default 8080). Shell form so ${PORT} is expanded;
# `exec` replaces the shell so SIGTERM reaches uvicorn for graceful shutdown.
# Single process per instance: Cloud Run scales by instances, which keeps
# request-based billing and memory predictable on the Supabase Free target.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
