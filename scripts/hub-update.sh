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

prev="$current"
log "updating $prev -> $latest"

rollback() {
  local reason="$1"
  log "FAILED ($reason); rolling back to $prev"
  git checkout --quiet "$prev" || true
  fetch_webui "$prev" || log "warn: could not restore webui for $prev"
  # uv is the installer on this box (uv-created venv, no pip). Resolves on PATH
  # via ~/.local/bin (systemd unit / runbook set it), or the stub in tests.
  uv pip install --python "$VENV/bin/python" -e ".[api]" \
     -c requirements-server-cpu.txt --extra-index-url "$PIP_INDEX" --quiet || true
  sudo -- systemctl restart "$SERVE_UNIT" "$WATCH_UNIT" || true
  # Marker write is best-effort: never let it abort rollback under `set -e`
  # (e.g. full disk or permission drift on the state dir) — the service is
  # already restarted onto $prev by this point; losing the marker must not
  # turn a clean rollback into a hard error before the exit-1 signal.
  local now
  now="$(date -Is 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$MARKER")" || true
  echo "$now failed=$latest reason=$reason rolled_back_to=$prev" > "$MARKER" || true
  logger -t hub-update "rollback to $prev after $reason" 2>/dev/null || true
  exit 1
}

fetch_webui() {
  local tag="$1" tmp
  tmp="$(mktemp -d)"
  gh release download "$tag" --repo "$REPO_SLUG" -p "$ASSET_GLOB" -D "$tmp" || return 1
  local arc
  arc="$(ls "$tmp"/$ASSET_GLOB 2>/dev/null | head -1)"
  [ -n "$arc" ] || return 1
  rm -rf "$REPO_DIR/speechtotext/webui"
  tar -xzf "$arc" -C "$REPO_DIR/speechtotext"
  [ -f "$REPO_DIR/speechtotext/webui/index.html" ] || return 1
}

health_ok() {
  local deadline=$(( SECONDS + HEALTH_TIMEOUT ))
  while [ "$SECONDS" -lt "$deadline" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' \
              -H "Authorization: Bearer $TOKEN" "$HEALTH_URL" || echo 000)"
    [ "$code" = "200" ] && return 0
    sleep 2
  done
  return 1
}

git checkout --quiet "$latest" || rollback "checkout"
fetch_webui "$latest" || rollback "webui-asset"
uv pip install --python "$VENV/bin/python" -e ".[api]" \
   -c requirements-server-cpu.txt --extra-index-url "$PIP_INDEX" --quiet || rollback "pip"
sudo -- systemctl restart "$SERVE_UNIT" "$WATCH_UNIT" || rollback "restart"
health_ok || rollback "health"

rm -f "$MARKER"
log "updated to $latest OK"
