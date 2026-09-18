install_data(
  'org.funes.Funes.gschema.xml',
  install_dir: datadir / 'glib-2.0' / 'schemas',
)

install_data(
  'org.funes.Funes.desktop',
  install_dir: datadir / 'applications',
)

# Compile schemas inside the build dir so `funes` can run uninstalled
# (see scripts/run.sh which exports GSETTINGS_SCHEMA_DIR).
custom_target(
  'gschemas-dev',
  input: 'org.funes.Funes.gschema.xml',
  output: 'gschemas.compiled',
  command: [
    find_program('glib-compile-schemas'),
    '--targetdir', meson.current_build_dir(),
    meson.current_source_dir(),
  ],
  build_by_default: true,
)
