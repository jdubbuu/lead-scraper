#!/usr/bin/env bash
#
# Container entrypoint. Materializes the Streamlit secrets file at runtime from
# the base64-encoded SECRETS_TOML_B64 env var, then execs Streamlit.
#
# Design (BRIEF D3):
#   - Secrets are injected at runtime, never baked into the image.
#   - The decoded secrets are written with 600 permissions, owned by the app user.
#   - The secret contents are NEVER echoed or logged.
#   - If SECRETS_TOML_B64 is absent or malformed, fail loudly (non-zero exit)
#     rather than starting an unconfigured app.
#   - A freshly-mounted persistent volume is root-owned; this script (running as
#     root) makes the database directory writable, then drops to the non-root
#     app user via gosu to run Streamlit.
set -euo pipefail

APP_USER="appuser"
SECRETS_DIR="/app/.streamlit"
SECRETS_FILE="${SECRETS_DIR}/secrets.toml"

if [[ -z "${SECRETS_TOML_B64:-}" ]]; then
    echo "FATAL: SECRETS_TOML_B64 is not set. Refusing to start without secrets." >&2
    exit 1
fi

mkdir -p "${SECRETS_DIR}"

# Decode straight to the file. Do not print the contents on success or failure.
# `umask 077` ensures the file is created private even before the explicit chmod.
# `tr -d '[:space:]'` strips any whitespace (spaces/newlines) that a copy-paste
# into a host's env-var field may have introduced, so the decode is robust.
( umask 077
  if ! printf '%s' "${SECRETS_TOML_B64}" | tr -d '[:space:]' | base64 -d > "${SECRETS_FILE}" 2>/dev/null; then
      echo "FATAL: SECRETS_TOML_B64 could not be base64-decoded." >&2
      rm -f "${SECRETS_FILE}"
      exit 1
  fi
)

if [[ ! -s "${SECRETS_FILE}" ]]; then
    echo "FATAL: decoded secrets file is empty." >&2
    rm -f "${SECRETS_FILE}"
    exit 1
fi

chown "${APP_USER}:${APP_USER}" "${SECRETS_FILE}"
chmod 600 "${SECRETS_FILE}"

# Make the database directory writable by the non-root app user. On a fresh
# persistent disk (e.g. Render) the mount is root-owned, so the app could not
# otherwise create leads.db there.
DB_PATH="${LEADS_DB_PATH:-/app/leads.db}"
DB_DIR="$(dirname "${DB_PATH}")"
mkdir -p "${DB_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${DB_DIR}"

echo "Secrets materialized at ${SECRETS_FILE} (contents not logged). Starting Streamlit as ${APP_USER}."

exec gosu "${APP_USER}" streamlit run app.py \
    --server.port="${PORT:-8501}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
