#!/usr/bin/env bash
# Build + publish the hub web-UI bundle as a GitHub Release asset.
#
#   scripts/publish-release.sh package --tag vX.Y.Z [--repo-dir DIR] \
#       [--out-dir DIR] [--skip-build]
#   scripts/publish-release.sh publish --tag vX.Y.Z [--repo-dir DIR] [--notes STR]
#
# `package` builds (npm run build:hub) and tars speechtotext/webui into
# webui-<tag>.tar.gz. `publish` runs package then uploads to the GH release.
# The archive stores paths as webui/... so the updater extracts with
#   tar -xzf webui-<tag>.tar.gz -C <repo>/speechtotext
set -euo pipefail

MODE="${1:?usage: publish-release.sh package|publish --tag vX.Y.Z}"
shift

TAG=""
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR=""
SKIP_BUILD=0
NOTES=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --notes) NOTES="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$TAG" ] || { echo "--tag is required" >&2; exit 2; }
[ -n "$OUT_DIR" ] || OUT_DIR="$REPO_DIR"

package() {
  if [ "$SKIP_BUILD" -eq 0 ]; then
    ( cd "$REPO_DIR/ui" && npm run build:hub )
  fi
  local bundle="$REPO_DIR/speechtotext/webui"
  [ -f "$bundle/index.html" ] || { echo "no built bundle at $bundle" >&2; exit 1; }
  local archive="$OUT_DIR/webui-$TAG.tar.gz"
  tar -czf "$archive" -C "$REPO_DIR/speechtotext" webui
  echo "$archive"
}

case "$MODE" in
  package)
    package
    ;;
  publish)
    archive="$(package)"
    if gh release view "$TAG" --repo lieuwe89/LocalLexis >/dev/null 2>&1; then
      gh release upload "$TAG" "$archive" --repo lieuwe89/LocalLexis --clobber
    else
      gh release create "$TAG" "$archive" --repo lieuwe89/LocalLexis \
        --title "$TAG" --notes "${NOTES:-$TAG}"
    fi
    ;;
  *)
    echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
