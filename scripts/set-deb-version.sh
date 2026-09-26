#!/usr/bin/env bash
# Regenerate debian/changelog for a given package version.
#
# Usage: fns set-deb-version <version> [distribution] [message]
#
# The changelog kept in git is only a stub; CI calls this script so the built
# package always carries the version derived from meson.build / the git tag.
#
# Wrapped by `fns set-deb-version`; hexagon runs it with /bin/sh, so keep it
# POSIX (no `pipefail`).
set -eu

version="${1:?usage: set-deb-version.sh <version> [distribution] [message]}"
distribution="${2:-unstable}"
message="${3:-Automated build.}"

root="$(cd "$(dirname "$0")/.." && pwd)"
name="$(git -C "$root" config user.name 2>/dev/null || true)"
email="$(git -C "$root" config user.email 2>/dev/null || true)"
maintainer="${DEBFULLNAME:-${name:-Joaco Campero}} <${DEBEMAIL:-${email:-juacocampero@gmail.com}}>"
date="$(date -R)"

cat > "$root/debian/changelog" <<EOF
funes (${version}) ${distribution}; urgency=medium

  * ${message}

 -- ${maintainer}  ${date}
EOF

echo "debian/changelog set to ${version} (${distribution})"
