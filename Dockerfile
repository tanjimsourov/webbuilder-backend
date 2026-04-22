# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && python -m venv "${VIRTUAL_ENV}" \
    && "${VIRTUAL_ENV}/bin/pip" install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN "${VIRTUAL_ENV}/bin/pip" install -r requirements.txt


FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    WEB_CONCURRENCY=4 \
    DJANGO_RUN_MIGRATIONS=1 \
    DJANGO_COLLECTSTATIC=1 \
    DJANGO_WAIT_FOR_DB=1 \
    DJANGO_WAIT_FOR_CACHE=1 \
    DJANGO_STARTUP_MAX_WAIT_SECONDS=60 \
    GUNICORN_CMD_ARGS="--bind 0.0.0.0:8000 --workers 4 --threads 2 --worker-class gthread --max-requests 1000 --max-requests-jitter 200 --timeout 60 --graceful-timeout 30 --access-logfile - --error-logfile -"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --home /app appuser \
    && chmod +x /app/scripts/docker-entrypoint.sh \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=5)" || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application"]
