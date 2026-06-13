# Lead Scraper — single-tenant client instance image.
#
# Secrets are NEVER baked in. They are injected at runtime: the entrypoint
# materializes .streamlit/secrets.toml from the base64-encoded SECRETS_TOML_B64
# env var at startup. The image is byte-identical across all clients.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl: container HEALTHCHECK + entrypoint checks. sqlite3: consistent DB
# backups via deploy/backup.sh (.backup). gosu: the entrypoint starts as root
# to fix mounted-volume ownership, then drops to the non-root app user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl sqlite3 gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (respecting .dockerignore — no secrets, no DBs).
COPY . .

# Create the non-root user the app will ultimately run as. The entrypoint runs
# as root only briefly (to materialize secrets and chown the mounted data
# volume), then drops to this user via gosu to run Streamlit.
RUN chmod +x /app/entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

EXPOSE 8501

# Streamlit's health endpoint. start-period gives the server time to boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8501}/_stcore/health" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
