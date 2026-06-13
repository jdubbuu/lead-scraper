#!/usr/bin/env bash
#
# Staged rollout for Lead Scraper client instances (BRIEF D5).
#
# Model: tag a release, deploy it to a staging/canary instance you own, verify
# it there, then promote the SAME tag to each client instance ONE AT A TIME.
# Never push-to-all. The prior tag stays deployable for fast rollback.
#
# Render reference implementation. The host-agnostic parts (tag->commit
# resolution, deploy polling, health check, prior-tag tracking, rollback) are
# concrete. The single host-specific step is trigger_deploy() / deploy_status();
# swap those two functions to retarget another host (Railway CLI, ssh+docker on
# a VPS) without touching the rest of the script.
#
# Usage:
#   deploy/rollout.sh deploy   <tag> <instance>
#   deploy/rollout.sh rollback <instance>
#   deploy/rollout.sh status   <instance>
#   deploy/rollout.sh list-instances
#
# Per-instance config: deploy/instances/<instance>.env   (operator-local; see
# deploy/instances/example.env). Contains the instance's service id + URL — NOT
# secrets:
#   RENDER_SERVICE_ID=srv-xxxxxxxxxxxxxxxxxxxx
#   HEALTHCHECK_URL=https://acme-leads.onrender.com
#
# Required in the environment (NEVER commit):
#   RENDER_API_KEY=rnd_xxx   # a Render API key with deploy permission
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_DIR="${ROOT}/deploy/instances"
STATE_DIR="${ROOT}/deploy/state"
HEALTH_PATH="/_stcore/health"
POLL_TIMEOUT="${POLL_TIMEOUT:-600}"     # max seconds to wait for a deploy to go live
POLL_INTERVAL="${POLL_INTERVAL:-10}"

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

load_instance() {
    local instance="$1"
    local cfg="${INSTANCE_DIR}/${instance}.env"
    [[ -f "$cfg" ]] || die "no config for instance '${instance}' (expected ${cfg})"
    # shellcheck disable=SC1090
    source "$cfg"
    [[ -n "${RENDER_SERVICE_ID:-}" ]] || die "RENDER_SERVICE_ID not set in ${cfg}"
    [[ -n "${HEALTHCHECK_URL:-}" ]]   || die "HEALTHCHECK_URL not set in ${cfg}"
}

resolve_commit() {
    # Resolve an annotated or lightweight tag (or any ref) to a commit SHA.
    local ref="$1"
    git -C "$ROOT" rev-list -n 1 "refs/tags/${ref}" 2>/dev/null \
        || git -C "$ROOT" rev-list -n 1 "$ref" 2>/dev/null \
        || die "cannot resolve tag/ref '${ref}' to a commit"
}

# --- host-specific (Render) -------------------------------------------------
_json_field() {
    # Extract the first "<key>":"<value>" string field from JSON without jq.
    local key="$1"
    grep -o "\"${key}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 \
        | sed -E 's/.*"([^"]+)"$/\1/'
}

trigger_deploy() {
    # Trigger a deploy of <commit> and echo the new deploy id.
    local commit="$1"
    [[ -n "${RENDER_API_KEY:-}" ]] || die "RENDER_API_KEY not set in the environment"
    local resp
    resp="$(curl -fsS -X POST \
        "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/deploys" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"commitId\":\"${commit}\"}")" \
        || die "Render deploy request failed"
    echo "$resp" | _json_field id
}

deploy_status() {
    # Echo the status string for a deploy id.
    local deploy_id="$1"
    curl -fsS \
        "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/deploys/${deploy_id}" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        | _json_field status
}
# ---------------------------------------------------------------------------

wait_for_live() {
    local deploy_id="$1" elapsed=0 status
    while (( elapsed < POLL_TIMEOUT )); do
        status="$(deploy_status "$deploy_id" || true)"
        case "$status" in
            live)
                log "deploy ${deploy_id} is live"; return 0 ;;
            build_failed|update_failed|canceled|deactivated|pre_deploy_failed)
                die "deploy ${deploy_id} ended in status '${status}'" ;;
            *)
                log "deploy ${deploy_id} status: ${status:-pending} (${elapsed}s)" ;;
        esac
        sleep "$POLL_INTERVAL"; elapsed=$(( elapsed + POLL_INTERVAL ))
    done
    die "timed out after ${POLL_TIMEOUT}s waiting for deploy ${deploy_id}"
}

