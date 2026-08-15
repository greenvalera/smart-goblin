#!/bin/bash
set -euo pipefail

# Only needed in Claude Code on the web - each session gets a fresh container.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if command -v railway >/dev/null 2>&1; then
  exit 0
fi

case "$(uname -m)" in
  x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
  aarch64|arm64) TARGET="aarch64-unknown-linux-musl" ;;
  *)
    echo "railway CLI: unsupported architecture $(uname -m), skipping install" >&2
    exit 0
    ;;
esac

# Resolve the latest release tag via the git protocol (works even when
# api.github.com / the GitHub releases HTML page are blocked for this
# session's network policy - release download assets are reachable though).
VERSION="$(git ls-remote --tags --refs --sort=-v:refname \
  https://github.com/railwayapp/cli 2>/dev/null \
  | sed -n 's#.*refs/tags/v##p' | head -1)"

if [ -z "$VERSION" ]; then
  echo "railway CLI: could not resolve latest version, skipping install" >&2
  exit 0
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

URL="https://github.com/railwayapp/cli/releases/download/v${VERSION}/railway-v${VERSION}-${TARGET}.tar.gz"
if ! curl -fsSL --max-time 60 -o "$TMP_DIR/railway.tar.gz" "$URL"; then
  echo "railway CLI: download failed ($URL), skipping install" >&2
  exit 0
fi

tar -xzf "$TMP_DIR/railway.tar.gz" -C "$TMP_DIR"
install -m 0755 "$TMP_DIR/railway" /usr/local/bin/railway

echo "railway CLI v${VERSION} installed to /usr/local/bin/railway"
