FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir .

COPY . .

# --- API server ---
FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# --- Celery worker ---
FROM base AS worker
CMD ["celery", "-A", "src.workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]

# --- Celery beat ---
FROM base AS beat
CMD ["celery", "-A", "src.workers.celery_app", "beat", "--loglevel=info"]
