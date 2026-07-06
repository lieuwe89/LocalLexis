#!/usr/bin/env bash
# Roll the LocalLexis hub to the newest v* tag; roll back on failure.
# All host config comes from env vars (defaults = the homelab) so the script
# is testable against a throwaway repo with stub binaries on PATH.
set -euo pipefail

REPO_DIR="${HUB_REPO_DIR:-/home/lieuwe/LocalLexis}"
VENV="${HUB_VENV:-$REPO_DIR/.venv}"
SERVE_UNIT="${HUB_SERVE_UNIT:-locallexis-serve.service}"
WATCH_UNIT="${HUB_WATCH_UNIT:-locallexis-watch.service}"
HEALTH_URL="${HUB_HEALTH_URL:-http://127.0.0.1:8010/health}"
HEALTH_TIMEOUT="${HUB_HEALTH_TIMEOUT:-30}"
MARKER="${HUB_MARKER:-/home/lieuwe/.local/state/locallexis/last-update-failure}"
ASSET_GLOB="${HUB_ASSET_GLOB:-webui-*.tar.gz}"
REPO_SLUG="${HUB_REPO_SLUG:-lieuwe89/LocalLexis}"
PIP_INDEX="${HUB_PIP_INDEX:-https://download.pytorch.org/whl/cpu}"
DRY_RUN=0
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { echo "[hub-update] $*"; logger -t hub-update "$*" 2>/dev/null || true; }
run() { if [ "$DRY_RUN" -eq 1 ]; then log "DRY: $*"; else "$@"; fi; }

# Token for the health check (sourced from service.env on the real box).
TOKEN="${HUB_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "${HUB_ENV_FILE:-/home/lieuwe/.config/speechtotext/service.env}" ]; then
  TOKEN="$(grep -E '^LOCALLEXIS_API_TOKEN=' "${HUB_ENV_FILE:-/home/lieuwe/.config/speechtotext/service.env}" | cut -d= -f2- || true)"
fi

cd "$REPO_DIR"
run git fetch --tags --quiet || true
current="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
latest="$(git tag -l 'v*' | sort -V | tail -1)"

if [ -z "$latest" ]; then log "no v* tags found"; exit 0; fi
if [ "$current" = "$latest" ] && [ "$FORCE" -eq 0 ]; then
  log "already current ($current)"; exit 0
fi
if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY: would update $current -> $latest"; exit 0
fi

# --- update body added in Task 5 ---
log "TODO update body"
