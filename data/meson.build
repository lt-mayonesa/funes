i18n = import('i18n')
gnome = import('gnome')

install_data(
  'org.x.funes.gschema.xml',
  install_dir: join_paths(get_option('datadir'), 'glib-2.0', 'schemas'),
)

install_man('funes.1')

i18n.merge_file(
  input: 'org.x.funes.desktop.in',
  output: 'org.x.funes.desktop',
  type: 'desktop',
  po_dir: join_paths(meson.project_source_root(), 'po'),
  install: true,
  install_dir: join_paths(get_option('datadir'), 'applications'),
)

# Icons: one scalable app icon, its symbolic sibling for the tray, and a 256px
# raster for packaging and the README.
icondir = join_paths(get_option('datadir'), 'icons', 'hicolor')

install_data(
  'icons/hicolor/scalable/apps/org.x.funes.svg',
  install_dir: join_paths(icondir, 'scalable', 'apps'),
)
install_data(
  'icons/hicolor/symbolic/apps/org.x.funes-symbolic.svg',
  install_dir: join_paths(icondir, 'symbolic', 'apps'),
)
install_data(
  'icons/hicolor/256x256/apps/org.x.funes.png',
  install_dir: join_paths(icondir, '256x256', 'apps'),
)

gnome.post_install(glib_compile_schemas: true, gtk_update_icon_cache: true)

# Compile schemas inside the build dir so Funes can run uninstalled
# (see scripts/run.sh, which exports GSETTINGS_SCHEMA_DIR).
custom_target(
  'gschemas-dev',
  input: 'org.x.funes.gschema.xml',
  output: 'gschemas.compiled',
  command: [
    find_program('glib-compile-schemas'),
    '--targetdir', meson.current_build_dir(),
    meson.current_source_dir(),
  ],
  build_by_default: true,
)
