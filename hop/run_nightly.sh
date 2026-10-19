#!/bin/sh
set -eu
since="${1:-}"
[ -n "$since" ] || since="$(date -d yesterday +%F)"
cd "$(dirname "$0")/.."
exec ${PYTHON:-uv run --frozen --extra db python} -m parltopics.nightly --since "$since" ${NIGHTLY_ARGS:-}
