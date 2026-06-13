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

mkdir -p "${SECRETS_DIR}"

# Acquire the Streamlit secrets file from the first available source:
#   1. SECRETS_TOML_B64 env var  -> base64 of the secrets file (portable; works
#      on any host). Whitespace from a copy-paste is stripped before decoding.
#   2. A host-mounted raw secret file at /etc/secrets/secrets.toml (e.g. Render
#      "Secret Files") -> plain TOML, no base64, nothing to decode.
#   3. A secrets file already present at ${SECRETS_FILE}.
if [[ -n "${SECRETS_TOML_B64:-}" ]]; then
    ( umask 077
      if ! printf '%s' "${SECRETS_TOML_B64}" | tr -d '[:space:]' | base64 -d > "${SECRETS_FILE}" 2>/dev/null; then
          echo "FATAL: SECRETS_TOML_B64 is set but could not be base64-decoded." >&2
          rm -f "${SECRETS_FILE}"
          exit 1
      fi
    )
    echo "Secrets source: SECRETS_TOML_B64 env var."
elif [[ -s /etc/secrets/secrets.toml ]]; then
    ( umask 077; cp /etc/secrets/secrets.toml "${SECRETS_FILE}" )
    echo "Secrets source: mounted secret file /etc/secrets/secrets.toml."
elif [[ -s "${SECRETS_FILE}" ]]; then
    echo "Secrets source: existing ${SECRETS_FILE}."
else
    echo "FATAL: no secrets provided. Set SECRETS_TOML_B64, or mount a secret file at /etc/secrets/secrets.toml." >&2
    exit 1
fi

if [[ ! -s "${SECRETS_FILE}" ]]; then
    echo "FATAL: secrets file is empty after setup." >&2
    rm -f "${SECRETS_FILE}"
    exit 1
fi

chown "${APP_USER}:${APP_USER}" "${SECRETS_FILE}"
chmod 600 "${SECRETS_FILE}"
echo "Secrets ready at ${SECRETS_FILE} ($(wc -c < "${SECRETS_FILE}") bytes; contents not logged)."

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