health_check() {
    local url="${HEALTHCHECK_URL%/}${HEALTH_PATH}"
    log "health check: ${url}"
    local i
    for i in $(seq 1 12); do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
            log "health check passed"; return 0
        fi
        sleep 5
    done
    die "health check failed: ${url}"
}

record_good() {
    local instance="$1" tag="$2" commit="$3"
    mkdir -p "$STATE_DIR"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ${tag} ${commit}" >> "${STATE_DIR}/${instance}.history"
}

cmd_deploy() {
    local tag="${1:?usage: rollout.sh deploy <tag> <instance>}"
    local instance="${2:?usage: rollout.sh deploy <tag> <instance>}"
    load_instance "$instance"
    local commit; commit="$(resolve_commit "$tag")"
    log "deploying ${tag} (${commit:0:12}) to ${instance} [service ${RENDER_SERVICE_ID}]"
    local deploy_id; deploy_id="$(trigger_deploy "$commit")"
    [[ -n "$deploy_id" ]] || die "could not obtain a deploy id from the host"
    wait_for_live "$deploy_id"
    health_check
    record_good "$instance" "$tag" "$commit"
    log "OK: ${instance} is now running ${tag}"
}

cmd_rollback() {
    local instance="${1:?usage: rollout.sh rollback <instance>}"
    load_instance "$instance"
    local hist="${STATE_DIR}/${instance}.history"
    [[ -f "$hist" ]] || die "no deploy history for ${instance}; nothing to roll back to"
    local count; count="$(wc -l < "$hist")"
    (( count >= 2 )) || die "only one recorded deploy for ${instance}; no prior tag to roll back to"
    local prev; prev="$(tail -n 2 "$hist" | head -n 1)"
    local prev_tag prev_commit
    prev_tag="$(echo "$prev" | awk '{print $2}')"
    prev_commit="$(echo "$prev" | awk '{print $3}')"
    log "rolling ${instance} back to ${prev_tag} (${prev_commit:0:12})"
    local deploy_id; deploy_id="$(trigger_deploy "$prev_commit")"
    [[ -n "$deploy_id" ]] || die "could not obtain a deploy id from the host"
    wait_for_live "$deploy_id"
    health_check
    record_good "$instance" "$prev_tag" "$prev_commit"
    log "OK: ${instance} rolled back to ${prev_tag}"
}

cmd_status() {
    local instance="${1:?usage: rollout.sh status <instance>}"
    load_instance "$instance"
    health_check && log "${instance} is healthy at ${HEALTHCHECK_URL}"
}

cmd_list() {
    if compgen -G "${INSTANCE_DIR}/*.env" >/dev/null; then
        for f in "${INSTANCE_DIR}"/*.env; do
            local name; name="$(basename "$f" .env)"
            [[ "$name" == "example" ]] && continue
            echo "$name"
        done
    else
        echo "(no instances configured)"
    fi
}

main() {
    local sub="${1:-}"; shift || true
    case "$sub" in
        deploy)         cmd_deploy "$@" ;;
        rollback)       cmd_rollback "$@" ;;
        status)         cmd_status "$@" ;;
        list-instances) cmd_list ;;
        *)
            cat >&2 <<EOF
usage:
  $0 deploy   <tag> <instance>
  $0 rollback <instance>
  $0 status   <instance>
  $0 list-instances
EOF
            exit 2 ;;
    esac
}

main "$@"
