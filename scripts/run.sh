#!/usr/bin/env bash
# Run Funes straight from the source tree, without installing anything.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
schemas="$root/_build/data"

mkdir -p "$schemas"
glib-compile-schemas --targetdir "$schemas" "$root/data"

export GSETTINGS_SCHEMA_DIR="$schemas"
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 "$root/app/funes_app.py" "$@"
