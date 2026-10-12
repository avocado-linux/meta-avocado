#!/bin/bash
# Serve a build's avocado feed (see meta-avocado/classes/avocado-feed.bbclass).
# The container keeps serving across rebuilds; each index run swaps repodata
# in place, so start it once per build dir.
#
#   scripts/feed-serve.sh [BUILD_DIR]    # build-<m>, or $BUILDDIR in a kas shell
#   scripts/feed-serve.sh --stop
#
# Then: AVOCADO_REPO_URL=http://localhost:${PORT:-8080} avocado install
set -euo pipefail

NAME=${NAME:-avocado-feed}
PORT=${PORT:-8080}

if [ "${1:-}" = "--stop" ]; then
    exec docker rm -f "$NAME"
fi

BUILD_DIR=$(realpath "${1:-${BUILDDIR:-build}}")
# Accept the bitbake build dir or the kas work dir around it (build-<m>/build).
for DEPLOY in "$BUILD_DIR/tmp/deploy" "$BUILD_DIR/build/tmp/deploy"; do
    [ -d "$DEPLOY/avocado-feed" ] && break
done
if [ ! -d "$DEPLOY/avocado-feed" ]; then
    echo "no feed at $DEPLOY/avocado-feed; run: bitbake avocado-feed-index" >&2
    exit 1
fi

CONF="$(cd "$(dirname "$0")/.." && pwd)/support/feed-serve/nginx.conf"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --restart unless-stopped --name "$NAME" -p "$PORT:80" \
    -v "$DEPLOY:/deploy:ro" -v "$CONF:/etc/nginx/conf.d/default.conf:ro" \
    docker.io/library/nginx:alpine >/dev/null
echo "serving $DEPLOY/avocado-feed on http://localhost:$PORT"
echo "  export AVOCADO_REPO_URL=http://localhost:$PORT"
