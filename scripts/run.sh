#!/usr/bin/env bash
# Run Funes straight from the source tree, without installing anything.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
schemas="$root/_build/data"

mkdir -p "$schemas"
glib-compile-schemas --targetdir "$schemas" "$root/data"

# Let GTK and libxapp find the uninstalled icons (data/icons/hicolor/...).
icons="$root/_build/icon-data"
mkdir -p "$icons"
ln -sfn "$root/data/icons" "$icons/icons"

export GSETTINGS_SCHEMA_DIR="$schemas"
export XDG_DATA_DIRS="$icons${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}:/usr/local/share:/usr/share"
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 "$root/app/funes_app.py" "$@"
