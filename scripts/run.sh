#!/usr/bin/env bash
# Run Funes from the build tree without installing.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build="$root/_build"

if [[ ! -d "$build" ]]; then
  meson setup "$build" "$root"
fi
meson compile -C "$build"

export GSETTINGS_SCHEMA_DIR="$build/data"
exec "$build/funes" "$@"
