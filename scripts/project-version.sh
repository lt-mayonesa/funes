#!/usr/bin/env bash
# Print the project version declared in meson.build.
#
# Called directly by CI and wrapped by `fns project-version`; hexagon runs it
# with /bin/sh, so keep it POSIX (no `pipefail`).
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
sed -n "s/^[[:space:]]*version:[[:space:]]*'\([^']*\)'.*/\1/p" "$root/meson.build" | head -1
