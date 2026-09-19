#!/usr/bin/env bash
# Remove a locally installed (meson --prefix=/usr/local) Funes.
set -eu

rm -f /usr/local/bin/funes
rm -rf /usr/local/share/funes
rm -rf /usr/local/lib/python3/dist-packages/funes
rm -f /usr/local/share/applications/org.x.funes.desktop
rm -f /usr/local/share/glib-2.0/schemas/org.x.funes.gschema.xml
glib-compile-schemas /usr/local/share/glib-2.0/schemas 2>/dev/null || true
update-desktop-database /usr/local/share/applications 2>/dev/null || true
