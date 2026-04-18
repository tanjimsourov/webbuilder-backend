# SMC Web Builder Backend - Production Dockerfile
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_CONCURRENCY=4 \
    DJANGO_RUN_MIGRATIONS=1 \
    DJANGO_COLLECTSTATIC=1 \
    GUNICORN_CMD_ARGS="--bind 0.0.0.0:8000 --workers 4 --threads 2 --worker-class gthread --max-requests 1000 --max-requests-jitter 200 --timeout 60 --graceful-timeout 30 --access-logfile - --error-logfile -"

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser && \
    chmod +x /app/scripts/docker-entrypoint.sh && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/', timeout=5)" || exit 1

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

# Production startup command
CMD ["gunicorn", "config.wsgi:application"]
