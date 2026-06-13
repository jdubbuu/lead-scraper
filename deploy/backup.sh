#!/usr/bin/env bash
#
# Per-instance backup of a Lead Scraper leads.db (BRIEF D6).
#
# Produces a timestamped, consistent snapshot of the database. Each client's
# saved leads/status/notes are the client's data and are protected
# independently of the code.
#
# Usage:
#   deploy/backup.sh <db-path> [backup-dir]
#
# Examples:
#   deploy/backup.sh /var/data/leads.db /var/backups
#   deploy/backup.sh leads.db                      # -> ./backups/
#
# Intended to be run on a schedule (cron / host scheduled job) against the
# database file on the mounted persistent volume. Copy the resulting file to
# off-instance storage (object storage, etc.) for durability.
set -euo pipefail

DB_PATH="${1:?usage: backup.sh <db-path> [backup-dir]}"
BACKUP_DIR="${2:-backups}"

[[ -f "$DB_PATH" ]] || { echo "FATAL: database not found: ${DB_PATH}" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
base="$(basename "$DB_PATH")"
base="${base%.db}"
dest="${BACKUP_DIR}/${base}_${TS}.db"

# Prefer sqlite3's online .backup for a consistent snapshot even while the app
# is writing; fall back to a plain copy if sqlite3 isn't on the host.
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '${dest}'"
else
    cp "$DB_PATH" "$dest"
fi

echo "$dest"
