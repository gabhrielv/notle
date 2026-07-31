#!/usr/bin/env bash
# Vendors the Worker's Python dependencies into python_modules/.
#
# Run after any change to the Worker's dependencies in pyproject.toml. The
# result is committed lock (pylock.toml) plus an ignored tree (python_modules/),
# so a fresh clone runs this once and wrangler finds what it needs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="notle-vendor"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "building $IMAGE (first run only)..."
    docker build -q -t "$IMAGE" "$REPO_ROOT/tools/vendor" >/dev/null
fi

# Runs as the caller so the vendored tree is not left owned by root.
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$REPO_ROOT":/repo \
    "$IMAGE" "$@"

echo "vendored into python_modules/"
